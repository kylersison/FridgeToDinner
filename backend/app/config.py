"""Runtime settings, read from environment variables (or a local .env file)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5").strip()
    force_mock: bool = _bool("MOCK_MODE")
    max_image_edge: int = int(os.getenv("MAX_IMAGE_EDGE", "1024"))
    max_generation_attempts: int = int(os.getenv("MAX_GENERATION_ATTEMPTS", "2"))
    price_in_per_mtok: float = float(os.getenv("PRICE_INPUT_PER_MTOK", "1.0"))
    price_out_per_mtok: float = float(os.getenv("PRICE_OUTPUT_PER_MTOK", "5.0"))

    @property
    def mock_mode(self) -> bool:
        """Mock mode runs without an API key, so anyone can try the full flow."""
        return self.force_mock or not self.api_key


settings = Settings()
