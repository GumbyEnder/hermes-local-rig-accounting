"""
Local Rig Accounting Plugin for Hermes Agent

Surfaces realistic per-token costs for local LLM inference by tracking
hardware depreciation, energy consumption, and measured throughput.

Config (in config.yaml):
  local_rig:
    hardware_cost_usd: 5000
    lifespan_years: 3
    gpu_only_cost_usd: 2500         # optional
    avg_power_watts: 450
    electricity_rate_per_kwh: 0.15
    hostname: my-server             # optional auto-detect
    auto_submit: true               # auto-submit after /rig-benchmark (default true)
    submit_target: cloudflare       # 'cloudflare' (Worker) or 'github' (Issues)
    worker_url: https://benchmark-worker.agentic-accounting.workers.dev  # optional override

Slash commands:
  /rig-cost       — Show current session's local cost estimate
  /rig-summary    — Full rig economics dashboard
  /rig-benchmark  — Run TPS benchmark for current model

Tools:
  rig_cost        — Estimate cost for a given model + token count
  rig_summary     — Get rig economics summary
  rig_benchmark   — Benchmark a local model's TPS
  rig_submit      — Submit benchmark to community leaderboard
  rig_rates       — Look up regional electricity rates
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import get_hermes_home

from . import hooks
from .cost_calculator import estimate_local_cost, estimate_session_cost, rig_summary
from .rig_config import load_rig_config, lookup_electricity_rate
from .benchmark import run_benchmark

logger = logging.getLogger("local_rig_accounting")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hermes_home() -> Path:
    return Path(get_hermes_home())


def _tool_result(data: Any) -> str:
    """Serialize to JSON string (standard tool result format)."""
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, default=str)


def _tool_error(msg: str) -> str:
    return json.dumps({"error": msg})


def _format_hardware_string(hardware: dict) -> str:
    """Format hardware dict into a concise string for leaderboard display."""
    gpus = hardware.get("gpu", [])
    if gpus:
        gpu = gpus[0]
        model = gpu.get("model", "unknown")
        vram = gpu.get("vram_mb", 0)
        return f"{model} ({vram} MB)" if vram else model
    cpu = hardware.get("cpu", {})
    if cpu:
        return cpu.get("model", "unknown CPU")
    return "unknown"


def _spinner(message: str, total_steps: int = 0):
    """Live progress indicator for long-running benchmark."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    start = time.time()
    def render(step: int = 0) -> str:
        nonlocal idx
        frame = frames[idx % len(frames)]
        idx += 1
        elapsed = time.time() - start
        if total_steps > 0:
            pct = int((step / total_steps) * 100)
            return f"\r{frame} {message} — {step}/{total_steps} ({pct}%) — {elapsed:.1f}s"
        return f"\r{frame} {message} — {elapsed:.1f}s"
    def update(step: int) -> str:
        return render(step)
    def complete(final_msg: str = "") -> str:
        return f"\r✅ {final_msg or message}"
    return render, update, complete


def _is_local_model(model: str = "", provider: str = "", base_url: str = "") -> bool:
    """Check if a model route points to local inference."""
    return hooks._is_local_provider(provider, base_url)


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------

