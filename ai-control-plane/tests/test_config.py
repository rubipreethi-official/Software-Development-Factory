"""
test_config.py — Unit tests for config.py
==========================================
Task: V-01
Tests Settings loading, validation, and PolicyManager behavior.
"""

import os
import pytest
from pathlib import Path


class TestSettings:
    """Tests for the Settings class."""

    def test_defaults_load(self):
        """Settings loads with sensible dev defaults."""
        from config import Settings
        s = Settings(
            _env_file=None,
            claude_api_key="mock",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        assert s.environment.value == "development"
        assert s.api_port == 8000
        assert s.jwt_algorithm == "HS256"

    def test_is_mock_mode_true(self):
        """is_mock_mode returns True for mock key."""
        from config import Settings
        s = Settings(_env_file=None, claude_api_key="mock")
        assert s.is_mock_mode is True

    def test_is_mock_mode_false(self):
        """is_mock_mode returns False for a real key."""
        from config import Settings
        s = Settings(_env_file=None, claude_api_key="sk-ant-real-key-here")
        assert s.is_mock_mode is False

    def test_is_development(self):
        from config import Settings
        s = Settings(_env_file=None, environment="development")
        assert s.is_development is True
        assert s.is_production is False

    def test_is_production(self):
        from config import Settings
        s = Settings(_env_file=None, environment="production")
        assert s.is_production is True
        assert s.is_development is False

    def test_invalid_log_level_rejected(self):
        """Invalid log level raises ValueError."""
        from config import Settings
        with pytest.raises(Exception):
            Settings(_env_file=None, log_level="TRACE")

    def test_valid_log_levels(self):
        """All standard log levels are accepted."""
        from config import Settings
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            s = Settings(_env_file=None, log_level=level)
            assert s.log_level == level


class TestPolicyManager:
    """Tests for PolicyManager."""

    def test_loads_config_yaml(self):
        """PolicyManager loads the real config.yaml."""
        from config import PolicyManager
        pm = PolicyManager("config.yaml")
        assert "spec_validation" in pm.all_policies

    def test_get_section(self):
        from config import PolicyManager
        pm = PolicyManager("config.yaml")
        sv = pm.get("spec_validation")
        assert isinstance(sv, dict)

    def test_get_key(self):
        from config import PolicyManager
        pm = PolicyManager("config.yaml")
        score = pm.get("spec_validation", "min_completeness_score", 0.7)
        assert isinstance(score, (int, float))

    def test_get_default(self):
        from config import PolicyManager
        pm = PolicyManager("config.yaml")
        val = pm.get("nonexistent_section", "nonexistent_key", "fallback")
        assert val == "fallback"

    def test_is_gate_blocking(self):
        from config import PolicyManager
        pm = PolicyManager("config.yaml")
        # Returns a bool regardless of what's in config
        result = pm.is_gate_blocking("contract_validation")
        assert isinstance(result, bool)

    def test_file_not_found(self):
        from config import PolicyManager
        with pytest.raises(FileNotFoundError):
            PolicyManager("nonexistent_file_xyz.yaml")

    def test_reload(self):
        from config import PolicyManager
        pm = PolicyManager("config.yaml")
        # Should not raise
        pm.reload()
        assert len(pm.all_policies) > 0
