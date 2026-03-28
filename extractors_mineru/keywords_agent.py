from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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

KEYWORDS_SYSTEM_PROMPT = """你是一个专业的技术文档分析师。请分析以下Markdown文档，提取核心关键词。 
 
 ## 第一步：文档分析 
 1. 统计文档总字数（不含代码块、表格） 
 2. 判断文档类型（目录/产品说明/参考文献/文献综述等） 
 
 ## 第二步：确定关键词数量 
 根据以下规则自动确定输出多少个关键词： 
 
 | 文档字数范围 | 输出关键词数量 | 
 |------------|--------------| 
 | < 500字 | 5-8个 | 
 | 500-1500字 | 8-12个 | 
 | 1500-3000字 | 12-18个 | 
 | 3000-6000字 | 18-25个 | 
 | 6000-12000字 | 25-35个 | 
 | 12000-20000字 | 35-45个 | 
 | > 20000字 | 45-60个 | 
 
 ## 第三步：关键词提取要求 
 1. 过滤停用词（的、了、是、在、等、也、都、并、则、以、于、而、及） 
 2. 过滤通用动词（进行、实现、使用、采用、通过、提供、支持） 
 3. 合并同义词/近义词（如"机器学习"和"ML"合并，"API"和"接口"根据上下文判断） 
 4. 优先保留： 
    - 专业术语和技术概念 
    - 核心业务实体 
    - 关键指标和参数 
    - 重复出现的重要短语（2-4字组合） 
 
 ## 输出格式 
 严格按照以下JSON格式输出，不要添加任何额外说明文字： 
 
 ```json 
 { 
   "meta": { 
     "total_chars": 0, 
     "total_words": 0, 
     "doc_type": "", 
     "keywords_count": 0, 
     "analysis_time": "" 
   }, 
   "keywords": [ 
     { 
       "rank": 1, 
       "word": "", 
       "frequency": 0, 
       "significance": "", 
       "category": "" 
     } 
   ], 
   "clusters": { 
     "分类名称": ["关键词1", "关键词2"] 
   } 
 }
"""


def _join_api(base_url: str, path: str) -> str:
    b = str(base_url or "").rstrip("/")
    p = str(path or "")
    if b.endswith("/v1") and p.startswith("/v1/"):
        return b + "/" + p[4:]
    return b + p


def retry_on_connection_error(max_retries=3, delay=2, backoff=True):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (
                    httpx.ConnectError,
                    httpx.ProxyError,
                    httpx.TimeoutException,
                    httpx.TransportError,
                ) as e:
                    error_str = str(e)
                    if any(
                        keyword in error_str.lower()
                        for keyword in ["ssl", "eof", "connection", "timeout"]
                    ):
                        last_error = e
                        if attempt < max_retries - 1:
                            wait_time = delay * (2**attempt) if backoff else delay
                            print(
                                f"连接错误 (尝试 {attempt + 1}/{max_retries}): {e}",
                                file=sys.stderr,
                            )
                            print(f"{wait_time}秒后重试...", file=sys.stderr)
                            time.sleep(wait_time)
                            continue
                    else:
                        raise
                except Exception:
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
    return os.path.basename(path).lower().endswith(".summary.md")


def _is_keywords_file(path: str) -> bool:
    return os.path.basename(path).lower().endswith(".keywords.json")


def _keywords_path_for(md_path: str) -> str:
    base = os.path.basename(md_path)
    stem = base[:-3] if base.lower().endswith(".md") else base
    return os.path.join(os.path.dirname(md_path), f"{stem}.keywords.json")


def _should_skip(source_path: str, target_path: str, *, force: bool) -> bool:
    if force:
        return False
    if not os.path.exists(target_path):
        return False
    return os.path.getmtime(target_path) >= os.path.getmtime(source_path)


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


def _strip_code_blocks(md_text: str) -> str:
    return re.sub(r"```[\s\S]*?```", "", md_text or "")


