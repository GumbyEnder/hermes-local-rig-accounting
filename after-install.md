# Local Rig Accounting — Setup Guide

> **⚠️ Hermes Restart Reminder**
>
> After any plugin code/config change, you **must fully restart Hermes** to load the updated code:
>
> ```bash
> pkill -f hermes && sleep 1 && hermes --tui -p frodo
> ```
>
> `/quit` only closes the TUI window — the gateway daemon keeps running in the background and **will not reload plugin code**. Use `pkill -f hermes` to kill all Hermes processes first.

## Quick Start

1. **Configure your rig** in `~/.hermes/profiles/frodo/config.yaml`:

```yaml
local_rig:
  hardware_cost_usd: 3500        # Total system cost (or GPU-only if you prefer)
  gpu_only_cost_usd: 1500       # GPU cost only (RTX 4080 example)
  lifespan_years: 3
  avg_power_watts: 450          # Average power draw during inference
  electricity_rate_per_kwh: 0.12  # Or use "auto" + electricity_region: "Texas"
  auto_submit: true             # Auto-submit benchmarks after /rig-benchmark
  submit_target: cloudflare     # "cloudflare" (recommended) or "github"
  # worker_url: https://benchmark-worker.agentic-accounting.workers.dev  # optional custom
```

2. **Restart Hermes** to load the plugin:
   ```bash
   hermes --tui -p frodo
   ```

3. **Benchmark your local model:**
   ```
   /rig-benchmark qwen3.5-9b
   ```

4. **View costs:**
   ```
   /rig-cost
   /rig-summary
   ```

5. **Submit to community leaderboard** (if `auto_submit: false`):
   ```
   /rig-submit
   ```

---

## Configuration Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `hardware_cost_usd` | float | 0.0 | Total hardware cost for depreciation |
| `gpu_only_cost_usd` | float | null | GPU cost only (more accurate if specified) |
| `lifespan_years` | float | 3.0 | Depreciation lifespan |
| `avg_power_watts` | float | 0.0 | Average inference power draw |
| `electricity_rate_per_kwh` | float/"auto" | 0.0 | $/kWh; use "auto" + `electricity_region` for lookup |
| `electricity_region` | string | — | US state, country, or abbreviation (required if rate is "auto") |
| `auto_submit` | boolean | true | Auto-submit after `/rig-benchmark` |
| `submit_target` | string | "cloudflare" | Where to submit: `"cloudflare"` (anonymous Worker) or `"github"` (GitHub Issues) |
| `worker_url` | string | Cloudflare default | Override the Worker endpoint URL |
| `leaderboard_url` | string | null | [legacy] URL of leaderboard website |
| `hostname` | string | null | Auto-select rig by machine hostname |
| `rigs` | list | [] | Multiple rig profiles for multi-machine setups |

---

## Community Leaderboard

Benchmarks submitted via Cloudflare Worker are stored in a shared D1 database:

**Worker endpoint:** `https://benchmark-worker.agentic-accounting.workers.dev`

- **Public submissions:** `POST /api/benchmarks` (no auth required)
- **Admin API:** `GET /api/admin/benchmarks` (requires `X-API-Key` header)
- Rate limit: 100 submissions/hour per IP
- Deduplication: `(repo_url, commit_sha)` UNIQUE — re-submit of same commit returns existing ID

View the live leaderboard (coming soon): TBD

---

## Troubleshooting

### Plugin not loading?
- Restart Hermes TUI: `/quit` then `hermes --tui -p frodo`
- Check plugin path: `~/.hermes/profiles/frodo/plugins/local-rig-accounting/`
- Verify config: `hermes config get local_rig` (should show your values)

### Benchmark fails?
- Ensure local model provider is running (LM Studio, Ollama, etc.)
- Use `--base_url` if non-standard endpoint
- Check Hermes logs for errors

### Submission fails?
- **Cloudflare Worker:** Check internet connectivity; Worker may be temporarily unavailable
- **GitHub fallback:** Run `gh auth status` — login if not authenticated
- Toggle `submit_target` between `cloudflare` and `github` in config

---

## Optional: Hermes Dashboard Integration

A dashboard plugin shows your rig's status and the community leaderboard inside Hermes's web UI.

**Quick install:**
```bash
mkdir -p ~/.hermes/plugins/rig-leaderboard/dashboard
cp -r ~/hermes-plugins/local-rig-accounting/rig-leaderboard/dashboard/* \
       ~/.hermes/plugins/rig-leaderboard/dashboard/
pkill -f hermes && hermes --tui -p frodo   # restart
# Open Dashboard tab in browser → press R to rescan plugins
```

See plugin README for full features and upcoming quick-benchmark button.

---

## Cost Model Explained

**Hourly cost = depreciation + energy**

Depreciation per hour = `gpu_only_cost_usd / (lifespan_years × 365.25 × 24)`  
Energy per hour = `(avg_power_watts / 1000) × electricity_rate_per_kwh`

**Cost per million tokens = (hourly_cost / (TPS × 3600)) × 1,000,000**

Example: RTX 4080, $1500 GPU, 3 years, 450W, $0.12/kWh, 75 TPS  
Depreciation: $1500 / (3 × 8766) = $0.057/hr  
Energy: 0.45 × $0.12 = $0.054/hr  
**Total: $0.111/hr → ~$0.52/M tokens at 75 TPS**

---

## Files

- Plugin: `~/.hermes/profiles/frodo/plugins/local-rig-accounting/`
- Kanban: `/mnt/nas/Obsidian Vault/Kanban/Local Rig Accounting.md`
- GitHub: https://github.com/GumbyEnder/hermes-local-rig-accounting
- Worker source: `worker/` subdirectory (Cloudflare Worker)
