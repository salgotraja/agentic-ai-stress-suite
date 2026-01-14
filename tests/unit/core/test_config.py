"""Unit tests for configuration management."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.config import Environment, Settings, get_settings


class TestEnvironmentEnum:
    """Test Environment enum."""

    def test_environment_values(self) -> None:
        """Test that Environment enum has expected values."""
        assert Environment.DEV.value == "dev"
        assert Environment.TEST.value == "test"
        assert Environment.PROD.value == "prod"


class TestSettings:
    """Test Settings class."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that default values are set correctly."""
        # Clear any existing .env file influence by overriding env vars
        # This ensures we're testing the actual defaults, not .env placeholders
        monkeypatch.setenv("GROQ_API_KEY", "")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("LOG_LEVEL", "INFO")

        settings = Settings()

        assert settings.environment == Environment.DEV
        # Empty string from env becomes None for optional fields
        assert settings.groq_api_key == "" or settings.groq_api_key is None
        assert settings.embeddings_url == "http://localhost:8080"
        assert settings.chroma_url == "http://localhost:8000"
        assert settings.redis_url == "redis://localhost:6379"
        assert settings.default_llm_model == "groq/llama-3-8b"
        assert settings.default_llm_temperature == 0.7
        assert settings.default_llm_max_tokens == 1000
        assert settings.llm_request_timeout == 30
        assert settings.monthly_budget_usd == 100.0
        assert settings.cost_alert_threshold == 0.8
        assert settings.cache_ttl_seconds == 86400
        assert settings.semantic_cache_threshold == 0.95
        assert settings.debug is False
        assert settings.log_level == "INFO"

    def test_environment_variable_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that environment variables override defaults."""
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("GROQ_API_KEY", "test_groq_key")
        monkeypatch.setenv("DEFAULT_LLM_TEMPERATURE", "0.5")
        monkeypatch.setenv("DEBUG", "true")

        settings = Settings()

        assert settings.environment == Environment.PROD
        assert settings.groq_api_key == "test_groq_key"
        assert settings.default_llm_temperature == 0.5
        assert settings.debug is True

    def test_case_insensitive_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that environment variable names are case-insensitive."""
        monkeypatch.setenv("groq_api_key", "test_key_lowercase")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_uppercase")

        settings = Settings()

        assert settings.groq_api_key == "test_key_lowercase"
        assert settings.anthropic_api_key == "test_key_uppercase"

    def test_log_level_validation_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that valid log levels are accepted."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        for level in valid_levels:
            monkeypatch.setenv("LOG_LEVEL", level)
            settings = Settings()
            assert settings.log_level == level

    def test_log_level_validation_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that log level validation is case-insensitive."""
        monkeypatch.setenv("LOG_LEVEL", "debug")
        settings = Settings()
        assert settings.log_level == "DEBUG"

        monkeypatch.setenv("LOG_LEVEL", "Info")
        settings = Settings()
        assert settings.log_level == "INFO"

    def test_log_level_validation_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that invalid log levels raise ValidationError."""
        monkeypatch.setenv("LOG_LEVEL", "INVALID")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "log_level must be one of" in str(exc_info.value)

    def test_environment_validation_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that valid environments are accepted."""
        for env in ["dev", "test", "prod"]:
            monkeypatch.setenv("ENVIRONMENT", env)
            settings = Settings()
            assert settings.environment == Environment(env)

    def test_environment_validation_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that environment validation is case-insensitive."""
        monkeypatch.setenv("ENVIRONMENT", "DEV")
        settings = Settings()
        assert settings.environment == Environment.DEV

        monkeypatch.setenv("ENVIRONMENT", "Prod")
        settings = Settings()
        assert settings.environment == Environment.PROD

    def test_environment_validation_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that invalid environments raise ValidationError."""
        monkeypatch.setenv("ENVIRONMENT", "invalid")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "environment must be one of" in str(exc_info.value)

    def test_temperature_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that temperature is validated to be between 0 and 2."""
        # Valid temperature
        monkeypatch.setenv("DEFAULT_LLM_TEMPERATURE", "1.0")
        settings = Settings()
        assert settings.default_llm_temperature == 1.0

        # Invalid: below minimum
        monkeypatch.setenv("DEFAULT_LLM_TEMPERATURE", "-0.1")
        with pytest.raises(ValidationError):
            Settings()

        # Invalid: above maximum
        monkeypatch.setenv("DEFAULT_LLM_TEMPERATURE", "2.1")
        with pytest.raises(ValidationError):
            Settings()

    def test_positive_integer_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that positive integer fields are validated."""
        # Valid
        monkeypatch.setenv("DEFAULT_LLM_MAX_TOKENS", "500")
        settings = Settings()
        assert settings.default_llm_max_tokens == 500

        # Invalid: zero
        monkeypatch.setenv("DEFAULT_LLM_MAX_TOKENS", "0")
        with pytest.raises(ValidationError):
            Settings()

        # Invalid: negative
        monkeypatch.setenv("DEFAULT_LLM_MAX_TOKENS", "-1")
        with pytest.raises(ValidationError):
            Settings()


class TestSettingsHelperMethods:
    """Test Settings helper methods."""

    def test_is_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test is_dev() method."""
        monkeypatch.setenv("ENVIRONMENT", "dev")
        settings = Settings()
        assert settings.is_dev() is True
        assert settings.is_test() is False
        assert settings.is_prod() is False

    def test_is_test(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test is_test() method."""
        monkeypatch.setenv("ENVIRONMENT", "test")
        settings = Settings()
        assert settings.is_dev() is False
        assert settings.is_test() is True
        assert settings.is_prod() is False

    def test_is_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test is_prod() method."""
        monkeypatch.setenv("ENVIRONMENT", "prod")
        settings = Settings()
        assert settings.is_dev() is False
        assert settings.is_test() is False
        assert settings.is_prod() is True

    def test_has_any_llm_key_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test has_any_llm_key() returns False when no keys are set."""
        # Override .env by setting env vars to empty
        for key in [
            "GROQ_API_KEY",
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
        ]:
            monkeypatch.setenv(key, "")

        settings = Settings()
        assert settings.has_any_llm_key() is False

    def test_has_any_llm_key_with_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test has_any_llm_key() returns True when at least one key is set."""
        # Test with each key individually
        keys = [
            "GROQ_API_KEY",
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
        ]

        for key in keys:
            # Clear all keys
            for k in keys:
                monkeypatch.delenv(k, raising=False)

            # Set only one key
            monkeypatch.setenv(key, "test_key")
            settings = Settings()
            assert settings.has_any_llm_key() is True, f"Failed for {key}"

    def test_get_project_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test get_project_root() returns correct path."""
        settings = Settings()
        project_root = settings.get_project_root()

        assert isinstance(project_root, Path)
        # Should be three levels up from src/core/config.py
        assert project_root.name == "agentic-ai-stress-suite"
        assert (project_root / "src" / "core" / "config.py").exists()


class TestProductionValidation:
    """Test production-specific validation."""

    def test_validate_required_for_production_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that production validation passes with required config."""
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("GROQ_API_KEY", "test_key")
        monkeypatch.setenv("REDIS_URL", "redis://prod-redis:6379")

        settings = Settings()
        # Should not raise
        settings.validate_required_for_production()

    def test_validate_required_for_production_no_llm_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that production validation fails without LLM key."""
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("REDIS_URL", "redis://prod-redis:6379")
        # Override .env by setting all LLM keys to empty
        for key in [
            "GROQ_API_KEY",
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
        ]:
            monkeypatch.setenv(key, "")

        settings = Settings()

        with pytest.raises(ValueError, match="At least one LLM API key must be configured"):
            settings.validate_required_for_production()

    def test_validate_required_for_production_localhost_redis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that production validation fails with localhost Redis."""
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("GROQ_API_KEY", "test_key")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        settings = Settings()

        with pytest.raises(ValueError, match="Production Redis URL must not be localhost"):
            settings.validate_required_for_production()

    def test_validate_required_for_production_skipped_for_dev(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that production validation is skipped for dev environment."""
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        # No LLM keys set

        settings = Settings()
        # Should not raise even though we're using localhost and have no LLM keys
        settings.validate_required_for_production()


class TestGetSettings:
    """Test get_settings singleton function."""

    def test_get_settings_returns_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that get_settings returns the same instance."""
        # Force reload to clear any previous state
        settings1 = get_settings(force_reload=True)
        settings2 = get_settings()

        assert settings1 is settings2

    def test_get_settings_force_reload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that force_reload creates a new instance with updated config."""
        monkeypatch.setenv("DEFAULT_LLM_TEMPERATURE", "0.5")
        settings1 = get_settings(force_reload=True)
        assert settings1.default_llm_temperature == 0.5

        # Change environment variable
        monkeypatch.setenv("DEFAULT_LLM_TEMPERATURE", "0.9")

        # Without force_reload, should get cached instance
        settings2 = get_settings()
        assert settings2.default_llm_temperature == 0.5  # Still old value

        # With force_reload, should get new instance
        settings3 = get_settings(force_reload=True)
        assert settings3.default_llm_temperature == 0.9  # New value


class TestHierarchicalLoading:
    """Test hierarchical configuration loading precedence."""

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that environment variables override default values."""
        # Default is 0.7
        settings_default = Settings()
        assert settings_default.default_llm_temperature == 0.7

        # Override with env var
        monkeypatch.setenv("DEFAULT_LLM_TEMPERATURE", "0.3")
        settings_override = Settings()
        assert settings_override.default_llm_temperature == 0.3

    def test_multiple_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test multiple configuration overrides."""
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("LOG_LEVEL", "debug")
        monkeypatch.setenv("DEFAULT_LLM_MAX_TOKENS", "2000")
        monkeypatch.setenv("GROQ_API_KEY", "test_groq")

        settings = Settings()

        assert settings.environment == Environment.TEST
        assert settings.debug is True
        assert settings.log_level == "DEBUG"
        assert settings.default_llm_max_tokens == 2000
        assert settings.groq_api_key == "test_groq"