def _strip_tables(md_text: str) -> str:
    lines: list[str] = []
    for line in (md_text or "").splitlines():
        s = line.strip()
        if not s:
            lines.append(line)
            continue
        if s.startswith("|") or s.endswith("|") or s.count("|") >= 2:
            continue
        if re.match(r"^\s*:?-{3,}:?\s*$", s):
            lines.append(line)
            continue
        lines.append(line)
    return "\n".join(lines)


def _cjk_char_count(text: str) -> int:
    count = 0
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            count += 1
    return count


def _compute_counts(md_text: str) -> tuple[int, int, str]:
    cleaned = _strip_tables(_strip_code_blocks(md_text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    total_chars = len(cleaned)
    latin_words = re.findall(r"[A-Za-z0-9_]+", cleaned)
    total_words = len(latin_words) + _cjk_char_count(cleaned)
    return total_chars, total_words, cleaned


def _frequency(text: str, word: str) -> int:
    w = str(word or "").strip()
    if not w:
        return 0
    return text.count(w)


def _extract_json_text(s: str) -> str:
    t = (s or "").strip()
    if not t:
        raise ValueError("模型未返回内容")
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, flags=re.IGNORECASE)
    if fenced:
        t = fenced.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        raise ValueError("未在模型输出中找到JSON对象")
    return m.group(0).strip()


def _normalize_output(obj: Any, *, total_chars: int, total_words: int, cleaned_text: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("JSON根对象必须是对象")
    meta = obj.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        obj["meta"] = meta

    keywords = obj.get("keywords")
    if not isinstance(keywords, list):
        keywords = []
        obj["keywords"] = keywords

    now = datetime.now(timezone.utc).isoformat()
    meta["total_chars"] = int(total_chars)
    meta["total_words"] = int(total_words)
    meta["analysis_time"] = str(meta.get("analysis_time") or now)
    meta["keywords_count"] = int(len(keywords))

    normalized_keywords: list[dict[str, Any]] = []
    for idx, item in enumerate(keywords, start=1):
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", "")).strip()
        if not word:
            continue
        item["rank"] = int(idx)
        item["word"] = word
        item["frequency"] = int(_frequency(cleaned_text, word))
        if "significance" not in item:
            item["significance"] = ""
        if "category" not in item:
            item["category"] = ""
        normalized_keywords.append(item)
    obj["keywords"] = normalized_keywords
    meta["keywords_count"] = int(len(normalized_keywords))

    clusters = obj.get("clusters")
    if not isinstance(clusters, dict):
        obj["clusters"] = {}
    return obj


@dataclass(frozen=True)
class AnthropicClient:
    base_url: str
    api_key: str
    timeout: float = 120.0

    @retry_on_connection_error(max_retries=3, delay=2)
    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        url = _join_api(self.base_url, "/v1/messages")
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
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
                http2=False,
            ) as client:
                resp = client.post(url, headers=headers, json=body)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 401:
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
        raise ValueError("未从模型响应中解析到文本")


@dataclass(frozen=True)
class OpenAIChatClient:
    base_url: str
    api_key: str
    timeout: float = 120.0

    @retry_on_connection_error(max_retries=3, delay=2)
    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        url = _join_api(self.base_url, "/v1/chat/completions")
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.api_key}"}
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5),
            http2=False,
        ) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()

        payload = resp.json()
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        raise ValueError("未从模型响应中解析到文本")


@dataclass(frozen=True)
class OpenVikingClient:
    base_url: str
    api_key: str
    timeout: float = 120.0

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


