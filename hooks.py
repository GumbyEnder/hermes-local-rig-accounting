"""
Lifecycle Hooks for Local Rig Accounting

Hooks into Hermes' post_api_request and on_session_finalize to track
token throughput and cumulative inference hours.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .rig_config import load_cumulative_hours, save_cumulative_hours

logger = logging.getLogger("local_rig_accounting")

# Module-level session accumulator (reset on each session start)
_session_tokens_in: int = 0
_session_tokens_out: int = 0
_session_start_time: float = 0.0
_session_api_calls: int = 0
_skip_submit_prompt: bool = False
_hermes_home: Optional[Path] = None


def _is_local_provider(provider: str = "", base_url: str = "") -> bool:
    """Determine if the request was served by a local inference engine."""
    provider_lower = (provider or "").strip().lower()
    base_lower = (base_url or "").strip().lower()
    return (
        provider_lower in ("local", "lmstudio-local", "lmstudio", "ollama", "llamacpp", "vllm", "tabbyapi")
        or "localhost" in base_lower
        or "127.0.0.1" in base_lower
        or "0.0.0.0" in base_lower
    )


def init_session(hermes_home: Path) -> None:
    """Reset session accumulators. Called from on_session_start hook."""
    global _session_tokens_in, _session_tokens_out, _session_start_time, _session_api_calls, _hermes_home, _skip_submit_prompt
    _session_tokens_in = 0
    _session_tokens_out = 0
    _session_start_time = time.monotonic()
    _session_api_calls = 0
    _skip_submit_prompt = False
    _hermes_home = hermes_home


def on_post_api_request(
    hermes_home: Path,
    *,
    task_id: str = "",
    session_id: str = "",
    platform: str = "",
    model: str = "",
    provider: str = "",
    base_url: str = "",
    api_mode: str = "",
    api_call_count: int = 0,
    api_duration: float = 0.0,
    finish_reason: str = "",
    message_count: int = 0,
    response_model: str = "",
    usage: dict = None,
    assistant_content_chars: int = 0,
    assistant_tool_call_count: int = 0,
    **kwargs,
) -> None:
    """Track token counts from local inference API responses.

    Only counts tokens from local providers (localhost, lmstudio, ollama, etc).
    """
    global _session_tokens_in, _session_tokens_out, _session_api_calls

    if not _is_local_provider(provider, base_url):
        return

    if usage is None:
        return

    # Normalize usage (OpenAI-compatible format)
    in_tok = 0
    out_tok = 0
    if isinstance(usage, dict):
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
    else:
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)

    _session_tokens_in += in_tok
    _session_tokens_out += out_tok
    _session_api_calls += 1

    logger.debug(
        "Local tokens: +%d in, +%d out (session total: %d/%d, calls: %d)",
        in_tok, out_tok, _session_tokens_in, _session_tokens_out, _session_api_calls,
    )


def on_session_finalize(
    hermes_home: Path,
    *,
    session_id: str = "",
    platform: str = "",
    **kwargs,
) -> None:
    """Persist cumulative inference hours when session truly ends.

    Estimates inference time from API call durations, or falls back
    to wall-clock time scaled by the ratio of local-to-total API calls.
    """
    global _session_tokens_in, _session_tokens_out, _session_api_calls, _session_start_time

    if _session_api_calls == 0:
        return  # No local inference happened this session

    # Estimate inference hours: use wall-clock session time * rough duty cycle
    # A more accurate approach would track per-call duration, but post_api_request
    # gives us api_duration already — we'll use accumulated duration if available.
    # For now, estimate from token throughput using cached benchmarks.
    session_wall_seconds = time.monotonic() - _session_start_time if _session_start_time else 0

    # Conservative estimate: assume ~40% duty cycle for local inference
    # (model loading, batching overhead, idle between calls)
    # This will be refined when per-call duration tracking is added
    estimated_inference_hours = (session_wall_seconds * 0.4) / 3600.0

    # Load, add, save
    cumulative = load_cumulative_hours(hermes_home)
    new_total = cumulative + estimated_inference_hours
    save_cumulative_hours(hermes_home, new_total)

    logger.info(
        "Session finalize: ~%.2f inference hours (cumulative: %.2f). "
        "Local tokens: %d in / %d out across %d API calls.",
        estimated_inference_hours, new_total,
        _session_tokens_in, _session_tokens_out, _session_api_calls,
    )

    # Reset session state
    _session_tokens_in = 0
    _session_tokens_out = 0
    _session_api_calls = 0
    _session_start_time = 0.0


def get_session_stats() -> Dict[str, Any]:
    """Return current session's local inference stats."""
    return {
        "local_input_tokens": _session_tokens_in,
        "local_output_tokens": _session_tokens_out,
        "local_api_calls": _session_api_calls,
    }