def _handle_rig_cost(args: dict, **kwargs) -> str:
    """Estimate local inference cost for a given model + token count."""
    model = args.get("model", "")
    input_tokens = int(args.get("input_tokens", 0))
    output_tokens = int(args.get("output_tokens", 0))

    if not model:
        # Try to use current session's stats if no model specified
        stats = hooks.get_session_stats()
        if stats["local_api_calls"] > 0:
            result = estimate_session_cost(
                _hermes_home(), model or "local/unknown",
                input_tokens=stats["local_input_tokens"],
                output_tokens=stats["local_output_tokens"],
            )
            if result:
                return _tool_result(result)

        return _tool_error("No model specified and no local inference detected in this session.")

    if input_tokens == 0 and output_tokens == 0:
        # Just return per-million rates
        result = estimate_local_cost(_hermes_home(), model)
        if result is None:
            return _tool_result({
                "status": "not_configured",
                "message": "Local rig not configured. Add a 'local_rig:' section to your config.yaml.",
            })
        return _tool_result({
            "model": model,
            "input_cost_per_million_tokens": float(result.input_cost_per_million),
            "output_cost_per_million_tokens": float(result.output_cost_per_million),
            "hourly_cost_usd": result.hourly_cost_usd,
            "measured_tps": result.tps,
            "label": result.label,
            "notes": list(result.notes),
        })

    result = estimate_session_cost(_hermes_home(), model, input_tokens, output_tokens)
    if result is None:
        return _tool_result({
            "status": "not_configured",
            "message": "Local rig not configured. Add a 'local_rig:' section to your config.yaml.",
        })
    return _tool_result(result)


def _handle_rig_summary(args: dict, **kwargs) -> str:
    """Return full rig economics summary."""
    summary = rig_summary(_hermes_home())
    return _tool_result(summary)


def _handle_rig_benchmark(args: dict, **kwargs) -> str:
    """Run a TPS benchmark for a local model."""
    model = args.get("model", "")
    base_url = args.get("base_url", "http://127.0.0.1:1234/v1")
    api_key = args.get("api_key", "not-needed")
    max_tokens = int(args.get("max_tokens", 512))

    if not model:
        return _tool_error("model parameter required (e.g. 'qwen3.5-9b' or 'lmstudio-local/qwen3.5-9b')")

    # Spinner thread
    import threading, sys, time
    stop_spinner = False

    def spin():
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        start = time.time()
        while not stop_spinner:
            frame = frames[idx % len(frames)]
            elapsed = time.time() - start
            msg = f"\r{frame} Benchmarking '{model}'... — {elapsed:.1f}s"
            sys.stderr.write(msg)
            sys.stderr.flush()
            idx += 1
            time.sleep(0.1)
        sys.stderr.write(f"\r✅ Benchmark complete — {time.time()-start:.1f}s        \n")
        sys.stderr.flush()

    t = threading.Thread(target=spin, daemon=True)
    t.start()

    try:
        result = run_benchmark(
            _hermes_home(),
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_tokens=max_tokens,
        )
    finally:
        stop_spinner = True
        t.join(timeout=1.0)

    return _tool_result(result)


def _check_rig_available() -> bool:
    """Rig accounting is always available — the check is whether it's configured."""
    return True


# ---------------------------------------------------------------------------
# Slash Command Handlers
# ---------------------------------------------------------------------------

def _slash_rig_cost(raw_args: str) -> str:
    """Show current session's local inference cost estimate."""
    home = _hermes_home()
    stats = hooks.get_session_stats()

    if stats["local_api_calls"] == 0:
        return "No local inference detected in this session."

    result = estimate_session_cost(
        home,
        model="local/session",
        input_tokens=stats["local_input_tokens"],
        output_tokens=stats["local_output_tokens"],
    )

    if result is None:
        return "Local rig not configured. Add a 'local_rig:' section to your config.yaml."

    lines = [
        f"⚡ Local Inference — This Session",
        f"   Tokens: {stats['local_input_tokens']:,} in / {stats['local_output_tokens']:,} out",
        f"   API calls: {stats['local_api_calls']}",
        f"   Cost: {result.get('cost_label', 'n/a')}",
        f"   Hourly rate: ${result.get('hourly_cost_usd', 0):.4f}/hr",
        f"   Measured TPS: {result.get('tps', 0):.1f}",
    ]

    if result.get("notes"):
        for note in result["notes"]:
            lines.append(f"   ⚠ {note}")

    return "\n".join(lines)


