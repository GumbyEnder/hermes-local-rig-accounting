# 🏆 Local Rig Benchmark Leaderboard

## What is this?

The **Local Rig Benchmark Leaderboard** tracks the cost-effectiveness of running large language models on local hardware. It shows which hardware + model combinations deliver the lowest cost per million tokens, helping the community make informed decisions about local AI infrastructure investments.

All metrics are self-reported by community members via GitHub Issues. The leaderboard is updated automatically via CI/CD that processes new submissions.

---

## Leaderboard

| GPU | CPU | RAM | Model | Quant | TPS | $/M tokens | Backend | Submitted |
|-----|-----|-----|-------|-------|-----|-----------|---------|-----------|
| **NVIDIA RTX 4080** | AMD Ryzen 9 7950X | 64GB | qwen/qwen3.5-9b | Q4_K_M | 127.4 | $0.38 | llama.cpp | Apr 2026 |
| **NVIDIA RTX 4090** | Intel i9-14900K | 128GB | llama-3-70b | Q5_K_M | 89.2 | $0.52 | vLLM | Apr 2026 |
| **Apple M3 Max** | Apple M3 Max (12-core) | 64GB | mistral-7b | FP16 | 94.1 | $0.44 | Ollama | Mar 2026 |
| **NVIDIA L40S** | AMD EPYC 7742 | 256GB | mixtral-8x7b | Q4_K_M | 65.8 | $0.67 | llama.cpp | Mar 2026 |

> **Legend:** TPS = tokens per second (output). $/M tokens = effective cost per million generated tokens (depreciation + electricity). Lower is better for cost; higher is better for TPS.

---

## How to Submit

Submitting your benchmark to the leaderboard is simple and anonymous:

1. **Run the benchmark** on your local rig:
   ```bash
   /rig-benchmark --model qwen/qwen3.5-9b --max-tokens 4096
   ```

2. **Copy the JSON output** from the command (or use `/rig-submit --dry-run` if available).

3. **Open a GitHub Issue** in this repository using the [Benchmark Submission template](.github/ISSUE_TEMPLATE/benchmark-submission.yml):
   - Go to the [Issues tab](https://github.com/GumbyEnder/hermes-local-rig-accounting/issues)
   - Click "New Issue"
   - Select "Benchmark Submission"
   - Fill in the form fields (GPU, CPU, RAM, Model, etc.)
   - **Paste the full JSON output** into the "Benchmark JSON" textarea
   - Submit

4. **Wait for automation** — The CI pipeline will validate your submission, compute the cost model, and update this leaderboard automatically.

---

## Submission Rules & Notes

- **Anonymous submissions**: Only your GitHub username will be visible alongside your entry. No personal information is published.
- **One submission per hardware+model combo**: If you've already submitted for RTX 4080 + Qwen3.5-9B, only submit again if you've significantly changed the setup (new quant, different backend, etc.).
- **Honest reporting**: The leaderboard relies on community integrity. Fake or misleading submissions will be removed if discovered.
- **Minimum benchmark size**: For statistical reliability, benchmarks should run for at least 30 seconds and generate a minimum of 1024 tokens.
- **Real hardware only**: Cloud instances (rented GPUs) are welcome, but please specify "remote" in the environment field and include the actual instance type (e.g., "Lambda Labs A100 80GB").

---

## Cost Model Calculation

The effective cost per million tokens is calculated as:

```
cost_per_token = (depreciation_per_hour + energy_per_hour) / avg_tps
cost_per_million = cost_per_token * 1_000_000
```

Where:
- **depreciation_per_hour** = (hardware_cost + gpu_cost) / (lifespan_years × 365 × 24)
- **energy_per_hour** = avg_power_watts × electricity_rate_per_kwh × 0.001

This reflects the true marginal cost of running inference on your rig, accounting for both capital depreciation and electricity.

---

## Questions?

Open a [discussion](https://github.com/GumbyEnder/hermes-local-rig-accounting/discussions) or contact the maintainers if you have questions about the benchmark process, cost model, or leaderboard updates.

---

*Last updated: April 2026*
