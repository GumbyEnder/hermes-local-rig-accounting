# 🏆 Local Rig Benchmark Leaderboard

Real-world cost-per-token benchmarks from the local LLM community. All data self-reported via [GitHub Issues](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues?q=label%3Abenchmark).

> **Why this matters:** Local inference isn't free — every token costs electricity and hardware depreciation. This leaderboard shows the *real* effective cost per million tokens so you can compare local vs. cloud and make informed hardware decisions.

---

## Leaderboard

*Sorted by cost per million tokens (lowest first). Last rebuilt: April 2026.*

| # | GPU | CPU | RAM | Model | TPS | $/M tokens | Submitted |
|---|-----|-----|-----|-------|-----|-----------|-----------|
| 1 | NVIDIA RTX 4080 16GB | Intel i9-13900KF (24c/48t) | 31 GB | qwen3.5-9b | 76.0 | $0.41 | Apr 2026 |

> **Your rig not here?** Run `/rig-benchmark <model>` then `/rig-submit <model>` in Hermes, or [open a benchmark issue](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues/new?template=benchmark-submission.yml) manually.

---

## What the Numbers Mean

| Metric | Definition |
|--------|-----------|
| **TPS** | Tokens per second (output generation speed), measured by the plugin's standardized benchmark |
| **$/M tokens** | Effective cost per million generated tokens, calculated as: `(depreciation/hr + energy/hr) / TPS × 1,000,000 / 3600` |
| **Depreciation** | Based on GPU-only cost over expected lifespan, only counting actual inference hours |
| **Energy** | `avg_power_watts / 1000 × electricity_rate_per_kWh` |

### Example Breakdown (RTX 4080 entry)

| Component | Value |
|-----------|-------|
| GPU cost | $1,500 |
| Lifespan | 3 years (26,298 inference hours) |
| Power draw | 450W |
| Electricity | $0.12/kWh |
| Depreciation | $0.057/hr |
| Energy | $0.054/hr |
| **Total hourly** | **$0.111/hr** |
| At 76 TPS | **$0.41/M tokens** |

For comparison: GPT-4o-mini runs ~$0.15/M input, $0.60/M output on OpenAI. A well-tuned local rig can be cost-competitive — *if you measure it.*

---

## How to Submit

### Option A: In-App (Recommended)

```bash
# Benchmark your model
/rig-benchmark qwen3.5-9b

# Submit to the leaderboard
/rig-submit qwen3.5-9b
```

### Option B: Manual

1. Go to [Issues → New Issue → Benchmark Submission](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues/new?template=benchmark-submission.yml)
2. Fill in GPU, CPU, RAM, model, TPS, and your cost model parameters
3. Submit — the leaderboard auto-updates nightly

---

## Submission Rules

- **One entry per hardware+model combo** — resubmit only if setup changed significantly
- **Honest numbers** — use the plugin's built-in benchmark, not hand-timed estimates
- **Minimum 1,024 output tokens** per benchmark for statistical reliability
- **Local or remote hardware** — remote (cloud GPU) entries welcome, just tag `environment: remote`
- **GitHub account required** — your username is the only identity published, no PII collected

---

*This leaderboard is auto-regenerated from GitHub Issues by [a CI workflow](.github/workflows/update-leaderboard.yml). Your submissions appear within 24 hours.*
