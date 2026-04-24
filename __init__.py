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

Slash commands:
  /rig-cost       — Show current session's local cost estimate
  /rig-summary    — Full rig economics dashboard
  /rig-benchmark  — Run TPS benchmark for current model

Tools:
  rig_cost        — Estimate cost for a given model + token count
  rig_summary     — Get rig economics summary
  rig_benchmark   — Benchmark a local model's TPS
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import get_hermes_home

from . import hooks
from .cost_calculator import estimate_local_cost, estimate_session_cost, rig_summary
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

    result = run_benchmark(
        _hermes_home(),
        model=model,
        base_url=base_url,
        api_key=api_key,
        max_tokens=max_tokens,
    )
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

    # Show estimated cost with this benchmark
    cost_result = estimate_local_cost(_hermes_home(), model, tps_override=result.get("avg_tps"))
    if cost_result:
        lines.append(f"   ─────────────────────────────────")
        lines.append(f"   Estimated cost: ${float(cost_result.input_cost_per_million):.4f}/M tokens")
        lines.append(f"   Hourly cost: ${cost_result.hourly_cost_usd:.4f}/hr")

    return "\n".join(lines)


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

    logger.info("Local Rig Accounting plugin registered (tools: rig_cost, rig_summary, rig_benchmark)")
