import re
from typing import Optional

from langchain_openai import ChatOpenAI

import config
from git_collector import GitContext
from prompt_builder import build_messages


class LLMError(Exception):
    pass


_logger = None


def set_logger(fn) -> None:
    """注册日志回调（由 gui 注入 _log），用于把每次调用的诊断信息写进 gui-debug.log。"""
    global _logger
    _logger = fn


def _log(msg: str) -> None:
    if _logger is None:
        return
    try:
        _logger(msg)
    except Exception:
        pass


# 关闭思考过程的参数候选。不同网关字段名不统一，按实测命中率排序：
#   enable_thinking  —— 阿里云百炼 / DashScope 兼容模式（实测生效）
#   thinking         —— Anthropic 风格网关（实测生效）
#   reasoning_effort —— OpenAI / DeepSeek 风格（只能减少思考，无法完全关闭）
_THINKING_OFF_CANDIDATES = (
    ("enable_thinking=false", {"enable_thinking": False}),
    ("thinking.type=disabled", {"thinking": {"type": "disabled"}}),
    ("reasoning_effort=minimal", {"reasoning_effort": "minimal"}),
)
_THINKING_OFF_BODIES = dict(_THINKING_OFF_CANDIDATES)

_working_thinking_off = None  # 已确认生效的候选名（会话内缓存，避免重复试错）
_rejected_thinking_off = set()  # 被网关拒绝或无视的候选名


def _build_client(
    model=None,
    api_key=None,
    base_url=None,
    extra_body: Optional[dict] = None,
) -> ChatOpenAI:
    api_key = api_key or config.api_key()
    model = model or config.model()
    base_url = base_url or config.base_url()
    if not api_key or api_key.startswith("sk-your"):
        raise LLMError(
            "未配置 API Key。请点击界面上的「打开 .env」按钮，"
            "在 API_KEY 中填写你的 Key 后重试。"
        )
    extra = {"extra_body": extra_body} if extra_body else {}
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        max_tokens=config.max_tokens(),
        timeout=90,
        **extra,
    )


def _extract_text(resp) -> str:
    """把模型响应归一化成纯文本。

    部分网关在开启思考/工具能力后，content 会变成分块列表
    （如 [{"type": "text", "text": "..."}]），这里统一拼接文本块。
    """
    content = getattr(resp, "content", None)
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = str(block.get("type", "")).lower()
                if block_type in ("", "text", "output_text"):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _reasoning_text(resp) -> str:
    """取出思考过程字段（reasoning_content / reasoning），仅用于诊断。"""
    for holder in (
        getattr(resp, "additional_kwargs", None),
        getattr(resp, "response_metadata", None),
    ):
        if not isinstance(holder, dict):
            continue
        for key in ("reasoning_content", "reasoning"):
            value = holder.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _reasoning_tokens(resp) -> int:
    usage = getattr(resp, "usage_metadata", None) or {}
    details = usage.get("output_token_details") or {}
    try:
        return int(details.get("reasoning") or 0)
    except (TypeError, ValueError):
        return 0


def _diagnose(resp) -> dict:
    """汇总一次调用的关键指标，用于日志与空内容归因。"""
    usage = getattr(resp, "usage_metadata", None) or {}
    meta = getattr(resp, "response_metadata", None) or {}
    return {
        "finish_reason": meta.get("finish_reason") if isinstance(meta, dict) else None,
        "out_tokens": usage.get("output_tokens"),
        "reasoning_tokens": _reasoning_tokens(resp),
        "content_len": len(_extract_text(resp).strip()),
        "reasoning_chars": len(_reasoning_text(resp)),
    }


def _looks_like_param_rejected(e: Exception) -> bool:
    msg = str(e).lower()
    if any(
        w in msg
        for w in (
            "unrecognized request argument",
            "unknown parameter",
            "unsupported parameter",
            "invalid parameter",
            "extra fields not permitted",
        )
    ):
        return True
    status = getattr(e, "status_code", None)
    return status == 400 and any(
        k in msg for k in ("enable_thinking", "thinking", "reasoning_effort")
    )


def _invoke(messages, *, model, api_key, base_url, extra_body=None):
    client = _build_client(
        model=model, api_key=api_key, base_url=base_url, extra_body=extra_body
    )
    return client.invoke(messages)


