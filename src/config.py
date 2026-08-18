"""Environment-backed settings. Values come from `.env` or process env vars."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime config for the demo: OpenAI, SQLite path, and policy thresholds."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    database_url: str = "sqlite:///./data/demo.db"
    auto_remediate: bool = True
    host: str = Field(
        default="127.0.0.1", validation_alias=AliasChoices("APP_HOST", "host")
    )
    port: int = Field(default=8000, validation_alias=AliasChoices("APP_PORT", "port"))
    data_dir: str = ""
    classify_confidence_threshold: float = Field(default=0.55)
    diagnose_confidence_threshold: float = Field(default=0.60)
    max_investigate_steps: int = Field(default=6)  # cap LLM tool-calling loops

    def resolved_data_dir(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir).resolve()
        # src/config.py → repo/data
        repo_data = Path(__file__).resolve().parents[1] / "data"
        if repo_data.exists():
            return repo_data
        return Path.cwd() / "data"


@lru_cache
def get_settings() -> Settings:
    """Cached Settings instance; CLI clears the cache after setting DATA_DIR."""
    return Settings()
