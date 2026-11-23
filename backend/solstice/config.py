"""Loads config/settings.yaml once and exposes it as simple attributes.

Everything tunable for the demo (model, demo date, file paths) lives in YAML so a
live change never requires touching Python.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Repo root = two levels above this file's package (backend/solstice/config.py -> repo/)
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CSV_KEYS = ("properties_csv", "guests_csv", "inquiries_csv")


@dataclass(frozen=True)
class Settings:
    raw: dict

    def path(self, key: str) -> Path:
        p = REPO_ROOT / self.raw["paths"][key]
        # SOLSTICE_DATA_DIR swaps the three source CSVs for another set with the same file names,
        # e.g. the synthetic 10x data: SOLSTICE_DATA_DIR=data/synthetic
        alt = os.getenv("SOLSTICE_DATA_DIR")
        if alt and key in DATA_CSV_KEYS:
            return REPO_ROOT / alt / p.name
        return p

    def model_for(self, agent_name: str) -> str:
        """Per-agent override > env var override > default."""
        m = self.raw["model"]
        return m.get(agent_name) or os.getenv("SOLSTICE_MODEL") or m["default"]

    @property
    def max_tokens(self) -> int:
        return int(self.raw["model"]["max_tokens"])

    @property
    def request_timeout_s(self) -> float:
        return float(self.raw["model"].get("request_timeout_s", 30))

    @property
    def max_retries(self) -> int:
        return int(self.raw["model"].get("max_retries", 1))

    @property
    def max_tool_rounds(self) -> int:
        return int(self.raw["agent"]["max_tool_rounds"])

    @property
    def max_history_turns(self) -> int:
        return int(self.raw["agent"].get("max_history_turns", 12))

    def turn_deadline_for(self, agent: str) -> float:
        """Seconds one user turn may take in total before the agent hands off (settings.yaml -> agent)."""
        a = self.raw["agent"]
        if agent == "group_sales":
            return float(a.get("group_sales_turn_deadline_s", a.get("turn_deadline_s", 45)))
        return float(a.get("turn_deadline_s", 45))

    def limit(self, key: str) -> int:
        """Abuse/cost limits from settings.yaml -> limits."""
        return int(self.raw["limits"][key])

    @property
    def today(self) -> date:
        pinned = self.raw.get("demo_today")
        return date.fromisoformat(pinned) if pinned else date.today()

    def pin_for(self, role: str) -> str:
        """role: staff | admin. Env var override (SOLSTICE_STAFF_PIN / SOLSTICE_ADMIN_PIN) > settings.yaml."""
        return os.getenv(f"SOLSTICE_{role.upper()}_PIN") or str(self.raw["access"][f"{role}_pin"])

    def pin_source(self, role: str) -> str:
        return ".env override" if os.getenv(f"SOLSTICE_{role.upper()}_PIN") else "settings.yaml (demo value)"

    @property
    def max_failed_verifications(self) -> int:
        return int(self.raw["access"]["max_failed_verifications"])

    @property
    def latency_target_s(self) -> float:
        """Live-chat target (concierge: guests and front desk)."""
        return float(self.raw["latency"]["target_p95_seconds"])

    def latency_target_for(self, agent: str) -> float:
        """Group sales is back-office work with its own, looser target."""
        if agent == "group_sales":
            return float(self.raw["latency"].get("group_sales_target_p95_seconds", self.latency_target_s))
        return self.latency_target_s


_yaml_cache: dict[Path, tuple[float, object]] = {}
_settings_cache: tuple[float, Settings] | None = None


def load_yaml(path: Path):
    """Read a YAML config file, re-reading it whenever it changes on disk.
    That's what makes live edits (a discount cap, a rate limit, the model) take effect
    on the next request without restarting the app."""
    mtime = path.stat().st_mtime
    hit = _yaml_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    _yaml_cache[path] = (mtime, data)
    return data


def get_settings() -> Settings:
    global _settings_cache
    path = REPO_ROOT / "config" / "settings.yaml"
    mtime = path.stat().st_mtime
    if _settings_cache and _settings_cache[0] == mtime:
        return _settings_cache[1]
    load_dotenv(REPO_ROOT / ".env")
    _settings_cache = (mtime, Settings(raw=load_yaml(path)))
    return _settings_cache[1]
