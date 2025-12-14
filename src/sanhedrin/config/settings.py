"""
Configuration settings using Pydantic Settings.

Loads from environment variables and .env files.
"""

from __future__ import annotations

from typing import Any
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SANHEDRIN_",
        env_file=".env",
        extra="ignore",
    )

    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    base_url: str | None = Field(default=None, description="Public base URL")
    reload: bool = Field(default=False, description="Enable auto-reload")


class AdapterSettings(BaseSettings):
    """Adapter configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SANHEDRIN_",
        env_file=".env",
        extra="ignore",
    )

    adapter: str = Field(default="claude-code", description="Default adapter")
    timeout: float = Field(default=120.0, description="Execution timeout")
    max_retries: int = Field(default=3, description="Max retry attempts")


class OllamaSettings(BaseSettings):
    """Ollama-specific settings."""

    model_config = SettingsConfigDict(
        env_prefix="OLLAMA_",
        env_file=".env",
        extra="ignore",
    )

    host: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL",
    )
    model: str = Field(default="llama3.2", description="Default model")


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_prefix="SANHEDRIN_",
        env_file=".env",
        extra="ignore",
    )

    # Nested settings
    server: ServerSettings = Field(default_factory=ServerSettings)
    adapter: AdapterSettings = Field(default_factory=AdapterSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string",
    )

    # Provider info
    provider_name: str = Field(default="Sanhedrin", description="Provider name")
    provider_url: str = Field(
        default="https://github.com/sanhedrin",
        description="Provider URL",
    )

    def get_base_url(self) -> str:
        """Get effective base URL."""
        if self.server.base_url:
            return self.server.base_url
        return f"http://{self.server.host}:{self.server.port}"


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings."""
    global _settings
    _settings = Settings()
    return _settings
