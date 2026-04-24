"""
Benchmark Module for Local Rig Accounting

Runs a short standardized inference test to measure tokens-per-second (TPS)
for a given model, then caches the result.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .cost_calculator import _load_benchmarks, _save_benchmarks

logger = logging.getLogger("local_rig_accounting")

# Standardized benchmark prompt — fixed length, deterministic
_BENCHMARK_PROMPT = (
    "Write a detailed comparison of three sorting algorithms: "
    "quicksort, mergesort, and heapsort. For each, explain the time complexity, "
    "space complexity, stability, and best use cases. Include examples of when "
    "each algorithm would be the optimal choice."
)

_BENCHMARK_MAX_TOKENS = 512


def run_benchmark(
    hermes_home: Path,
    model: str,
    base_url: str = "http://127.0.0.1:1234/v1",
    api_key: str = "not-needed",
    prompt: Optional[str] = None,
    max_tokens: int = _BENCHMARK_MAX_TOKENS,
    warmup: bool = True,
) -> Dict[str, Any]:
    """Run a short inference benchmark and cache the TPS result.

    Returns dict with benchmark results and saves to model_benchmarks.yaml.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return {"error": "openai package required for benchmarking. Run: pip install openai"}

    client = OpenAI(base_url=base_url, api_key=api_key)
    test_prompt = prompt or _BENCHMARK_PROMPT

    # Warmup run (first inference is often slower due to model loading/caching)
    if warmup:
        try:
            logger.info("Warmup inference for %s...", model)
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hello, respond briefly."}],
                max_tokens=32,
                temperature=0.1,
            )
        except Exception as e:
            logger.warning("Warmup failed (non-fatal): %s", e)

    # Timed run
    try:
        logger.info("Benchmarking %s with %d max tokens...", model, max_tokens)
        start = time.monotonic()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": test_prompt}],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        elapsed = time.monotonic() - start
    except Exception as e:
        return {"error": f"Benchmark inference failed: {e}"}

    # Extract token counts
    usage = getattr(response, "usage", None)
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    total_tokens = input_tokens + output_tokens

    if elapsed <= 0:
        return {"error": "Benchmark completed in zero time — suspicious result"}

    tps = output_tokens / elapsed if output_tokens > 0 else 0.0
    tps_total = total_tokens / elapsed

    result = {
        "avg_tps": round(tps, 2),
        "total_tps": round(tps_total, 2),
        "output_tokens": output_tokens,
        "input_tokens": input_tokens,
        "elapsed_seconds": round(elapsed, 2),
        "max_tokens": max_tokens,
        "base_url": base_url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Cache result
    benchmarks = _load_benchmarks(hermes_home)
    # Normalize key: strip provider prefix if present
    key = model.split("/", 1)[1] if "/" in model else model
    benchmarks[key] = result
    _save_benchmarks(hermes_home, benchmarks)

    logger.info("Benchmark complete: %s = %.2f output TPS, %.2f total TPS", model, tps, tps_total)

    return {
        "model": model,
        "cached_as": key,
        **result,
    }
