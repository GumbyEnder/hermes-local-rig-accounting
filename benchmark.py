"""
Benchmark Module for Local Rig Accounting

Runs a short standardized inference test to measure tokens-per-second (TPS)
for a given model, then caches the result.
"""
from __future__ import annotations

import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _resolve_model_name(model: str, client) -> str:
    """Resolve a partial model name against the server's model list.

    If the exact model name exists on the server, return it as-is.
    Otherwise, try fuzzy matching: if the user passes 'qwen3.5-9b' and
    the server has 'qwen/qwen3.5-9b', use that.
    Returns the resolved name, or the original if no match found.
    """
    try:
        models_response = client.models.list()
        available = [m.id for m in models_response.data]

        # Exact match
        if model in available:
            return model

        # Partial match: user's name is a suffix of a server model
        # e.g. "qwen3.5-9b" matches "qwen/qwen3.5-9b"
        suffix_matches = [m for m in available if m.endswith("/" + model)]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        if len(suffix_matches) > 1:
            # Multiple suffix matches — return the shortest (most specific)
            return sorted(suffix_matches, key=len)[0]

        # Substring match: user's name appears anywhere in server model
        substring_matches = [m for m in available if model in m]
        if len(substring_matches) == 1:
            return substring_matches[0]
        if len(substring_matches) > 1:
            return sorted(substring_matches, key=len)[0]

    except Exception:
        pass  # If we can't list models, just try the name as-is

    return model


def _is_local_base_url(base_url: str) -> bool:
    """Determine if a base_url points to a local or private network address.

    Returns True for localhost (127.0.0.1, ::1, 0.0.0.0) or private IP ranges
    (10.x, 172.16-31.x, 192.168.x). Returns False otherwise.
    """
    import re
    from urllib.parse import urlparse

    try:
        parsed = urlparse(base_url)
        host = parsed.hostname or ""
    except Exception:
        host = base_url.split("://")[-1].split("/")[0].split(":")[0]

    # Localhost variants
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"):
        return True

    # IPv4 private ranges
    if re.match(r"^10\.", host):
        return True
    if re.match(r"^172\.(1[6-9]|2[0-9]|3[01])\.", host):
        return True
    if re.match(r"^192\.168\.", host):
        return True

    # IPv6 link-local (optional, covers local IPv6 like fd00::/8)
    if re.match(r"^fe80::", host):
        return True

    return False


def _collect_hardware_info() -> Dict[str, Any]:
    """Collect hardware and OS information from the local system.

    Returns a dict with cpu (model, cores, threads, architecture),
    gpu (list of {model, vram_mb, driver}), ram_gb, and os fields.
    All failures are caught and result in empty/missing fields.
    """
    result: Dict[str, Any] = {}

    # CPU info via lscpu
    try:
        cpu_data = subprocess.run(
            ["lscpu"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if cpu_data.returncode == 0:
            cpu_info: Dict[str, Any] = {}
            for line in cpu_data.stdout.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip().lower()
                    val = val.strip()
                    if "model name" in key:
                        cpu_info["model"] = val
                    elif "socket(s)" in key:
                        cpu_info["sockets"] = int(val) if val.isdigit() else None
                    elif "core(s) per socket" in key:
                        cpu_info["cores_per_socket"] = (
                            int(val) if val.isdigit() else None
                        )
                    elif "thread(s) per core" in key:
                        cpu_info["threads_per_core"] = (
                            int(val) if val.isdigit() else None
                        )
                    elif "architecture" in key:
                        cpu_info["architecture"] = val

            # Derive total cores and threads
            sockets = cpu_info.get("sockets", 1) or 1
            cps = cpu_info.get("cores_per_socket", 1) or 1
            tpc = cpu_info.get("threads_per_core", 1) or 1
            cpu_info["cores"] = sockets * cps
            cpu_info["threads"] = sockets * cps * tpc

            # Keep only the fields we want
            result["cpu"] = {
                "model": cpu_info.get("model", "Unknown"),
                "cores": cpu_info.get("cores", 0),
                "threads": cpu_info.get("threads", 0),
                "architecture": cpu_info.get("architecture", "Unknown"),
            }
    except Exception:
        result["cpu"] = {"model": "Unknown", "cores": 0, "threads": 0, "architecture": "Unknown"}

    # GPU info — try nvidia-smi first
    gpu_list: List[Dict[str, Any]] = []
    try:
        nvidia = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if nvidia.returncode == 0 and nvidia.stdout.strip():
            for line in nvidia.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    model = parts[0]
                    vram_mb = int(parts[1]) if parts[1].isdigit() else 0
                    driver = parts[2] if len(parts) > 2 else "Unknown"
                    gpu_list.append({"model": model, "vram_mb": vram_mb, "driver": driver})
    except Exception:
        pass

    # If no NVIDIA GPUs found, try ROCm (AMD)
    if not gpu_list:
        try:
            rocm = subprocess.run(
                ["rocm-smi", "--showproductname"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if rocm.returncode == 0:
                for line in rocm.stdout.splitlines():
                    if line.strip() and not line.startswith("="):
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            gpu_list.append(
                                {"model": parts[1].strip(), "vram_mb": 0, "driver": "ROCm"}
                            )
        except Exception:
            pass

    result["gpu"] = gpu_list

    # RAM — read /proc/meminfo
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        # MemTotal is in kB
                        ram_kb = int(parts[1])
                        result["ram_gb"] = round(ram_kb / 1024 / 1024, 1)
                        break
            else:
                result["ram_gb"] = 0.0
    except Exception:
        result["ram_gb"] = 0.0

    # OS info
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"').strip("'")
                    result["os"] = os_name
                    break
            else:
                raise FileNotFoundError
    except Exception:
        # Fallback to platform module
        sys_name = platform.system()
        release = platform.release()
        result["os"] = f"{sys_name} {release}".strip()

    return result


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

    # Resolve partial model names against server's model list
    resolved_model = _resolve_model_name(model, client)
    if resolved_model != model:
        logger.info("Resolved model name: %s → %s", model, resolved_model)
    model = resolved_model
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

    # Determine environment and collect hardware info (never fails)
    is_local = _is_local_base_url(base_url)
    environment = "local" if is_local else "remote"
    hardware_info = _collect_hardware_info()

    result = {
        "avg_tps": round(tps, 2),
        "total_tps": round(tps_total, 2),
        "output_tokens": output_tokens,
        "input_tokens": input_tokens,
        "elapsed_seconds": round(elapsed, 2),
        "max_tokens": max_tokens,
        "base_url": base_url,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": environment,
        "hardware": hardware_info,
    }

    if environment == "remote":
        result["notes"] = [
            "Remote provider benchmark — cost estimates use local rig rates for comparison only"
        ]

    # Cache result (with all metadata)
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
