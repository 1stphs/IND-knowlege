from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://aihubmix.com/v1"
DEFAULT_MODEL = "grok-4-fast-non-reasoning"

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_DOTENV_PATH, override=True)

def _join_api(base_url: str, path: str) -> str:
    b = str(base_url or "").rstrip("/")
    p = str(path or "")
    if b.endswith("/v1") and p.startswith("/v1/"):
        return b + "/" + p[4:]
    return b + p


def retry_on_connection_error(max_retries=3, delay=2, backoff=True):
    """重试装饰器，处理SSL和连接错误"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (httpx.ConnectError, httpx.ProxyError, httpx.TimeoutException, httpx.TransportError) as e:
                    error_str = str(e)
                    # 捕获SSL相关错误
                    if any(keyword in error_str.lower() for keyword in ["ssl", "eof", "connection", "timeout"]):
                        last_error = e
                        if attempt < max_retries - 1:
                            wait_time = delay * (2 ** attempt) if backoff else delay
                            print(f"连接错误 (尝试 {attempt + 1}/{max_retries}): {e}", file=sys.stderr)
                            print(f"{wait_time}秒后重试...", file=sys.stderr)
                            time.sleep(wait_time)
                            continue
                    else:
                        # 非连接错误直接抛出
                        raise
                except Exception as e:
                    # 其他异常直接抛出
                    raise
            raise last_error if last_error else Exception("重试后仍然失败")
        return wrapper
    return decorator


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _is_summary_file(path: str) -> bool:
    name = os.path.basename(path).lower()
    return name.endswith(".summary.md")


def _summary_path_for(md_path: str) -> str:
    base = os.path.basename(md_path)
    if base.lower().endswith(".md"):
        stem = base[:-3]
    else:
        stem = base
    return os.path.join(os.path.dirname(md_path), f"{stem}.summary.md")


def _should_skip(source_path: str, summary_path: str, *, force: bool) -> bool:
    if force:
        return False
    if not os.path.exists(summary_path):
        return False
    return os.path.getmtime(summary_path) >= os.path.getmtime(source_path)


def _build_input_text(md_text: str, *, max_chars: int) -> str:
    text = (md_text or "").strip()
    if len(text) <= max_chars:
        return text
    head_len = max(1, int(max_chars * 0.75))
    tail_len = max_chars - head_len
    head = text[:head_len].rstrip()
    tail = text[-tail_len:].lstrip() if tail_len > 0 else ""
    if tail:
        return f"{head}\n\n[...内容过长，已截断...]\n\n{tail}"
    return head


@dataclass(frozen=True)
class AnthropicClient:
    base_url: str
    api_key: str
    timeout: float = 120.0  # 增加超时时间

    @retry_on_connection_error(max_retries=3, delay=2)
    def summarize(self, text: str, *, model: str, max_tokens: int) -> str:
        url = _join_api(self.base_url, "/v1/messages")
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": "你是一个严谨的中文文档摘要助手。输出为纯中文摘要，不要添加无关解释。",
            "messages": [
                {
                    "role": "user",
                    "content": text,
                }
            ],
        }
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
        }
        
        try:
            with httpx.Client(
                timeout=self.timeout, 
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=5),
                http2=False  # 禁用HTTP/2可能有助于某些连接问题
            ) as client:
                resp = client.post(url, headers=headers, json=body)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                # 尝试使用Bearer token方式
                headers_alt = dict(headers)
                headers_alt.pop("x-api-key", None)
                headers_alt["authorization"] = f"Bearer {self.api_key}"
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    resp = client.post(url, headers=headers_alt, json=body)
                    resp.raise_for_status()
            else:
                raise

        payload = resp.json()
        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    txt = item.get("text")
                    if isinstance(txt, str) and txt.strip():
                        parts.append(txt.strip())
            if parts:
                return "\n\n".join(parts).strip()
        raise ValueError("未从模型响应中解析到摘要文本")


@dataclass(frozen=True)
class OpenAIChatClient:
    base_url: str
    api_key: str
    timeout: float = 120.0  # 增加超时时间

    @retry_on_connection_error(max_retries=3, delay=2)
    def summarize(self, text: str, *, model: str, max_tokens: int) -> str:
        url = _join_api(self.base_url, "/v1/chat/completions")
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个严谨的中文文档摘要助手。输出为纯中文摘要，不要添加无关解释。",
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }
        
        with httpx.Client(
            timeout=self.timeout, 
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5),
            http2=False  # 禁用HTTP/2可能有助于某些连接问题
        ) as client:
            try:
                resp = client.post(url, headers=headers, json=body)
                resp.raise_for_status()
            except httpx.ConnectError as e:
                print(f"OpenAI连接失败: {e}", file=sys.stderr)
                raise
        
        payload = resp.json()
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        raise ValueError("未从模型响应中解析到摘要文本")


@dataclass(frozen=True)
class OpenVikingClient:
    base_url: str
    api_key: str
    timeout: float = 120.0  # 增加超时时间

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"content-type": "application/json"}
        account = str(os.getenv("OPENVIKING_ACCOUNT", "")).strip()
        user = str(os.getenv("OPENVIKING_USER", "")).strip()
        agent = str(os.getenv("OPENVIKING_AGENT", "")).strip()
        if account:
            headers["X-OpenViking-Account"] = account
        if user:
            headers["X-OpenViking-User"] = user
        if agent:
            headers["X-OpenViking-Agent"] = agent

        if self.api_key.lower().startswith("bearer "):
            headers["authorization"] = self.api_key
        else:
            headers["x-api-key"] = self.api_key
        return headers

    def _unwrap(self, payload: Any) -> Any:
        if isinstance(payload, dict) and "result" in payload:
            status = str(payload.get("status", "")).strip().lower()
            if status and status not in {"ok", "success"} and payload.get("error"):
                err = payload.get("error")
                if isinstance(err, dict):
                    code = err.get("code")
                    msg = err.get("message")
                    raise RuntimeError(f"OpenViking error: code={code} message={msg}")
                raise RuntimeError(f"OpenViking error: {err}")
            return payload.get("result")
        return payload

    @retry_on_connection_error(max_retries=3, delay=2)
    def create_session(self) -> str:
        url = self.base_url.rstrip("/") + "/api/v1/sessions"
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.post(url, headers=self._headers(), json={})
            resp.raise_for_status()
        data = self._unwrap(resp.json())
        if isinstance(data, dict):
            for key in ("session_id", "id", "sessionId"):
                v = data.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        if isinstance(data, str) and data.strip():
            return data.strip()
        raise ValueError("未从 OpenViking 响应中解析到 session_id")

    @retry_on_connection_error(max_retries=2, delay=1)
    def delete_session(self, session_id: str) -> None:
        url = self.base_url.rstrip("/") + f"/api/v1/sessions/{session_id}"
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.delete(url, headers=self._headers())
            if resp.status_code in (404, 410):
                return
            resp.raise_for_status()

    @retry_on_connection_error(max_retries=3, delay=2)
    def add_message(self, session_id: str, *, role: str, content: str) -> Any:
        url = self.base_url.rstrip("/") + f"/api/v1/sessions/{session_id}/messages"
        body = {"role": role, "content": content}
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
        return self._unwrap(resp.json())

    @retry_on_connection_error(max_retries=3, delay=2)
    def get_session(self, session_id: str) -> Any:
        url = self.base_url.rstrip("/") + f"/api/v1/sessions/{session_id}"
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=self._headers())
            resp.raise_for_status()
        return self._unwrap(resp.json())


def _extract_assistant_text(payload: Any) -> str | None:
    if isinstance(payload, dict):
        if "messages" in payload and isinstance(payload["messages"], list):
            for item in reversed(payload["messages"]):
                if isinstance(item, dict):
                    role = str(item.get("role", "")).strip().lower()
                    if role == "assistant":
                        content = item.get("content")
                        if isinstance(content, str) and content.strip():
                            return content.strip()
                        parts = item.get("parts")
                        if isinstance(parts, list):
                            texts: list[str] = []
                            for p in parts:
                                if isinstance(p, dict) and p.get("type") == "text":
                                    t = p.get("text")
                                    if isinstance(t, str) and t.strip():
                                        texts.append(t.strip())
                            if texts:
                                return "\n\n".join(texts).strip()
        for v in payload.values():
            got = _extract_assistant_text(v)
            if got:
                return got
    if isinstance(payload, list):
        for v in reversed(payload):
            got = _extract_assistant_text(v)
            if got:
                return got
    return None


def _summarize_with_fallback(
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    text: str,
    provider: str,
) -> str:
    normalized = str(provider or "").strip().lower() or "auto"
    if normalized not in {"auto", "openai", "anthropic", "openviking"}:
        raise ValueError("provider 仅支持 auto/openai/anthropic/openviking")

    last_error: Exception | None = None
    if normalized == "auto":
        host = urlparse(base_url).netloc.lower()
        if "openai" in host:
            candidates = ["openai"]
        elif "anthropic" in host or "claude" in host:
            candidates = ["anthropic"]
        elif host and all(ch.isdigit() or ch in ".:" for ch in host):
            candidates = ["openviking"]
        else:
            candidates = ["openai", "anthropic", "openviking"]
    else:
        candidates = [normalized]
    
    for kind in candidates:
        try:
            print(f"尝试使用 {kind} 提供商进行摘要...", file=sys.stderr)
            if kind == "openai":
                return OpenAIChatClient(base_url=base_url, api_key=api_key).summarize(
                    text, model=model, max_tokens=max_tokens
                )
            if kind == "anthropic":
                return AnthropicClient(base_url=base_url, api_key=api_key).summarize(
                    text, model=model, max_tokens=max_tokens
                )
            client = OpenVikingClient(base_url=base_url, api_key=api_key)
            session_id = client.create_session()
            try:
                client.add_message(session_id, role="user", content=text)
                deadline = time.monotonic() + 180.0  # 增加到3分钟
                while True:
                    state = client.get_session(session_id)
                    msg = _extract_assistant_text(state)
                    if msg:
                        return msg
                    if time.monotonic() >= deadline:
                        raise TimeoutError("等待 OpenViking 生成摘要超时")
                    time.sleep(0.8)
            finally:
                try:
                    client.delete_session(session_id)
                except Exception as e:
                    print(f"删除会话失败: {e}", file=sys.stderr)
        except Exception as exc:
            print(f"{kind} 摘要失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            last_error = exc
            continue
    assert last_error is not None
    raise last_error


def _iter_md_files(output_dir: str) -> list[str]:
    paths: list[str] = []
    for name in sorted(os.listdir(output_dir)):
        path = os.path.join(output_dir, name)
        if not os.path.isfile(path):
            continue
        if not name.lower().endswith(".md"):
            continue
        if _is_summary_file(path):
            continue
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    parser.add_argument(
        "--base-url",
        default=os.getenv(
            "OPENVIKING_LLM_API_BASE",
            os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        ),
    )
    parser.add_argument(
        "--model",
        default=os.getenv(
            "OPENVIKING_LLM_MODEL",
            os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        ),
    )
    parser.add_argument(
        "--provider",
        default=os.getenv(
            "OPENVIKING_LLM_PROVIDER",
            os.getenv("SUMMARY_PROVIDER", "auto"),
        ),
    )
    parser.add_argument("--max-input-chars", type=int, default=14000)
    parser.add_argument("--max-output-tokens", type=int, default=400)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    args = parser.parse_args()

    api_key = (
        str(os.getenv("OPENVIKING_LLM_API_KEY", "")).strip()
        or str(os.getenv("OPENVIKING_API_KEY", "")).strip()
        or str(os.getenv("OPENAI_API_KEY", "")).strip()
    )
    if not api_key:
        print("缺少环境变量 OPENVIKING_LLM_API_KEY / OPENVIKING_API_KEY / OPENAI_API_KEY", file=sys.stderr)
        return 2
    if api_key.lower().startswith("bearer "):
        api_key = api_key.strip()

    # 调试信息
    print(f"配置信息:", file=sys.stderr)
    print(f"  Base URL: {args.base_url}", file=sys.stderr)
    print(f"  Model: {args.model}", file=sys.stderr)
    print(f"  Provider: {args.provider}", file=sys.stderr)
    print(f"  API Key 前缀: {api_key[:15]}..." if len(api_key) > 15 else "  API Key: [已设置]", file=sys.stderr)
    print(f"  .env 文件: {_DOTENV_PATH} ({'存在' if _DOTENV_PATH.exists() else '不存在'})", file=sys.stderr)
    used_base_env = next((n for n in ("OPENVIKING_LLM_API_BASE", "OPENAI_BASE_URL") if os.getenv(n)), None)
    used_model_env = next((n for n in ("OPENVIKING_LLM_MODEL", "OPENAI_MODEL") if os.getenv(n)), None)
    used_provider_env = next((n for n in ("OPENVIKING_LLM_PROVIDER", "SUMMARY_PROVIDER") if os.getenv(n)), None)
    used_key_env = next((n for n in ("OPENVIKING_LLM_API_KEY", "OPENVIKING_API_KEY", "OPENAI_API_KEY") if os.getenv(n)), None)
    print(f"  Base 来源: {used_base_env or '默认'}", file=sys.stderr)
    print(f"  Model 来源: {used_model_env or '默认'}", file=sys.stderr)
    print(f"  Provider 来源: {used_provider_env or '默认'}", file=sys.stderr)
    print(f"  Key 来源: {used_key_env or '未找到'}", file=sys.stderr)
    print(file=sys.stderr)

    output_dir = str(args.output_dir or "").strip() or "output"
    if not os.path.isdir(output_dir):
        print(f"目录不存在: {output_dir}", file=sys.stderr)
        return 2

    base_url = str(args.base_url)
    model = str(args.model)
    provider = str(args.provider)
    md_files = _iter_md_files(output_dir)
    if not md_files:
        print("output 目录下未找到需要摘要的 .md 文件", file=sys.stderr)
        return 0

    written = 0
    for md_path in md_files:
        summary_path = _summary_path_for(md_path)
        if _should_skip(md_path, summary_path, force=bool(args.force)):
            print(f"跳过已存在的摘要: {os.path.basename(md_path)}", file=sys.stderr)
            continue
        
        print(f"处理文件: {os.path.basename(md_path)}", file=sys.stderr)
        md_text = _read_text(md_path)
        prompt_text = _build_input_text(md_text, max_chars=int(args.max_input_chars))
        
        try:
            summary = _summarize_with_fallback(
                base_url=base_url,
                api_key=api_key,
                model=model,
                max_tokens=int(args.max_output_tokens),
                text=prompt_text,
                provider=provider,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                print(
                    "401 Unauthorized：当前 API Key 对该服务无效，或该服务需要不同的鉴权方式/Key",
                    file=sys.stderr,
                )
                return 2
            print(f"HTTP错误: {exc}", file=sys.stderr)
            raise
        except Exception as exc:
            print(f"摘要生成失败: {exc}", file=sys.stderr)
            raise
        
        title = os.path.basename(md_path)
        out = f"# {title} 摘要\n\n{summary.strip()}\n"
        _write_text(summary_path, out)
        written += 1
        print(f"已生成摘要: {os.path.abspath(summary_path)}")
        time.sleep(max(0.0, float(args.sleep_seconds)))

    if written == 0:
        print("无需要更新的摘要（可用 --force 强制重算）", file=sys.stderr)
    else:
        print(f"成功生成 {written} 个摘要文件", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
