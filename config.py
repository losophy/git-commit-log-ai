import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(sys.executable).parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent

load_dotenv(PROJECT_DIR / ".env")


def _get(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value.strip() if value else default


def app_base_dir() -> Path:
    return PROJECT_DIR


def llm_api_key() -> str:
    return _get("LLM_API_KEY", "")


def deepseek_model() -> str:
    return _get("DEEPSEEK_MODEL", "deepseek-chat")


def deepseek_base_url() -> str:
    return _get("LLM_BASE_URL", "") or _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def commit_language() -> str:
    return _get("COMMIT_LANGUAGE", "zh")


def commit_style() -> str:
    return _get("COMMIT_STYLE", "conventional")


def max_diff_lines() -> int:
    try:
        return max(1, int(_get("MAX_DIFF_LINES", "600")))
    except ValueError:
        return 600


def recent_commits() -> int:
    try:
        return max(0, int(_get("RECENT_COMMITS", "5")))
    except ValueError:
        return 5