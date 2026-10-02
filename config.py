import sys
from pathlib import Path

from dotenv import dotenv_values

if getattr(sys, "frozen", False):
    PROJECT_DIR = Path(sys.executable).parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent

_DOTENV = dotenv_values(PROJECT_DIR / ".env")


def _get(name: str, default: str) -> str:
    value = _DOTENV.get(name)
    value = value or default
    return value.strip() if value else default


def app_base_dir() -> Path:
    return PROJECT_DIR


def api_key() -> str:
    return _get("API_KEY", "")


def model() -> str:
    return _get("MODEL", "deepseek-chat")


def base_url() -> str:
    return _get("BASE_URL", "") or _get("base_url", "https://api.deepseek.com")


def commit_language() -> str:
    return _get("COMMIT_LANGUAGE", "zh")


def commit_style() -> str:
    return _get("COMMIT_STYLE", "conventional")


def max_tokens() -> int:
    """单次生成的最大 token 预算。

    思考型模型会把 reasoning 和正文都算在这个额度里，额度太小会导致
    «思考把额度用光、正文为空»，因此下限保护到 512。
    """
    try:
        return max(512, int(_get("MAX_TOKENS", "2048")))
    except ValueError:
        return 2048


def thinking() -> str:
    """思考模式：off（默认，直接输出正文）/ on（保留思考）/ auto（先思考，正文为空再降级关闭）"""
    value = _get("THINKING", "off").lower()
    return value if value in ("off", "on", "auto") else "off"


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