def _complete_with_fallback(
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    provider: str,
    system: str,
    user: str,
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
            print(f"尝试使用 {kind} 提供商进行关键词分析...", file=sys.stderr)
            if kind == "openai":
                return OpenAIChatClient(base_url=base_url, api_key=api_key).complete(
                    system=system,
                    user=user,
                    model=model,
                    max_tokens=max_tokens,
                )
            if kind == "anthropic":
                return AnthropicClient(base_url=base_url, api_key=api_key).complete(
                    system=system,
                    user=user,
                    model=model,
                    max_tokens=max_tokens,
                )
            client = OpenVikingClient(base_url=base_url, api_key=api_key)
            session_id = client.create_session()
            try:
                combined = f"{system}\n\n---\n\n{user}"
                client.add_message(session_id, role="user", content=combined)
                deadline = time.monotonic() + 240.0
                while True:
                    state = client.get_session(session_id)
                    msg = _extract_assistant_text(state)
                    if msg:
                        return msg
                    if time.monotonic() >= deadline:
                        raise TimeoutError("等待 OpenViking 关键词分析超时")
                    time.sleep(0.8)
            finally:
                try:
                    client.delete_session(session_id)
                except Exception as e:
                    print(f"删除会话失败: {e}", file=sys.stderr)
        except Exception as exc:
            print(f"{kind} 关键词分析失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            last_error = exc
            continue
    assert last_error is not None
    raise last_error


def analyze_md_to_keywords_json(
    *,
    md_text: str,
    base_url: str,
    api_key: str,
    model: str,
    provider: str,
    max_output_tokens: int,
    max_input_chars: int,
) -> dict[str, Any]:
    total_chars, total_words, cleaned = _compute_counts(md_text)
    prompt_text = _build_input_text(md_text, max_chars=int(max_input_chars))
    user = f"请分析以下 Markdown 文档：\n\n{prompt_text}"
    raw = _complete_with_fallback(
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=int(max_output_tokens),
        provider=provider,
        system=KEYWORDS_SYSTEM_PROMPT,
        user=user,
    )
    json_text = _extract_json_text(raw)
    obj = json.loads(json_text)
    return _normalize_output(obj, total_chars=total_chars, total_words=total_words, cleaned_text=cleaned)


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
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    args = parser.parse_args()

    api_key = (
        str(os.getenv("OPENVIKING_LLM_API_KEY", "")).strip()
        or str(os.getenv("OPENVIKING_API_KEY", "")).strip()
        or str(os.getenv("OPENAI_API_KEY", "")).strip()
    )
    if not api_key:
        print(
            "缺少环境变量 OPENVIKING_LLM_API_KEY / OPENVIKING_API_KEY / OPENAI_API_KEY",
            file=sys.stderr,
        )
        return 2
    if api_key.lower().startswith("bearer "):
        api_key = api_key.strip()

    output_dir = str(args.output_dir or "").strip() or "output"
    if not os.path.isdir(output_dir):
        print(f"目录不存在: {output_dir}", file=sys.stderr)
        return 2

    md_files = _iter_md_files(output_dir)
    if not md_files:
        print("output 目录下未找到需要分析的 .md 文件", file=sys.stderr)
        return 0

    written = 0
    for md_path in md_files:
        if _is_keywords_file(md_path):
            continue
        out_path = _keywords_path_for(md_path)
        if _should_skip(md_path, out_path, force=bool(args.force)):
            print(f"跳过已存在的关键词文件: {os.path.basename(out_path)}", file=sys.stderr)
            continue

        print(f"处理文件: {os.path.basename(md_path)}", file=sys.stderr)
        md_text = _read_text(md_path)
        try:
            obj = analyze_md_to_keywords_json(
                md_text=md_text,
                base_url=str(args.base_url),
                api_key=api_key,
                model=str(args.model),
                provider=str(args.provider),
                max_output_tokens=int(args.max_output_tokens),
                max_input_chars=int(args.max_input_chars),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                print(
                    "401 Unauthorized：当前 API Key 对该服务无效，或该服务需要不同的鉴权方式/Key",
                    file=sys.stderr,
                )
                return 2
            raise

        _write_text(out_path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        written += 1
        print(f"已生成关键词文件: {os.path.abspath(out_path)}")
        time.sleep(max(0.0, float(args.sleep_seconds)))

    if written == 0:
        print("无需要更新的关键词文件（可用 --force 强制重算）", file=sys.stderr)
    else:
        print(f"成功生成 {written} 个关键词文件", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
