"""Configuration management for Agentic AI Stress Suite.

This module provides hierarchical configuration loading with Pydantic BaseSettings.
Configuration sources are loaded in order of precedence (highest to lowest):
1. Environment variables (highest priority)
2. .env.local file (local overrides, gitignored)
3. .env file (committed defaults)
4. Field defaults (fallback values)

Teaching note: Use .env.local for machine-specific configuration (URLs, ports, paths).
Never commit .env.local to version control. This pattern allows:
- .env: Team-wide defaults (committed)
- .env.local: Developer-specific overrides (gitignored)
- Environment variables: CI/CD and production overrides

GPU Configuration:
The system automatically detects available GPU hardware:
- CUDA (NVIDIA): Priority 1 - Best for production ML workloads
- Metal (Apple Silicon): Priority 2 - M1/M2/M3/M4 Macs via MPS backend
- CPU: Priority 3 - Universal fallback
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.gpu import get_gpu_info

# Calculate project root (where .env files live)
# This file is at: src/core/config.py
# Project root is: ../../ from here
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class Environment(str, Enum):
    """Environment profiles for different deployment contexts."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):  # type: ignore[misc]
    """
    Application settings with hierarchical configuration loading.

    Configuration precedence (highest to lowest):
    1. Environment variables (CI/CD, production)
    2. .env.local (developer overrides, gitignored)
    3. .env (team defaults, committed)
    4. Field defaults (fallback)

    Teaching note: Pydantic BaseSettings loads env files in order.
    Later files override earlier ones. Field names are case-insensitive
    when loading from environment, but we use uppercase by convention.
    """

    model_config = SettingsConfigDict(
        # Load .env files from project root (not current working directory)
        # This allows running scripts from any directory (e.g., examples/)
        env_file=(
            str(PROJECT_ROOT / ".env"),  # Team defaults (committed)
            str(PROJECT_ROOT / ".env.local"),  # Local overrides (gitignored)
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields not defined in the model
    )

    # Environment
    environment: Environment = Field(
        default=Environment.DEV,
        description="Deployment environment profile",
    )

    # LLM API Keys
    # Teaching note: Cloud-first approach for LLMs due to M4 hardware constraints.
    # Groq provides cheapest development iteration, Claude/Gemini for quality,
    # OpenAI as final reliability fallback.
    groq_api_key: str | None = Field(default=None, description="Groq API key")
    deepseek_api_key: str | None = Field(default=None, description="DeepSeek API key")
    anthropic_api_key: str | None = Field(default=None, description="Anthropic Claude API key")
    google_api_key: str | None = Field(default=None, description="Google Gemini API key")
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    cohere_api_key: str | None = Field(default=None, description="Cohere API key for reranking")

    # GPU Configuration (auto-detected, can be overridden)
    # Teaching note: GPU backend is auto-detected at startup: CUDA > Metal > CPU
    # Override via GPU_BACKEND environment variable if needed (for testing or forcing CPU)
    gpu_backend: str | None = Field(
        default=None,
        description="GPU backend (cuda/metal/cpu) - auto-detected if not set",
    )
    gpu_device_name: str | None = Field(
        default=None,
        description="GPU device name - auto-detected if not set",
    )

    # Embeddings (local via text-embeddings-inference)
    # Teaching note: Defaults for localhost. Override via .env.local for Docker/production.
    embeddings_url: str = Field(
        default="http://localhost:8080",
        description="URL for local text-embeddings-inference server (BGE-base-en-v1.5)",
    )

    # Vector DB (Chroma - local dev)
    chroma_url: str = Field(default="http://localhost:8000", description="ChromaDB server URL")
    chroma_api_key: str | None = Field(
        default=None,
        description="ChromaDB API key (optional for local dev)",
    )

    # Redis (cache + state)
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL for caching and state persistence",
    )

    # Postgres (optional)
    postgres_url: str | None = Field(
        default=None,
        description="PostgreSQL connection URL (optional, for complex agent state)",
    )

    # Observability (Phoenix - local dev)
    phoenix_url: str = Field(
        default="http://localhost:6006", description="Arize Phoenix server URL"
    )
    phoenix_collector_endpoint: str = Field(
        default="http://localhost:6006/v1/traces",
        description="Phoenix OTLP trace collector endpoint",
    )
    observability_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for the @traced_retrieval / @traced_generation / "
            "@traced_tool_call decorators. When False, decorators short-circuit "
            "to a direct function call so benchmark runs measure the system "
            "without OTel overhead. Default True preserves the production "
            "tracing path; set OBSERVABILITY_ENABLED=false for clean "
            "latency/throughput numbers."
        ),
    )

    # LLM Configuration
    default_llm_model: str = Field(
        default="groq/llama-3-8b",
        description="Default LLM model for development (format: provider/model)",
    )
    default_llm_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Default temperature for LLM generation",
    )
    default_llm_max_tokens: int = Field(
        default=1000,
        gt=0,
        description="Default max tokens for LLM generation",
    )
    llm_request_timeout: int = Field(
        default=30,
        gt=0,
        description="LLM request timeout in seconds",
    )
    llm_enforce_guardrails: bool = Field(
        default=False,
        description=(
            "When True, UnifiedLLMClient applies regex-only GuardrailsManager "
            "to prompts before any provider call and raises GuardrailBlocked "
            "if input is rejected. Default off preserves existing behaviour; "
            "set LLM_ENFORCE_GUARDRAILS=true to enable in production."
        ),
    )

    # Cost Management
    monthly_budget_usd: float = Field(
        default=100.0,
        gt=0,
        description="Monthly budget for cloud LLM API calls in USD",
    )
    cost_alert_threshold: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        description="Alert when cost reaches this fraction of monthly budget",
    )

    # Cache Configuration
    cache_ttl_seconds: int = Field(
        default=86400,  # 24 hours
        gt=0,
        description="Time-to-live for cached responses in seconds",
    )
    semantic_cache_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for semantic cache hits",
    )

    # Reranking Configuration
    use_reranking: bool = Field(
        default=False,
        description="Enable reranking of retrieval results with cross-encoder",
    )
    reranking_backend: str = Field(
        default="flashrank",
        description="Reranking backend: 'flashrank' (local, free) or 'cohere' (cloud, $1/1K)",
    )
    reranking_model: str = Field(
        default="ms-marco-MiniLM-L-12-v2",
        description="FlashRank cross-encoder model for reranking",
    )
    reranking_top_k: int = Field(
        default=20,
        gt=0,
        description="Number of candidates to retrieve before reranking",
    )

    # Development
    debug: bool = Field(
        default=False,
        description="Enable debug mode with verbose logging",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v_upper

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, v: str | Environment) -> Environment:
        """Validate and normalize environment string to Environment enum."""
        if isinstance(v, Environment):
            return v
        try:
            return Environment(v.lower())
        except ValueError:
            valid = [e.value for e in Environment]
            raise ValueError(f"environment must be one of {valid}, got '{v}'")

    @model_validator(mode="after")
    def initialize_gpu_config(self) -> Settings:
        """
        Initialize GPU configuration if not explicitly set.

        Teaching note: This runs after all fields are loaded from env files
        and environment variables. If GPU settings aren't explicitly provided,
        we auto-detect the available hardware.

        This allows:
        - Automatic GPU detection for development (no config needed)
        - Manual override for testing (GPU_BACKEND=cpu for CI/CD)
        - Explicit configuration for production (GPU_BACKEND=cuda)
        """
        if self.gpu_backend is None or self.gpu_device_name is None:
            gpu_info = get_gpu_info()
            if self.gpu_backend is None:
                self.gpu_backend = gpu_info.backend.value
            if self.gpu_device_name is None:
                self.gpu_device_name = gpu_info.device_name

        return self

    def is_dev(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEV

    def is_test(self) -> bool:
        """Check if running in test environment."""
        return self.environment == Environment.TEST

    def is_prod(self) -> bool:
        """Check if running in production environment."""
        return self.environment == Environment.PROD

    def has_any_llm_key(self) -> bool:
        """
        Check if at least one LLM API key is configured.

        Teaching note: In production, you'd want at least one LLM provider
        configured. During development, you might use mock responses.
        """
        return any(
            [
                self.groq_api_key,
                self.deepseek_api_key,
                self.anthropic_api_key,
                self.google_api_key,
                self.openai_api_key,
            ]
        )

    def get_project_root(self) -> Path:
        """Get the project root directory."""
        return Path(__file__).parent.parent.parent

    def validate_required_for_production(self) -> None:
        """
        Validate that required fields for production are set.

        Teaching note: This method can be called explicitly when deploying
        to production to ensure critical configuration is present. We don't
        enforce this at init time to allow flexible local development.
        """
        if self.is_prod():
            if not self.has_any_llm_key():
                raise ValueError("At least one LLM API key must be configured for production")
            if self.redis_url == "redis://localhost:6379":
                raise ValueError("Production Redis URL must not be localhost")


# Singleton instance for application-wide access
_settings: Settings | None = None


def get_settings(force_reload: bool = False) -> Settings:
    """
    Get the singleton Settings instance.

    Args:
        force_reload: If True, reload settings from environment/files

    Returns:
        Settings instance

    Teaching note: Singleton pattern ensures consistent configuration
    across the application. Use force_reload=True in tests to simulate
    different configurations.
    """
    global _settings
    if _settings is None or force_reload:
        _settings = Settings()
    return _settings
