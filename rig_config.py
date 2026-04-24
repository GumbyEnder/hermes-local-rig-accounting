"""
Local Rig Configuration Loader

Reads rig profile from config.yaml under the `local_rig:` key.
Falls back to sensible defaults if no config is provided.
Supports multiple named rig profiles.
"""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("local_rig_accounting")

# ---------------------------------------------------------------------------
# Default rig profile (no config = zero-cost, opt-in model)
# ---------------------------------------------------------------------------
_DEFAULT_RIG = {
    "hardware_cost_usd": 0.0,
    "lifespan_years": 3.0,
    "gpu_only_cost_usd": None,
    "avg_power_watts": 0.0,
    "electricity_rate_per_kwh": 0.0,
    "hostname": None,           # None = match any host
    "label": "default",
}


@dataclass
class RigProfile:
    """A single local hardware rig's cost parameters."""
    label: str = "default"
    hardware_cost_usd: float = 0.0
    lifespan_years: float = 3.0
    gpu_only_cost_usd: Optional[float] = None
    avg_power_watts: float = 0.0
    electricity_rate_per_kwh: float = 0.0
    hostname: Optional[str] = None

    @property
    def depreciable_cost(self) -> float:
        """Cost base for depreciation — GPU-only if specified, else full hardware."""
        return self.gpu_only_cost_usd if self.gpu_only_cost_usd is not None else self.hardware_cost_usd

    @property
    def lifespan_hours(self) -> float:
        return self.lifespan_years * 365.25 * 24.0

    @property
    def energy_cost_per_hour(self) -> float:
        """$ per hour of inference at average power draw."""
        return (self.avg_power_watts / 1000.0) * self.electricity_rate_per_kwh

    def depreciation_per_hour(self, cumulative_hours: float) -> float:
        """Straight-line depreciation per actual inference hour."""
        if self.lifespan_hours <= 0:
            return 0.0
        return self.depreciable_cost / self.lifespan_hours

    def hourly_cost(self, cumulative_hours: float) -> float:
        """Total effective hourly operating cost."""
        return self.depreciation_per_hour(cumulative_hours) + self.energy_cost_per_hour

    def is_configured(self) -> bool:
        """True when the user has provided actual cost data (not all zeros)."""
        return self.hardware_cost_usd > 0 or self.gpu_only_cost_usd is not None

    def matches_host(self) -> bool:
        """True if this profile applies to the current machine."""
        if self.hostname is None:
            return True
        return socket.gethostname().lower() == self.hostname.lower()


@dataclass
class RigConfig:
    """Top-level config: active rig + optional alternates."""
    active: RigProfile = field(default_factory=RigProfile)
    rigs: List[RigProfile] = field(default_factory=list)
    cumulative_inference_hours: float = 0.0

    @property
    def all_rigs(self) -> List[RigProfile]:
        return [self.active] + [r for r in self.rigs if r is not self.active]


# ---------------------------------------------------------------------------
# Persistence for cumulative hours
# ---------------------------------------------------------------------------
_HOURS_FILE_NAME = "rig_inference_hours.yaml"


def _hours_path(hermes_home: Path) -> Path:
    return hermes_home / _HOURS_FILE_NAME


def load_cumulative_hours(hermes_home: Path) -> float:
    """Load cumulative inference hours from disk."""
    p = _hours_path(hermes_home)
    if not p.exists():
        return 0.0
    try:
        import yaml
        data = yaml.safe_load(p.read_text()) or {}
        return float(data.get("cumulative_hours", 0.0))
    except Exception as e:
        logger.warning("Failed to load cumulative hours: %s", e)
        return 0.0


def save_cumulative_hours(hermes_home: Path, hours: float) -> None:
    """Persist cumulative inference hours to disk."""
    p = _hours_path(hermes_home)
    try:
        import yaml
        p.write_text(yaml.dump({"cumulative_hours": round(hours, 4)}))
    except Exception as e:
        logger.warning("Failed to save cumulative hours: %s", e)


# ---------------------------------------------------------------------------
# Config loading from config.yaml
# ---------------------------------------------------------------------------
def _dict_to_profile(d: Dict[str, Any], label: str = "default") -> RigProfile:
    return RigProfile(
        label=label,
        hardware_cost_usd=float(d.get("hardware_cost_usd", 0.0)),
        lifespan_years=float(d.get("lifespan_years", 3.0)),
        gpu_only_cost_usd=(
            float(d["gpu_only_cost_usd"]) if "gpu_only_cost_usd" in d and d["gpu_only_cost_usd"] is not None
            else None
        ),
        avg_power_watts=float(d.get("avg_power_watts", 0.0)),
        electricity_rate_per_kwh=float(d.get("electricity_rate_per_kwh", 0.0)),
        hostname=d.get("hostname"),
    )


def load_rig_config(hermes_home: Path) -> RigConfig:
    """Load rig config from config.yaml's `local_rig:` section.

    Config schema:
      local_rig:
        hardware_cost_usd: 5000
        lifespan_years: 3
        gpu_only_cost_usd: 2500     # optional
        avg_power_watts: 450
        electricity_rate_per_kwh: 0.15
        hostname: my-server          # optional, auto-match by hostname
        rigs:                        # optional, for multi-rig setups
          - label: rtx4080
            hardware_cost_usd: 3000
            avg_power_watts: 350
            electricity_rate_per_kwh: 0.12
    """
    from hermes_cli.config import load_config
    config = load_config()
    rig_section = config.get("local_rig", {})

    if not rig_section:
        cumulative = load_cumulative_hours(hermes_home)
        return RigConfig(cumulative_inference_hours=cumulative)

    # Primary profile from top-level keys
    primary = _dict_to_profile(rig_section, label=rig_section.get("label", "default"))

    # Additional rigs
    alt_rigs: List[RigProfile] = []
    for rd in rig_section.get("rigs", []):
        alt_rigs.append(_dict_to_profile(rd, label=rd.get("label", f"rig-{len(alt_rigs)+1}")))

    # Auto-select active rig by hostname if multiple provided
    all_profiles = [primary] + alt_rigs
    active = primary
    for rp in all_profiles:
        if rp.hostname and rp.matches_host():
            active = rp
            break

    cumulative = load_cumulative_hours(hermes_home)

    return RigConfig(
        active=active,
        rigs=alt_rigs,
        cumulative_inference_hours=cumulative,
    )
