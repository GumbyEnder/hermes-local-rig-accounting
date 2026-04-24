#!/usr/bin/env python3
"""Rebuild LEADERBOARD.md from GitHub Issues labeled 'benchmark'.

Reads all open issues with the 'benchmark' label, extracts the JSON
payload from each, computes effective cost, and generates a sorted
markdown table.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "GumbyEnder/hermes-local-rig-accounting")
LEADERBOARD_PATH = Path(__file__).resolve().parent.parent.parent / "LEADERBOARD.md"


def fetch_benchmark_issues() -> list[dict]:
    """Fetch all open issues with the 'benchmark' label via gh CLI."""
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--repo", REPO,
            "--label", "benchmark",
            "--state", "open",
            "--limit", "500",
            "--json", "number,title,body,createdAt",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Warning: gh issue list failed: {result.stderr}")
        return []
    return json.loads(result.stdout)


def extract_benchmark_json(body: str) -> dict | None:
    """Extract the JSON object from a benchmark issue body."""
    # Look for ```json ... ``` block
    match = re.search(r'```json\s*\n(.*?)\n```', body, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def compute_cost_per_m(data: dict) -> float | None:
    """Compute $/M tokens from benchmark data."""
    try:
        cost_model = data.get("cost_model", {})
        cpm = cost_model.get("cost_per_million_tokens")
        if cpm is not None:
            return float(cpm)

        # Fallback: compute from components
        bench = data.get("benchmark", {})
        tps = float(bench.get("avg_tps", 0))
        if tps <= 0:
            return None

        dep_hr = float(cost_model.get("depreciation_per_hour", 0))
        energy_hr = float(cost_model.get("energy_per_hour", 0))
        total_hr = dep_hr + energy_hr
        return round((total_hr / tps) * 1_000_000 / 3600, 4)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def build_entry(data: dict, issue_num: int, created: str) -> dict | None:
    """Build a leaderboard row dict from benchmark data."""
    hw = data.get("hardware", {})
    bench = data.get("benchmark", {})
    cost_model = data.get("cost_model", {})

    gpu_info = hw.get("gpu", [{}])
    if isinstance(gpu_info, list) and gpu_info:
        gpu_model = gpu_info[0].get("model", "Unknown")
        vram = gpu_info[0].get("vram_mb", 0)
        gpu_str = f"{gpu_model}"
        if vram:
            gpu_str += f" {vram // 1024}GB" if vram >= 1024 else f" {vram}MB"
    else:
        gpu_str = "Unknown"

    cpu_info = hw.get("cpu", {})
    cpu_model = cpu_info.get("model", "Unknown")

    ram_gb = hw.get("ram_gb", 0)
    ram_str = f"{int(ram_gb)} GB" if ram_gb else "Unknown"

    model = bench.get("model", "Unknown")
    tps = bench.get("avg_tps", 0)
    env = bench.get("environment", "local")

    cpm = compute_cost_per_m(data)
    if cpm is None:
        return None

    # Parse date for "Mon YYYY" format
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        date_str = dt.strftime("%b %Y")
    except (ValueError, AttributeError):
        date_str = "Unknown"

    return {
        "gpu": gpu_str,
        "cpu": cpu_model,
        "ram": ram_str,
        "model": model,
        "tps": tps,
        "cost_per_m": cpm,
        "environment": env,
        "date": date_str,
        "issue": issue_num,
    }


def generate_leaderboard(entries: list[dict]) -> str:
    """Generate the full LEADERBOARD.md content."""
    # Sort by cost_per_m ascending
    entries.sort(key=lambda e: e["cost_per_m"])

    now_str = datetime.utcnow().strftime("%B %Y")

    rows = []
    for i, e in enumerate(entries, 1):
        tps_str = f"{e['tps']:.1f}" if isinstance(e['tps'], (int, float)) else str(e['tps'])
        cost_str = f"${e['cost_per_m']:.2f}"
        env_tag = " *(remote)*" if e.get("environment") == "remote" else ""
        rows.append(
            f"| {i} | {e['gpu']}{env_tag} | {e['cpu']} | {e['ram']} | {e['model']} "
            f"| {tps_str} | {cost_str} | {e['date']} |"
        )

    table_rows = "\n".join(rows) if rows else "| — | No submissions yet | | | | | | |"

    # If no entries, show a placeholder
    if not entries:
        table_rows = "| — | *No submissions yet — [be the first!](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues/new?template=benchmark-submission.yml)* | | | | | | |"

    return f"""# 🏆 Local Rig Benchmark Leaderboard

