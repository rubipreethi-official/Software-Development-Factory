"""
config.py — Centralized Configuration Management
=================================================
Task: S-02
Loads settings from environment variables (.env), validates them via Pydantic,
and provides YAML policy loading with hot-reload support.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


# ─── Environment Detection ─────────────────────────────────────────────────────

class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


# ─── Core Settings ──────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    """
    Root configuration loaded from environment variables.
    All values have sensible defaults for local development.
    """

    # --- Environment ---
    environment: Environment = Environment.DEVELOPMENT

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./data/control_plane.db"

    # --- Claude AI ---
    claude_api_key: str = "mock"
    claude_model: str = "claude-sonnet-4-20250514"

    # --- API Server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True

    # --- Authentication ---
    jwt_secret_key: str = "CHANGE-ME-IN-PRODUCTION-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # --- Rate Limiting ---
    rate_limit_per_minute: int = 60

    # --- Logging ---
    log_level: str = "DEBUG"

    # --- Observability ---
    trace_retention_days: int = 30
    metrics_enabled: bool = True

    # --- Policy ---
    policy_file: str = "config.yaml"

    # --- Derived ---
    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_mock_mode(self) -> bool:
        """True when Claude API key is not configured — use mock responses."""
        return self.claude_api_key in ("mock", "", "CHANGE-ME")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got '{v}'")
        return upper

    @field_validator("jwt_secret_key")
    @classmethod
    def warn_default_secret(cls, v: str) -> str:
        # Don't block, but the startup banner will warn
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


# ─── Policy System ─────────────────────────────────────────────────────────────

class PolicyManager:
    """
    Loads, validates, and serves YAML policy definitions.
    Supports hot-reload without service restart.
    """

    REQUIRED_SECTIONS = {
        "spec_validation",
        "validation_gates",
        "escalation",
        "agent_coordination",
        "orchestration",
        "observability",
    }

    def __init__(self, policy_path: str | Path):
        self._path = Path(policy_path)
        self._policies: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load and validate policy YAML."""
        if not self._path.exists():
            raise FileNotFoundError(
                f"Policy file not found: {self._path}. "
                f"Create it from the template or set POLICY_FILE in .env"
            )
        with open(self._path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise ValueError(f"Policy file must be a YAML mapping, got {type(raw)}")

        missing = self.REQUIRED_SECTIONS - set(raw.keys())
        if missing:
            # Warn but don't crash — allow partial policies during dev
            import structlog
            logger = structlog.get_logger("config")
            logger.warning("policy_sections_missing", missing=list(missing))

        self._policies = raw

    def reload(self) -> None:
        """Hot-reload policies from disk."""
        self._load()

    def get(self, section: str, key: str | None = None, default: Any = None) -> Any:
        """
        Retrieve a policy value.

        Examples:
            policy.get("spec_validation", "min_completeness_score")  → 0.7
            policy.get("escalation")  → full escalation dict
        """
        section_data = self._policies.get(section, {})
        if key is None:
            return section_data or default
        return section_data.get(key, default) if isinstance(section_data, dict) else default

    def get_gate_config(self, gate_name: str) -> dict[str, Any]:
        """Get configuration for a specific validation gate."""
        gates = self.get("validation_gates", default={})
        return gates.get(gate_name, {"blocking": False, "timeout": 300})

    def is_gate_blocking(self, gate_name: str) -> bool:
        """Check whether a validation gate is a hard block."""
        return self.get_gate_config(gate_name).get("blocking", False)

    @property
    def all_policies(self) -> dict[str, Any]:
        return dict(self._policies)


# ─── Singleton Access ───────────────────────────────────────────────────────────

@lru_cache()
def get_settings() -> Settings:
    """Get singleton Settings instance (cached)."""
    return Settings()


_policy_manager: PolicyManager | None = None


def get_policy_manager() -> PolicyManager:
    """Get singleton PolicyManager instance."""
    global _policy_manager
    if _policy_manager is None:
        settings = get_settings()
        _policy_manager = PolicyManager(settings.policy_file)
    return _policy_manager


def reload_policies() -> None:
    """Hot-reload policies without restarting."""
    global _policy_manager
    if _policy_manager is not None:
        _policy_manager.reload()
    else:
        get_policy_manager()
