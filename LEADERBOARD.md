# 🏆 Local Rig Benchmark Leaderboard

Real-world cost-per-token benchmarks from the local LLM community. All data self-reported via [GitHub Issues](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues?q=label%3Abenchmark).

> **Why this matters:** Local inference isn't free — every token costs electricity and hardware depreciation. This leaderboard shows the *real* effective cost per million tokens so you can compare local vs. cloud and make informed hardware decisions.

---

## Leaderboard

*Sorted by cost per million tokens (lowest first). Last rebuilt: May 2026.*

| # | GPU | CPU | RAM | Model | TPS | $/M tokens | Submitted |
|---|-----|-----|-----|-------|-----|-----------|-----------|
| 1 | NVIDIA GeForce RTX 4080 15GB | 13th Gen Intel(R) Core(TM) i9-13900KF | 31 GB | qwen3.5-9b | 76.0 | $0.41 | Apr 2026 |
| 2 | NVIDIA GeForce RTX 4080 15GB | 13th Gen Intel(R) Core(TM) i9-13900KF | 31 GB | qwen3.5-9b | 57.8 | $0.53 | Apr 2026 |

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