def _slash_rig_summary(raw_args: str) -> str:
    """Show full rig economics dashboard."""
    summary = rig_summary(_hermes_home())

    if not summary.get("configured"):
        return (
            "⚙ Local Rig Not Configured\n\n"
            "Add a 'local_rig:' section to your config.yaml:\n\n"
            "  local_rig:\n"
            "    hardware_cost_usd: 5000\n"
            "    lifespan_years: 3\n"
            "    avg_power_watts: 450\n"
            "    electricity_rate_per_kwh: 0.15\n"
        )

    lines = [
        f"🖥 Local Rig: {summary['rig_label']}",
        f"   Hardware cost: ${summary['hardware_cost_usd']:,.0f}",
    ]
    if summary.get("gpu_only_cost_usd") is not None:
        lines.append(f"   GPU-only cost: ${summary['gpu_only_cost_usd']:,.0f}")
    lines += [
        f"   Depreciable base: ${summary['depreciable_cost_usd']:,.0f}",
        f"   Lifespan: {summary['lifespan_years']:.1f} years ({summary['lifespan_years'] * 8766:.0f} hours)",
        f"   Power draw: {summary['avg_power_watts']:.0f}W @ ${summary['electricity_rate_per_kwh']:.3f}/kWh",
        f"   ─────────────────────────────────",
        f"   Depreciation: ${summary['depreciation_per_hour']:.4f}/hr",
        f"   Energy: ${summary['energy_cost_per_hour']:.4f}/hr",
        f"   Total: ${summary['total_hourly_cost']:.4f}/hr",
        f"   ─────────────────────────────────",
        f"   Cumulative inference: {summary['cumulative_inference_hours']:.1f} hours",
        f"   Benchmarked models: {summary['benchmarked_models']}",
    ]

    per_model = summary.get("per_model_costs", {})
    if per_model:
        lines.append(f"\n   📊 Per-Model Costs (per million tokens):")
        for model_key, costs in sorted(per_model.items()):
            lines.append(f"     {model_key}: ${costs['cost_per_million']:.4f}/M ({costs['tps']:.1f} TPS)")

    return "\n".join(lines)


def _slash_rig_benchmark(raw_args: str) -> str:
    """Run a TPS benchmark for a local model."""
    # Parse args: "model_name [base_url]"
    parts = raw_args.strip().split()
    if not parts:
        return "Usage: /rig-benchmark <model_name> [base_url]\nExample: /rig-benchmark qwen3.5-9b"

    model = parts[0]
    base_url = parts[1] if len(parts) > 1 else "http://127.0.0.1:1234/v1"

    result = run_benchmark(_hermes_home(), model=model, base_url=base_url)

    if "error" in result:
        return f"❌ Benchmark failed: {result['error']}"

    lines = [
        f"✅ Benchmark Complete: {result.get('model', model)}",
        f"   Output TPS: {result.get('avg_tps', 0):.2f} tok/s",
        f"   Total TPS: {result.get('total_tps', 0):.2f} tok/s",
        f"   Tokens: {result.get('output_tokens', 0)} out / {result.get('input_tokens', 0)} in",
        f"   Elapsed: {result.get('elapsed_seconds', 0):.2f}s",
        f"   Cached as: {result.get('cached_as', model)}",
    ]

    # Show hardware info if collected
    hw = result.get("hardware", {})
    if hw and hw.get("cpu", {}).get("model"):
        gpu_names = ", ".join(g.get("model", "?") for g in hw.get("gpu", []))
        lines.append(f"   Hardware: {hw['cpu']['model']} | {gpu_names} | {hw.get('ram_gb', 0):.0f}GB RAM")

    env = result.get("environment", "local")
    if env == "remote":
        lines.append(f"   ⚠ Remote provider — cost estimates use local rig rates for comparison only")

    # Show estimated cost with this benchmark
    cost_result = estimate_local_cost(_hermes_home(), model, tps_override=result.get("avg_tps"))
    if cost_result:
        lines.append(f"   ─────────────────────────────────")
        lines.append(f"   Estimated cost: ${float(cost_result.input_cost_per_million):.4f}/M tokens")
        lines.append(f"   Hourly cost: ${cost_result.hourly_cost_usd:.4f}/hr")

    # --- Auto-submit or suggestion (non-blocking) ---
    rig_config = load_rig_config(_hermes_home())
    if rig_config.auto_submit:
        # Auto-submit mode: delegate to _handle_rig_submit which respects submit_target
        lines.append("")
        lines.append("🔗 auto_submit enabled — submitting to community leaderboard…")
        submission_res_str = _handle_rig_submit({"model": model, "dry_run": False})
        try:
            submission_res = json.loads(submission_res_str)
            if submission_res.get("status") == "submitted":
                target = submission_res.get("target", "unknown")
                if target == "cloudflare":
                    # Cloudflare Worker: show concise confirmation
                    msg = submission_res.get("message", "Benchmark submitted to cloud leaderboard")
                    lines.append(f"✅ {msg}")
                elif target == "github":
                    lines.append(f"✅ Submitted! {submission_res.get('issue_url')}")
                else:
                    lines.append(f"✅ Submitted ({target})")
            else:
                err = submission_res.get("error", "unknown")
                # Provide targeted guidance based on error
                if "gh CLI not found" in err or "not authenticated" in err.lower():
                    lines.append(f"⚠️  GitHub submission needed: {err}")
                    lines.append("   Either: install/login gh CLI, or set submit_target: cloudflare")
                else:
                    lines.append(f"❌ Submission failed: {err}")
        except Exception:
            lines.append(f"❌ Submission error: {submission_res_str}")
    else:
        # Manual suggestion: show /rig-submit command with pre-filled model
        lines.append("")
        lines.append("💡 Share this benchmark: run →  /rig-submit model=" + model)

    return "\n".join(lines)


