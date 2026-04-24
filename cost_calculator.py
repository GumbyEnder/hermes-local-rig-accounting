"""
Cost Calculator for Local Rig Accounting

Converts rig operating cost into per-token pricing using measured throughput.
All outputs are in the same format as cloud provider pricing ($ per million tokens).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from .rig_config import RigConfig, RigProfile, load_rig_config

logger = logging.getLogger("local_rig_accounting")

_ONE_MILLION = Decimal("1000000")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class LocalCostResult:
    """Mirrors the core CostResult shape for display compatibility."""
    input_cost_per_million: Decimal
    output_cost_per_million: Decimal   # Same as input for local (no distillation cost difference)
    hourly_cost_usd: float
    tps: float                          # Tokens per second used for this calculation
    cumulative_hours: float
    label: str
    source: str = "local_rig_estimate"
    notes: tuple[str, ...] = ()


def _load_benchmarks(hermes_home: Path) -> Dict[str, Dict[str, Any]]:
    """Load cached benchmark data from model_benchmarks.yaml."""
    bench_path = hermes_home / "model_benchmarks.yaml"
    if not bench_path.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(bench_path.read_text()) or {}
        return data.get("benchmarks", {})
    except Exception as e:
        logger.warning("Failed to load benchmarks: %s", e)
        return {}


def _save_benchmarks(hermes_home: Path, benchmarks: Dict[str, Dict[str, Any]]) -> None:
    """Persist benchmark cache."""
    bench_path = hermes_home / "model_benchmarks.yaml"
    try:
        import yaml
        bench_path.write_text(yaml.dump({"benchmarks": benchmarks}, default_flow_style=False))
    except Exception as e:
        logger.warning("Failed to save benchmarks: %s", e)


def get_benchmark_tps(hermes_home: Path, model: str) -> Optional[float]:
    """Look up cached TPS for a specific model. Returns None if no benchmark."""
    benchmarks = _load_benchmarks(hermes_home)
    # Try exact match, then without provider prefix
    entry = benchmarks.get(model)
    if entry is None and "/" in model:
        bare = model.split("/", 1)[1]
        entry = benchmarks.get(bare)
    if entry is not None:
        return float(entry.get("avg_tps", 0.0)) or None
    return None


def estimate_local_cost(
    hermes_home: Path,
    model: str,
    tps_override: Optional[float] = None,
) -> Optional[LocalCostResult]:
    """Calculate effective per-token cost for local inference.

    Returns None if rig is not configured (all-zero profile) or
    if no benchmark TPS is available and no override given.
    """
    rig_config = load_rig_config(hermes_home)
    profile = rig_config.active

    if not profile.is_configured():
        return None

    # Resolve TPS: override > cached benchmark
    tps = tps_override or get_benchmark_tps(hermes_home, model)
    if not tps or tps <= 0:
        return LocalCostResult(
            input_cost_per_million=_ZERO,
            output_cost_per_million=_ZERO,
            hourly_cost_usd=profile.hourly_cost(rig_config.cumulative_inference_hours),
            tps=0.0,
            cumulative_hours=rig_config.cumulative_inference_hours,
            label="Local (no benchmark)",
            notes=("Run /rig-benchmark to measure throughput for this model.",),
        )

    # Tokens per hour at measured TPS
    tokens_per_hour = tps * 3600.0
    hourly = profile.hourly_cost(rig_config.cumulative_inference_hours)

    # Cost per million tokens
    if tokens_per_hour <= 0:
        cost_per_million = _ZERO
    else:
        cost_per_million = Decimal(str(round(hourly / tokens_per_hour * 1_000_000, 6)))

    return LocalCostResult(
        input_cost_per_million=cost_per_million,
        output_cost_per_million=cost_per_million,   # Local = same cost for input/output
        hourly_cost_usd=round(hourly, 4),
        tps=round(tps, 2),
        cumulative_hours=round(rig_config.cumulative_inference_hours, 2),
        label=f"Local ~${cost_per_million:.4f}/M",
        notes=(),
    )


def estimate_session_cost(
    hermes_home: Path,
    model: str,
    input_tokens: int,
    output_tokens: int,
    tps_override: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Estimate the cost of a specific session's local inference.

    Returns dict with cost breakdown, or None if rig not configured.
    """
    result = estimate_local_cost(hermes_home, model, tps_override=tps_override)
    if result is None:
        return None

    if result.input_cost_per_million == _ZERO and result.output_cost_per_million == _ZERO:
        if "no benchmark" in result.label.lower():
            return {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cost_usd": 0.0,
                "cost_label": result.label,
                "hourly_cost_usd": result.hourly_cost_usd,
                "tps": result.tps,
                "notes": list(result.notes),
            }

    input_cost = Decimal(str(input_tokens)) * result.input_cost_per_million / _ONE_MILLION
    output_cost = Decimal(str(output_tokens)) * result.output_cost_per_million / _ONE_MILLION
    total_cost = input_cost + output_cost

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_cost_usd": float(input_cost),
        "output_cost_usd": float(output_cost),
        "cost_usd": float(total_cost),
        "cost_label": f"~${float(total_cost):.4f} (Local Est.)",
        "cost_per_million_input": float(result.input_cost_per_million),
        "cost_per_million_output": float(result.output_cost_per_million),
        "hourly_cost_usd": result.hourly_cost_usd,
        "tps": result.tps,
        "cumulative_hours": result.cumulative_hours,
        "notes": list(result.notes),
    }


def rig_summary(hermes_home: Path) -> Dict[str, Any]:
    """Full rig economics summary for display."""
    rig_config = load_rig_config(hermes_home)
    profile = rig_config.active
    benchmarks = _load_benchmarks(hermes_home)

    per_model_costs = {}
    for model_key, bench in benchmarks.items():
        tps = float(bench.get("avg_tps", 0.0))
        if tps > 0:
            result = estimate_local_cost(hermes_home, model_key, tps_override=tps)
            if result:
                per_model_costs[model_key] = {
                    "cost_per_million": float(result.input_cost_per_million),
                    "tps": tps,
                    "hourly_cost": result.hourly_cost_usd,
                }

    return {
        "rig_label": profile.label,
        "configured": profile.is_configured(),
        "hardware_cost_usd": profile.hardware_cost_usd,
        "gpu_only_cost_usd": profile.gpu_only_cost_usd,
        "depreciable_cost_usd": profile.depreciable_cost,
        "lifespan_years": profile.lifespan_years,
        "avg_power_watts": profile.avg_power_watts,
        "electricity_rate_per_kwh": profile.electricity_rate_per_kwh,
        "depreciation_per_hour": round(profile.depreciation_per_hour(rig_config.cumulative_inference_hours), 4),
        "energy_cost_per_hour": round(profile.energy_cost_per_hour, 4),
        "total_hourly_cost": round(profile.hourly_cost(rig_config.cumulative_inference_hours), 4),
        "cumulative_inference_hours": round(rig_config.cumulative_inference_hours, 2),
        "benchmarked_models": len(benchmarks),
        "per_model_costs": per_model_costs,
    }
