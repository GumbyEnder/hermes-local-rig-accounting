# Local Rig Accounting — Setup

This plugin tracks the real cost of local LLM inference (depreciation + energy + throughput).

## Quick Start

Add a `local_rig:` section to your config.yaml:

```yaml
local_rig:
  hardware_cost_usd: 5000        # Total rig cost
  lifespan_years: 3              # Expected useful life
  gpu_only_cost_usd: 2500        # Optional: use GPU cost as depreciation base
  avg_power_watts: 450           # Average power draw during inference
  electricity_rate_per_kwh: 0.15 # Your local electricity rate
```

Then enable the plugin:

```yaml
plugins:
  enabled:
    - local-rig-accounting
```

## Next Steps

1. **Restart Hermes** to load the plugin
2. **Run `/rig-benchmark <model_name>`** to measure your local model's TPS
3. **Run `/rig-summary`** to see your rig economics

## Commands

- `/rig-cost` — Show current session's local inference cost
- `/rig-summary` — Full rig economics dashboard
- `/rig-benchmark <model> [base_url]` — Measure TPS for a local model

## How It Works

The cost model calculates:

- **Depreciation**: `gpu_only_cost / (lifespan_years × 8766 hours)` per actual inference hour
- **Energy**: `(avg_power_watts / 1000) × electricity_rate_per_kwh` per hour
- **Per-token**: `total_hourly_cost / (TPS × 3600) × 1,000,000`

Results display in the same format as cloud provider pricing ($/M tokens) for easy comparison.