def _build_submission_payload(hermes_home: Path, model: str = "") -> Optional[Dict[str, Any]]:
    """Build a community benchmark submission payload from cached data.

    Gathers: hardware info, latest benchmark, cost model config.
    Returns None if no benchmark data available.
    """
    from .benchmark import _collect_hardware_info

    # Load cached benchmarks
    from .cost_calculator import _load_benchmarks as _lb
    benchmarks = _lb(hermes_home)

    if not benchmarks:
        return None

    # Pick the model to submit (latest or specified)
    if model:
        key = model.split("/", 1)[1] if "/" in model and model not in benchmarks else model
        bench = benchmarks.get(key) or benchmarks.get(model)
        if not bench:
            # Try partial match
            for k, v in benchmarks.items():
                if model in k:
                    bench = v
                    key = k
                    break
    else:
        # Use the most recent benchmark
        key = max(benchmarks.keys(), key=lambda k: benchmarks[k].get("timestamp", ""))
        bench = benchmarks[key]

    if not bench:
        return None

    # Load rig config for cost model
    rig_config = load_rig_config(hermes_home)
    profile = rig_config.active

    # Collect hardware
    hardware = _collect_hardware_info()

    # Build submission matching our JSON schema
    tps = float(bench.get("avg_tps", 0))
    hourly = profile.hourly_cost(rig_config.cumulative_inference_hours)
    tokens_per_hour = tps * 3600.0
    cost_per_million = round(hourly / tokens_per_hour * 1_000_000, 6) if tokens_per_hour > 0 else 0.0

    submission = {
        "hardware": hardware,
        "benchmark": {
            "model": bench.get("model", key),
            "quantization": bench.get("quantization", ""),
            "avg_tps": tps,
            "total_tps": float(bench.get("total_tps", 0)),
            "output_tokens": int(bench.get("output_tokens", 0)),
            "input_tokens": int(bench.get("input_tokens", 0)),
            "max_tokens": int(bench.get("max_tokens", 512)),
            "elapsed_seconds": float(bench.get("elapsed_seconds", 0)),
            "backend": bench.get("backend", ""),
            "environment": bench.get("environment", "local"),
        },
        "cost_model": {
            "hardware_cost_usd": profile.hardware_cost_usd,
            "gpu_cost_usd": profile.gpu_only_cost_usd,
            "lifespan_years": profile.lifespan_years,
            "avg_power_watts": profile.avg_power_watts,
            "electricity_rate_per_kwh": profile.electricity_rate_per_kwh,
            "depreciation_per_hour": round(profile.depreciation_per_hour(rig_config.cumulative_inference_hours), 4),
            "energy_per_hour": round(profile.energy_cost_per_hour, 4),
            "total_hourly_cost": round(hourly, 4),
            "cost_per_million_tokens": cost_per_million,
        },
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "submission_version": "1.0",
    }

    return submission