def _invoke_thinking_off(messages, *, model, api_key, base_url):
    """依次尝试「关闭思考」的参数候选，返回响应；全部不可用时退回模型默认参数。"""
    global _working_thinking_off

    order = []
    if _working_thinking_off:
        order.append(_working_thinking_off)
    order += [
        name
        for name, _ in _THINKING_OFF_CANDIDATES
        if name != _working_thinking_off and name not in _rejected_thinking_off
    ]

    for name in order:
        try:
            resp = _invoke(
                messages,
                model=model,
                api_key=api_key,
                base_url=base_url,
                extra_body=_THINKING_OFF_BODIES[name],
            )
        except LLMError:
            raise
        except Exception as e:
            if _looks_like_param_rejected(e):
                _rejected_thinking_off.add(name)
                _log(f"[llm] 关闭思考参数被网关拒绝，改用下一个候选：{name}")
                continue
            raise
        if _reasoning_tokens(resp):
            # 参数被静默忽略：仍消耗了思考 token，视为无效候选
            _rejected_thinking_off.add(name)
            _log(f"[llm] 关闭思考参数未生效（仍消耗 {_reasoning_tokens(resp)} 思考 token）：{name}")
            return resp
        _working_thinking_off = name
        return resp

    _log("[llm] 所有关闭思考的参数候选均不可用，回退为模型默认参数")
    return _invoke(messages, model=model, api_key=api_key, base_url=base_url)


def _empty_advice(diag: dict) -> str:
    """正文为空时，给出可执行的修复建议（而不是让用户对着空白框发呆）。"""
    if diag.get("finish_reason") == "length" and diag.get("reasoning_tokens"):
        return (
            f"模型把 max_tokens（{config.max_tokens()}）全部用在了思考过程上，正文未能输出。"
            "请把 .env 里的 MAX_TOKENS 调大（建议 2048 以上），"
            "或将 THINKING 设为 off 后重试。"
        )
    if diag.get("reasoning_chars") and not diag.get("content_len"):
        return (
            "模型只返回了思考过程，没有输出提交信息。"
            f"请把 .env 里的 THINKING 设为 off（当前 {config.thinking()}）后重试。"
        )
    if diag.get("finish_reason") == "length":
        return "输出被 max_tokens 截断且正文为空。请把 .env 里的 MAX_TOKENS 调大后重试。"
    return "模型返回了空内容。请点「重新生成」重试；若反复出现，可更换 .env 里的 MODEL。"


def generate_commit_message(ctx: GitContext, *, model=None, api_key=None, base_url=None) -> str:
    if not ctx.file_list:
        return "当前没有变更文件，无需生成提交信息。"
    messages = build_messages(ctx)
    model = model or config.model()

    mode = config.thinking()
    if mode == "on":
        plans = [(False, "thinking=on（按配置保留思考）")]
    elif mode == "auto":
        plans = [
            (False, "thinking=auto（首次保留思考）"),
            (True, "thinking=auto（正文为空，降级关闭思考重试）"),
        ]
    else:
        plans = [(True, "thinking=off（按配置关闭思考）")]

    diag = {}
    for thinking_off, label in plans:
        try:
            if thinking_off:
                resp = _invoke_thinking_off(
                    messages, model=model, api_key=api_key, base_url=base_url
                )
            else:
                resp = _invoke(messages, model=model, api_key=api_key, base_url=base_url)
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(friendly_error(e))

        diag = _diagnose(resp)
        _log(
            f"[llm] {label} model={model} finish={diag['finish_reason']} "
            f"out_tokens={diag['out_tokens']} "
            f"reasoning_tokens={diag['reasoning_tokens']} "
            f"content_len={diag['content_len']} reasoning_chars={diag['reasoning_chars']}"
        )
        cleaned = clean_message(_extract_text(resp))
        if cleaned:
            return cleaned
        _log(f"[llm] 正文为空，诊断={diag}")

    raise LLMError(_empty_advice(diag))


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


_FENCE_LANG_RE = re.compile(r"[A-Za-z0-9_+.\-]*")


def _strip_fences(text: str) -> str:
    """只剥离首尾成对的代码围栏。

    旧实现用 str.strip("`") 按字符集剥离：既会吃掉正文首尾的反引号，
    又会在「模型只回了个空围栏」时把整条消息清成空串。
    这里改为按围栏数量判断——只有「成对包裹整条消息」或「孤立的一侧围栏」
    才剥，正文内部自带代码块的场景原样保留。
    """
    t = text.strip()
    fences = t.count("```")
    if fences == 0:
        return t
    if fences >= 2 and len(t) >= 6 and t.startswith("```") and t.endswith("```"):
        inner = t[3:-3]
        first, sep, rest = inner.partition("\n")
        # 首行是纯语言标记（markdown / text / git …）时丢弃
        if sep and _FENCE_LANG_RE.fullmatch(first.strip()):
            inner = rest
        return inner.strip()
    if fences == 1:
        # 模型只写了单侧围栏
        if t.startswith("```"):
            return t[3:].strip()
        if t.endswith("```"):
            return t[:-3].strip()
    return t


def clean_message(text: str) -> str:
    if not text:
        return ""
    result = _strip_fences(text)
    # 去掉模型额外加的包裹引号
    if len(result) >= 2 and result[0] == result[-1] and result[0] in ("'", '"'):
        result = result[1:-1].strip()
    return result
