from langchain_openai import ChatOpenAI

import config
from git_collector import GitContext
from prompt_builder import build_messages


class LLMError(Exception):
    pass


def _build_client(model=None, api_key=None, base_url=None) -> ChatOpenAI:
    api_key = api_key or config.api_key()
    model = model or config.model()
    base_url = base_url or config.base_url()
    if not api_key or api_key.startswith("sk-your"):
        raise LLMError(
            "未配置 API Key。请点击界面上的「打开 .env」按钮，"
            "在 API_KEY 中填写你的 Key 后重试。"
        )
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        max_tokens=800,
        timeout=90,
    )


def generate_commit_message(ctx: GitContext, *, model=None, api_key=None, base_url=None) -> str:
    if not ctx.file_list:
        return "当前没有变更文件，无需生成提交信息。"
    messages = build_messages(ctx)
    try:
        client = _build_client(model=model, api_key=api_key, base_url=base_url)
        resp = client.invoke(messages)
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(friendly_error(e))

    text = resp.content if hasattr(resp, "content") else str(resp)
    return clean_message(text)


def friendly_error(e: Exception) -> str:
    name = type(e).__name__
    status = getattr(e, "status_code", None)
    code = getattr(e, "code", None)

    if status == 401:
        return "API Key 无效或已过期，请点「打开 .env」检查 API_KEY 是否正确。"
    if status == 403:
        return "没有权限访问该模型或接口，请检查账号权限和 Model 名称。"
    if status == 404:
        return "接口地址或模型不存在，请检查 Base URL 和 Model 是否正确。"
    if status == 429:
        return "请求太频繁或余额不足，请稍后再试。"
    if status == 500 or status == 502 or status == 503:
        return "模型服务暂时不可用，请稍后再试。"
    if "Timeout" in name or "timeout" in str(e).lower():
        return "请求超时，请检查网络连接后重试。"
    if "Connection" in name or "connection" in str(e).lower():
        return "无法连接模型服务，请检查网络或 Base URL 是否正确。"
    if "Authentication" in name or "authentication" in str(e).lower():
        return "API Key 认证失败，请点「打开 .env」检查 API_KEY 是否正确。"
    if "RateLimit" in name:
        return "请求太频繁或余额不足，请稍后再试。"
    if "BadRequest" in name or status == 400:
        return "请求参数有误，请检查 Model、Base URL 配置。"
    if code == "invalid_request_error":
        return "请求参数有误，请检查 Model、Base URL 配置。"

    detail = f"（{name}）" if name else ""
    return f"模型调用失败，请稍后重试{detail}。"


def clean_message(text: str) -> str:
    if not text:
        return ""
    lines = text.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    result = "\n".join(lines).strip()
    if result.startswith("```"):
        result = result.strip("`").strip()
        if result.lower().startswith("markdown"):
            result = result[len("markdown") :].strip()
    return result