def _handle_rig_submit(args: dict, **kwargs) -> str:
    """Submit benchmark results to the community leaderboard (Cloudflare Worker or GitHub fallback)."""
    model = args.get("model", "")
    dry_run = args.get("dry_run", False)

    submission = _build_submission_payload(_hermes_home(), model=model)

    if submission is None:
        return _tool_error("No benchmark data available. Run /rig-benchmark first.")

    if dry_run:
        return _tool_result({
            "status": "dry_run",
            "message": "This is what would be submitted. Use dry_run=false to submit.",
            "payload": submission,
        })

    # Load config for submission target
    from .rig_config import load_rig_config
    rig_config = load_rig_config(_hermes_home())
    submit_target = getattr(rig_config, "submit_target", "cloudflare")
    worker_url = getattr(rig_config, "worker_url", None) or "https://benchmark-worker.agentic-accounting.workers.dev"
    profile = rig_config.active

    # Build Worker payload (includes metadata)
    worker_payload = {
        "submission": submission,
        "metadata": {
            "rig_config": {
                "hardware_cost_usd": profile.hardware_cost_usd,
                "gpu_only_cost_usd": profile.gpu_only_cost_usd,
                "lifespan_years": profile.lifespan_years,
                "avg_power_watts": profile.avg_power_watts,
                "electricity_rate_per_kwh": profile.electricity_rate_per_kwh,
            },
            "hermes_version": "0.4.0",
            "submission_version": "2.0"
        }
    }

    import urllib.request
    import json as _json

    if submit_target == "cloudflare":
        try:
            payload_bytes = _json.dumps(worker_payload).encode("utf-8")
            req = urllib.request.Request(
                f"{worker_url}/api/benchmarks",
                data=payload_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    result = _json.loads(resp.read().decode("utf-8"))
                    return _tool_result({
                        "status": "submitted",
                        "target": "cloudflare",
                        "worker_id": result.get("id"),
                        "message": result.get("message", "Benchmark submitted"),
                        "model": submission["benchmark"]["model"],
                        "tps": submission["benchmark"]["avg_tps"],
                    })
                else:
                    error_body = resp.read().decode("utf-8")
                    raise Exception(f"Worker returned {resp.status}: {error_body}")
        except Exception as e:
            # Fallback to GitHub if configured
            if submit_target == "cloudflare":
                # Try GitHub as fallback
                submit_target = "github"
            else:
                raise

    if submit_target == "github":
        # Legacy GitHub Issues fallback
        title = f"📊 Benchmark: {submission['benchmark']['model']} @ {submission['benchmark']['avg_tps']:.1f} TPS on {submission['hardware'].get('gpu', [{}])[0].get('model', 'unknown GPU')}"
        body = f"""### Benchmark Submission

```json
{_json.dumps(submission, indent=2)}
```

---

**Auto-submitted via `/rig-submit`** | [Local Rig Accounting Plugin](https://github.com/GumbyEnder/hermes-local-rig-accounting)
"""
        try:
            result = subprocess.run(
                ["gh", "issue", "create",
                 "--repo", "GumbyEnder/hermes-local-rig-accounting",
                 "--title", title,
                 "--body", body,
                 "--label", "benchmark"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                issue_url = result.stdout.strip()
                return _tool_result({
                    "status": "submitted",
                    "target": "github",
                    "issue_url": issue_url,
                    "model": submission["benchmark"]["model"],
                    "tps": submission["benchmark"]["avg_tps"],
                    "gpu": submission["hardware"].get("gpu", [{}])[0].get("model", "unknown"),
                })
            else:
                return _tool_error(f"GitHub issue creation failed: {result.stderr.strip()}")
        except FileNotFoundError:
            return _tool_error("gh CLI not found. Install: https://cli.github.com/")
        except Exception as e:
            return _tool_error(f"GitHub submission failed: {e}")

    return _tool_error("No submission target configured")


def _slash_rig_submit(raw_args: str) -> str:
    """Submit benchmark results to the community leaderboard."""
    import json as _json

    parts = raw_args.strip().split()
    model = parts[0] if parts else ""
    dry_run = "--dry-run" in parts

    submission = _build_submission_payload(_hermes_home(), model=model)

    if submission is None:
        return "❌ No benchmark data available. Run /rig-benchmark first."

    # Preview
    lines = [
        "📋 Benchmark Submission Preview",
        "─────────────────────────────────",
        f"  GPU: {submission['hardware'].get('gpu', [{}])[0].get('model', 'N/A')}",
        f"  CPU: {submission['hardware'].get('cpu', {}).get('model', 'N/A')}",
        f"  RAM: {submission['hardware'].get('ram_gb', 0):.0f} GB",
        f"  Model: {submission['benchmark']['model']}",
        f"  TPS: {submission['benchmark']['avg_tps']:.2f}",
        f"  $/M tokens: ${submission['cost_model']['cost_per_million_tokens']:.4f}",
        "─────────────────────────────────",
    ]

    if dry_run:
        lines.append("")
        lines.append("Full JSON payload:")
        lines.append(f"```json\n{_json.dumps(submission, indent=2)}\n```")
        lines.append("")
        lines.append("(dry-run mode — nothing submitted)")
        return "\n".join(lines)

    # Actually submit
    try:
        import subprocess

        title = f"📊 Benchmark: {submission['benchmark']['model']} @ {submission['benchmark']['avg_tps']:.1f} TPS on {submission['hardware'].get('gpu', [{}])[0].get('model', 'unknown GPU')}"
        body = f"""### Benchmark Submission

```json
{_json.dumps(submission, indent=2)}
```

---

**Auto-submitted via `/rig-submit`** | [Local Rig Accounting Plugin](https://github.com/GumbyEnder/hermes-local-rig-accounting)
"""

        result = subprocess.run(
            ["gh", "issue", "create",
             "--repo", "GumbyEnder/hermes-local-rig-accounting",
             "--title", title,
             "--body", body,
             "--label", "benchmark"],
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode == 0:
            issue_url = result.stdout.strip()
            lines.append(f"✅ Submitted! {issue_url}")
            return "\n".join(lines)
        else:
            lines.append(f"❌ Submission failed: {result.stderr.strip()}")
            return "\n".join(lines)

    except FileNotFoundError:
        lines.append("❌ gh CLI not found. Install from https://cli.github.com/")
        return "\n".join(lines)
    except Exception as e:
        lines.append(f"❌ Submission failed: {e}")
        return "\n".join(lines)


def _handle_rig_rates(args: dict, **kwargs) -> str:
    """Look up regional electricity rates."""
    region = args.get("region", "").strip()
    if not region:
        # Show a summary of popular regions
        try:
            import yaml
            from .rig_config import _POWER_RATES_FILE
            if _POWER_RATES_FILE.exists():
                data = yaml.safe_load(_POWER_RATES_FILE.read_text()) or {}
                lines = ["⚡ **Regional Electricity Rates (USD/kWh)**", ""]
                lines.append(f"US National Average: ${data.get('us_national_average', 0):.4f}/kWh")
                lines.append("")
                lines.append("**Most Expensive States:**")
                states = data.get("us_states", {})
                by_rate = sorted(states.items(), key=lambda x: x[1], reverse=True)
                for name, rate in by_rate[:5]:
                    lines.append(f"  {name}: ${rate:.4f}/kWh")
                lines.append("")
                lines.append("**Cheapest States:**")
                for name, rate in by_rate[-5:]:
                    lines.append(f"  {name}: ${rate:.4f}/kWh")
                lines.append("")
                lines.append("**International:**")
                intl = data.get("international", {})
                for name, rate in sorted(intl.items(), key=lambda x: x[1], reverse=True)[:8]:
                    lines.append(f"  {name}: ${rate:.2f}/kWh")
                lines.append("")
                lines.append("Use `rig_rates` with a `region` param to look up a specific rate.")
                lines.append("Config: `electricity_rate_per_kwh: auto` + `electricity_region: Texas`")
                return "\n".join(lines)
        except Exception:
            pass
        return "No region specified and rate data unavailable."

    rate = lookup_electricity_rate(region)
    if rate is not None:
        # Calculate impact on cost for a typical rig
        sample_watts = 450
        sample_energy_hr = (sample_watts / 1000) * rate
        return "\n".join([
            f"⚡ **Electricity Rate for {region}**",
            f"",
            f"Rate: **${rate:.4f}/kWh** ({rate*100:.2f}¢/kWh)",
            f"",
            f"Impact on a 450W rig:",
            f"  Energy cost: ${sample_energy_hr:.3f}/hr",
            f"  At 50 TPS: ${sample_energy_hr / 50 * 1_000_000 / 3600:.2f}/M tokens (energy only)",
            f"",
            f"To use in config.yaml:",
            f"  electricity_rate_per_kwh: auto",
            f"  electricity_region: {region}",
        ])
    else:
        return "\n".join([
            f"❌ No rate found for '{region}'",
            f"",
            f"Try: a US state name (e.g. 'Texas', 'California'),",
            f"     a country name (e.g. 'Germany', 'Japan'),",
            f"     or a state abbreviation (e.g. 'TX', 'CA').",
            f"Run `rig_rates` without args to see all available regions.",
        ])


def _slash_rig_rates(args: str = "") -> str:
    """Slash command: /rig-rates [region]"""
    region = args.strip()
    return _handle_rig_rates({"region": region})


# ---------------------------------------------------------------------------
# Plugin Registration
# ---------------------------------------------------------------------------

def register(ctx):
    """Entry point — called once during plugin discovery."""

    # --- Tools ---
    ctx.register_tool(
        name="rig_cost",
        toolset="local_rig_accounting",
        schema={
            "name": "rig_cost",
            "description": (
                "Estimate per-token cost for local LLM inference. "
                "If model + token counts given, returns session-style cost. "
                "If only model given, returns per-million-token rates. "
                "If no args, returns current session's local cost."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model name (e.g. 'qwen3.5-9b'). Optional — uses session stats if omitted.",
                    },
                    "input_tokens": {
                        "type": "integer",
                        "description": "Number of input/prompt tokens. Optional.",
                    },
                    "output_tokens": {
                        "type": "integer",
                        "description": "Number of output/completion tokens. Optional.",
                    },
                },
            },
        },
        handler=_handle_rig_cost,
        check_fn=_check_rig_available,
        description="Estimate local inference cost per token",
        emoji="⚡",
    )

    ctx.register_tool(
        name="rig_summary",
        toolset="local_rig_accounting",
        schema={
            "name": "rig_summary",
            "description": "Get full rig economics summary — hardware cost, depreciation, energy rate, per-model costs.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=_handle_rig_summary,
        check_fn=_check_rig_available,
        description="Full rig economics dashboard",
        emoji="🖥",
    )

    ctx.register_tool(
        name="rig_benchmark",
        toolset="local_rig_accounting",
        schema={
            "name": "rig_benchmark",
            "description": (
                "Run a TPS benchmark for a local model. Sends a standardized prompt "
                "and measures tokens/second. Results are cached for cost calculations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model name to benchmark (e.g. 'qwen3.5-9b').",
                    },
                    "base_url": {
                        "type": "string",
                        "description": "Local inference server URL. Default: http://127.0.0.1:1234/v1",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key (usually not needed for local). Default: 'not-needed'",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Max tokens for benchmark generation. Default: 512",
                    },
                },
                "required": ["model"],
            },
        },
        handler=_handle_rig_benchmark,
        check_fn=_check_rig_available,
        description="Benchmark local model TPS",
        emoji="📊",
    )

    ctx.register_tool(
        name="rig_submit",
        toolset="local_rig_accounting",
        schema={
            "name": "rig_submit",
            "description": (
                "Submit benchmark results to the community leaderboard. "
                "Creates a GitHub issue on the plugin repo with hardware + benchmark + cost data. "
                "Only your GitHub username is included — no other personal info."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model to submit (e.g. 'qwen3.5-9b'). If omitted, submits latest benchmark.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview submission without creating issue. Default: false",
                    },
                },
            },
        },
        handler=_handle_rig_submit,
        check_fn=_check_rig_available,
        description="Submit benchmark to community leaderboard",
        emoji="🏆",
    )

    ctx.register_tool(
        name="rig_rates",
        toolset="local_rig_accounting",
        schema={
            "name": "rig_rates",
            "description": (
                "Look up regional electricity rates (USD/kWh). "
                "Pass a region name (US state, country, abbreviation) to get the rate, "
                "or omit to see a summary of available regions. "
                "Supports auto-config: electricity_rate_per_kwh: auto + electricity_region: Texas"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "description": "Region to look up (e.g. 'Texas', 'CA', 'Germany'). Omit for summary.",
                    },
                },
            },
        },
        handler=_handle_rig_rates,
        check_fn=_check_rig_available,
        description="Look up regional electricity rates",
        emoji="⚡",
    )

    # --- Hooks ---
    home = _hermes_home()

    def _post_api_request_hook(**kwargs):
        on_post_api_request = lambda **kw: hooks.on_post_api_request(home, **kw)
        on_post_api_request(**kwargs)

    def _on_session_start_hook(**kwargs):
        hooks.init_session(home)

    def _on_session_finalize_hook(**kwargs):
        hooks.on_session_finalize(home, **kwargs)

    ctx.register_hook("post_api_request", _post_api_request_hook)
    ctx.register_hook("on_session_start", _on_session_start_hook)
    ctx.register_hook("on_session_finalize", _on_session_finalize_hook)

    # --- Slash Commands ---
    ctx.register_command(
        name="rig-cost",
        handler=_slash_rig_cost,
        description="Show current session's local inference cost estimate",
    )
    ctx.register_command(
        name="rig-summary",
        handler=_slash_rig_summary,
        description="Full rig economics dashboard",
    )
    ctx.register_command(
        name="rig-benchmark",
        handler=_slash_rig_benchmark,
        description="Run TPS benchmark for a local model",
        args_hint="<model_name> [base_url]",
    )
    ctx.register_command(
        name="rig-submit",
        handler=_slash_rig_submit,
        description="Submit benchmark to community leaderboard (GitHub issue)",
        args_hint="[model_name] [--dry-run]",
    )

    ctx.register_command(
        name="rig-rates",
        handler=_slash_rig_rates,
        description="Look up regional electricity rates",
        args_hint="[region_name]",
    )

    logger.info("Local Rig Accounting plugin registered (tools: rig_cost, rig_summary, rig_benchmark, rig_submit, rig_rates)")