Real-world cost-per-token benchmarks from the local LLM community. All data self-reported via [GitHub Issues](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues?q=label%3Abenchmark).

> **Why this matters:** Local inference isn't free — every token costs electricity and hardware depreciation. This leaderboard shows the *real* effective cost per million tokens so you can compare local vs. cloud and make informed hardware decisions.

---

## Leaderboard

*Sorted by cost per million tokens (lowest first). Last rebuilt: {now_str}.*

| # | GPU | CPU | RAM | Model | TPS | $/M tokens | Submitted |
|---|-----|-----|-----|-------|-----|-----------|-----------|
{table_rows}

> **Your rig not here?** Run `/rig-benchmark <model>` then `/rig-submit <model>` in Hermes, or [open a benchmark issue](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues/new?template=benchmark-submission.yml) manually.

---

## What the Numbers Mean

| Metric | Definition |
|--------|-----------|
| **TPS** | Tokens per second (output generation speed), measured by the plugin's standardized benchmark |
| **$/M tokens** | Effective cost per million generated tokens: `(depreciation/hr + energy/hr) / TPS × 1,000,000 / 3600` |
| **Depreciation** | GPU-only cost amortized over expected lifespan, counting actual inference hours only |
| **Energy** | `avg_power_watts / 1000 × electricity_rate_per_kWh` |

### For Comparison

| Provider | Model | Input $/M | Output $/M |
|----------|-------|-----------|------------|
| OpenAI | GPT-4o-mini | $0.15 | $0.60 |
| OpenAI | GPT-4o | $2.50 | $10.00 |
| Anthropic | Claude 3.5 Haiku | $0.80 | $4.00 |
| Groq | Llama 3.1 70B | $0.59 | $0.79 |

*Local rigs can be cost-competitive — if you measure it.*

---

## How to Submit

### Option A: In-App (Recommended)

```bash
/rig-benchmark qwen3.5-9b
/rig-submit qwen3.5-9b
```

### Option B: Manual

[Open a Benchmark Issue](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues/new?template=benchmark-submission.yml) — fill in GPU, CPU, RAM, model, TPS, and your cost parameters. The leaderboard auto-updates nightly.

---

## Submission Rules

- **One entry per hardware+model combo** — resubmit only if setup changed significantly
- **Honest numbers** — use the plugin's built-in benchmark, not hand-timed estimates
- **Minimum 1,024 output tokens** per benchmark for statistical reliability
- **Local or remote hardware** — remote entries tagged *(remote)*
- **No PII** — only your GitHub username is published

---

*This leaderboard is auto-regenerated from GitHub Issues by [a CI workflow](.github/workflows/update-leaderboard.yml). Your submissions appear within 24 hours.*
"""


def main():
    print(f"Fetching benchmark issues from {REPO}...")
    issues = fetch_benchmark_issues()
    print(f"Found {len(issues)} benchmark issue(s)")

    entries = []
    for issue in issues:
        data = extract_benchmark_json(issue.get("body", ""))
        if data is None:
            print(f"  #{issue['number']}: Could not parse JSON — skipping")
            continue
        entry = build_entry(data, issue["number"], issue.get("createdAt", ""))
        if entry is None:
            print(f"  #{issue['number']}: Could not compute cost — skipping")
            continue
        print(f"  #{issue['number']}: {entry['gpu']} + {entry['model']} = ${entry['cost_per_m']:.2f}/M")
        entries.append(entry)

    content = generate_leaderboard(entries)
    LEADERBOARD_PATH.write_text(content)
    print(f"\nWrote {len(entries)} entries to {LEADERBOARD_PATH}")


if __name__ == "__main__":
    main()
