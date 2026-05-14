from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def load_environment() -> None:
    """Load project environment variables before OpenAI or database setup."""
    load_dotenv(ENV_PATH)
    load_dotenv()
