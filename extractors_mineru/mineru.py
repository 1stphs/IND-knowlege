"""MinerU HTTP client wrappers."""

from __future__ import annotations

import io
import logging
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from dotenv import load_dotenv

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_DOTENV_PATH, override=True)

logger = logging.getLogger(__name__)

DEFAULT_MINERU_BASE_URL = "https://mineru.net/api/v4"
CREATE_TASK_PATH = "/extract/task"
_TERMINAL_FAILED_STATUS = {
    "failed",
    "failure",
    "error",
    "canceled",
    "cancelled",
}


def _env_proxy_configured() -> bool:
    return any(
        str(os.getenv(name, "")).strip()
        for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
    )


def _mineru_trust_env() -> bool:
    raw = str(os.getenv("MINERU_TRUST_ENV", "1") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def _should_fallback_without_proxy(exc: Exception, *, trust_env: bool) -> bool:
    return trust_env and _env_proxy_configured() and isinstance(exc, httpx.ConnectError)


def _request_via_client(
    method_value: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float,
    trust_env: bool,
) -> httpx.Response:
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=trust_env) as client:
        return client.request(
            method=method_value,
            url=url,
            headers=headers,
            json=json_body,
        )


def get_mineru_base_url() -> str:
    """Return MinerU base URL from env with sane default."""

    return os.getenv("MINERU_BASE_URL", DEFAULT_MINERU_BASE_URL).rstrip("/")


def get_mineru_token() -> str:
    """Return MinerU token from env (supports MINERU_API_TOKEN / MINERU_API_KEY)."""

    raw = str(os.getenv("MINERU_API_TOKEN", "")).strip() or str(os.getenv("MINERU_API_KEY", "")).strip()
    if not raw:
        raise RuntimeError("未配置 MINERU_API_TOKEN 或 MINERU_API_KEY")
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def get_mineru_auth_header() -> str:
    """Build Authorization header value."""

    return f"Bearer {get_mineru_token()}"


def get_mineru_default_model_version() -> str:
    """Return default MinerU model version."""

    return str(os.getenv("MINERU_MODEL_VERSION", "vlm")).strip() or "vlm"


def _build_url(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip()
    if not raw:
        raise ValueError("path_or_url 不能为空")
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    base_url = get_mineru_base_url()
    if raw.startswith("/"):
        return f"{base_url}{raw}"
    return f"{base_url}/{raw}"


def _request_json(
    method: str,
    path_or_url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    method_value = str(method or "").strip().upper()
    if not method_value:
        raise ValueError("method 不能为空")

    url = _build_url(path_or_url)
    headers = {
        "Content-Type": "application/json",
        "Authorization": get_mineru_auth_header(),
    }
    trust_env = _mineru_trust_env()
    try:
        resp = _request_via_client(
            method_value,
            url,
            headers=headers,
            json_body=json_body,
            timeout=timeout,
            trust_env=trust_env,
        )
    except Exception as exc:
        if not _should_fallback_without_proxy(exc, trust_env=trust_env):
            raise
        logger.warning(
            "[MinerU] request failed via proxy env, retrying direct connection: method=%s url=%s error=%s",
            method_value,
            url,
            exc,
        )
        resp = _request_via_client(
            method_value,
            url,
            headers=headers,
            json_body=json_body,
            timeout=timeout,
            trust_env=False,
        )

    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("MinerU 返回结果不是 JSON 对象")
    return payload


def _request_bytes(path_or_url: str, *, timeout: float = 60.0) -> bytes:
    url = _build_url(path_or_url)
    trust_env = _mineru_trust_env()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=trust_env) as client:
            resp = client.get(url)
    except Exception as exc:
        if not _should_fallback_without_proxy(exc, trust_env=trust_env):
            raise
        logger.warning(
            "[MinerU] download failed via proxy env, retrying direct connection: url=%s error=%s",
            url,
            exc,
        )
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            resp = client.get(url)

    resp.raise_for_status()
    return resp.content


def submit_extract_task(
    file_url: str,
    *,
    model_version: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Submit an extraction task to MinerU."""

    normalized_url = str(file_url or "").strip()
    if not normalized_url:
        raise ValueError("file_url 不能为空")

    normalized_model = str(model_version or get_mineru_default_model_version()).strip()
    if not normalized_model:
        raise ValueError("model_version 不能为空")

    payload: dict[str, Any] = {
        "url": normalized_url,
        "model_version": normalized_model,
    }
    return _request_json(
        "POST",
        CREATE_TASK_PATH,
        json_body=payload,
        timeout=timeout,
    )


def create_extract_task(
    source_url: str,
    *,
    model_version: str = "vlm",
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Backward-compatible alias of submit_extract_task."""

    return submit_extract_task(source_url, model_version=model_version, timeout=timeout)


def get_extract_task(task_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Query MinerU task detail."""

    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        raise ValueError("task_id 不能为空")
    return _request_json(
        "GET",
        f"{CREATE_TASK_PATH}/{normalized_task_id}",
        timeout=timeout,
    )


def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("MinerU 响应缺少 data 对象")
    return data


def _extract_task_id(create_payload: dict[str, Any]) -> str:
    data = _extract_data(create_payload)
    for key in ("task_id", "id", "taskId"):
        value = data.get(key)
        if isinstance(value, (str, int)):
            normalized = str(value).strip()
            if normalized:
                return normalized
    raise ValueError("创建任务成功但未返回 task_id")


def wait_task_full_zip_url(
    task_id: str,
    *,
    poll_interval_seconds: float = 2.0,
    max_wait_seconds: float = 300.0,
    timeout_per_poll: float = 20.0,
) -> str:
    """Poll task endpoint until data.full_zip_url appears."""

    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds 必须大于 0")
    if max_wait_seconds <= 0:
        raise ValueError("max_wait_seconds 必须大于 0")

    deadline = time.monotonic() + max_wait_seconds
    last_poll_error = ""

    while True:
        try:
            payload = get_extract_task(task_id, timeout=timeout_per_poll)
        except httpx.HTTPError as exc:
            last_poll_error = str(exc)
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"等待 full_zip_url 超时(task_id={task_id}, last_error={last_poll_error})"
                ) from exc
            logger.warning(
                "[MinerU] poll task failed, will retry same task: task_id=%s error=%s",
                task_id,
                exc,
            )
            time.sleep(poll_interval_seconds)
            continue

        data = _extract_data(payload)
        last_poll_error = ""

        full_zip_url = str(data.get("full_zip_url", "")).strip()
        if full_zip_url:
            return full_zip_url

        status = str(
            data.get("status")
            or data.get("state")
            or data.get("task_status")
            or ""
        ).strip().lower()
        if status in _TERMINAL_FAILED_STATUS:
            raise RuntimeError(f"MinerU 任务失败(task_id={task_id}, status={status})")

        if time.monotonic() >= deadline:
            suffix = f", last_error={last_poll_error}" if last_poll_error else ""
            raise TimeoutError(f"等待 full_zip_url 超时(task_id={task_id}{suffix})")

        time.sleep(poll_interval_seconds)


def _extract_full_md_from_zip_bytes(zip_bytes: bytes) -> str:
    if not zip_bytes:
        raise ValueError("zip_bytes 不能为空")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_obj:
        names = zip_obj.namelist()
        if not names:
            raise ValueError("zip 内容为空")

        candidate_names = [
            name
            for name in names
            if name.lower() == "full.md" or name.lower().endswith("/full.md")
        ]
        if not candidate_names:
            raise ValueError("zip 中未找到 full.md")

        target = min(candidate_names, key=len)
        raw = zip_obj.read(target)

    if not raw:
        return ""

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8-sig", errors="replace")


def get_full_markdown_from_zip_url(zip_url: str, *, timeout: float = 60.0) -> str:
    """Download MinerU full zip and return content of full.md."""

    content = _request_bytes(zip_url, timeout=timeout)
    return _extract_full_md_from_zip_bytes(content)


def parse_url_to_full_markdown(
    source_url: str,
    *,
    model_version: str = "vlm",
    create_timeout: float = 20.0,
    timeout_per_poll: float = 20.0,
    poll_interval_seconds: float = 2.0,
    max_wait_seconds: float = 300.0,
    zip_timeout: float = 60.0,
) -> str:
    """
    High-level API:
    1) create task
    2) poll task until full_zip_url
    3) download zip and return full.md text
    """

    create_payload = create_extract_task(
        source_url=source_url,
        model_version=model_version,
        timeout=create_timeout,
    )
    task_id = _extract_task_id(create_payload)
    full_zip_url = wait_task_full_zip_url(
        task_id=task_id,
        poll_interval_seconds=poll_interval_seconds,
        max_wait_seconds=max_wait_seconds,
        timeout_per_poll=timeout_per_poll,
    )
    return get_full_markdown_from_zip_url(full_zip_url, timeout=zip_timeout)


def extract_markdown(
    file_url: str,
    *,
    model_version: str | None = None,
    interval: float = 3.0,
    timeout: float = 300.0,
) -> tuple[str, dict[str, Any]]:
    """
    Run MinerU extraction and return markdown + metadata.

    This path stays within mineru_client.
    """

    normalized_file_url = str(file_url or "").strip()
    if not normalized_file_url:
        raise ValueError("file_url 不能为空")

    normalized_model = str(model_version or get_mineru_default_model_version()).strip()
    if not normalized_model:
        normalized_model = get_mineru_default_model_version()

    poll_interval_seconds = max(0.2, float(interval))
    max_wait_seconds = max(1.0, float(timeout))
    timeout_per_poll = max(5.0, min(30.0, max_wait_seconds))
    zip_timeout = max(30.0, min(120.0, max_wait_seconds))

    create_payload = submit_extract_task(
        normalized_file_url,
        model_version=normalized_model,
        timeout=30.0,
    )
    task_id = _extract_task_id(create_payload)
    full_zip_url = wait_task_full_zip_url(
        task_id,
        poll_interval_seconds=poll_interval_seconds,
        max_wait_seconds=max_wait_seconds,
        timeout_per_poll=timeout_per_poll,
    )
    markdown = get_full_markdown_from_zip_url(full_zip_url, timeout=zip_timeout)
    metadata = {
        "task_id": task_id,
        "source": "full_zip_url",
        "download_url": full_zip_url,
    }
    return markdown, metadata


def _sanitize_filename(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "output"
    raw = raw.replace("\x00", "").strip()
    raw = re.sub(r"""[<>:"/\\|?*\r\n\t]+""", "_", raw)
    raw = re.sub(r"\s+", "_", raw).strip("._ ")
    return raw or "output"


def _guess_md_filename(file_url: str, metadata: dict[str, Any] | None = None) -> str:
    parsed = urlparse(str(file_url or "").strip())
    base = unquote(os.path.basename(parsed.path or "")).strip()
    if base:
        stem, ext = os.path.splitext(base)
        if stem:
            return f"{_sanitize_filename(stem)}.md"
    task_id = ""
    if isinstance(metadata, dict):
        task_id = str(metadata.get("task_id", "")).strip()
    if task_id:
        return f"{_sanitize_filename(task_id)}.md"
    return "output.md"


def save_markdown_to_output(
    markdown: str,
    *,
    output_dir: str = "output",
    filename: str | None = None,
) -> str:
    normalized_dir = str(output_dir or "").strip() or "output"
    os.makedirs(normalized_dir, exist_ok=True)
    target_name = _sanitize_filename(filename) if filename else "output.md"
    if not target_name.lower().endswith(".md"):
        target_name = f"{target_name}.md"
    target_path = os.path.join(normalized_dir, target_name)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(markdown or "")
    return os.path.abspath(target_path)


def extract_markdown_to_output(
    file_url: str,
    *,
    output_dir: str = "output",
    filename: str | None = None,
    model_version: str | None = None,
    interval: float = 3.0,
    timeout: float = 300.0,
) -> tuple[str, dict[str, Any]]:
    markdown, metadata = extract_markdown(
        file_url,
        model_version=model_version,
        interval=interval,
        timeout=timeout,
    )
    target_filename = filename or _guess_md_filename(file_url, metadata)
    output_path = save_markdown_to_output(
        markdown,
        output_dir=output_dir,
        filename=target_filename,
    )
    enriched = dict(metadata)
    enriched["output_path"] = output_path
    enriched["output_filename"] = os.path.basename(output_path)
    return output_path, enriched


def request_batch_upload_urls(
    file_names: list[str],
    *,
    model_version: str = "vlm",
    timeout: float = 30.0,
) -> tuple[str, list[str]]:
    if not file_names:
        raise ValueError("file_names 不能为空")
    files: list[dict[str, Any]] = [{"name": os.path.basename(n)} for n in file_names]
    payload = _request_json(
        "POST",
        "/file-urls/batch",
        json_body={"files": files, "model_version": model_version},
        timeout=timeout,
    )
    data = _extract_data(payload)
    batch_id = str(data.get("batch_id", "")).strip()
    urls = data.get("file_urls")
    if not batch_id:
        raise ValueError("未返回 batch_id")
    if not isinstance(urls, list) or not all(isinstance(u, str) and u.strip() for u in urls):
        raise ValueError("未返回 file_urls")
    if len(urls) != len(file_names):
        raise ValueError("file_urls 数量与文件数量不一致")
    return batch_id, [str(u).strip() for u in urls]


def upload_files_to_urls(
    file_paths: list[str],
    upload_urls: list[str],
    *,
    timeout: float = 300.0,
) -> None:
    if len(file_paths) != len(upload_urls):
        raise ValueError("file_paths 与 upload_urls 数量不一致")
    trust_env = _mineru_trust_env()
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=trust_env) as client:
        for file_path, upload_url in zip(file_paths, upload_urls, strict=True):
            if not os.path.isfile(file_path):
                raise FileNotFoundError(file_path)
            with open(file_path, "rb") as f:
                resp = client.put(upload_url, data=f)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"上传失败: file={file_path} status={resp.status_code}")


def get_batch_results(batch_id: str, *, timeout: float = 30.0) -> list[dict[str, Any]]:
    normalized_batch_id = str(batch_id or "").strip()
    if not normalized_batch_id:
        raise ValueError("batch_id 不能为空")
    payload = _request_json("GET", f"/extract-results/batch/{normalized_batch_id}", timeout=timeout)
    data = _extract_data(payload)
    results = data.get("extract_result") or data.get("extract_results") or data.get("results")
    if not isinstance(results, list):
        raise ValueError("响应缺少 extract_result 列表")
    normalized: list[dict[str, Any]] = []
    for item in results:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def poll_and_save_batch_results(
    batch_id: str,
    *,
    output_dir: str = "output",
    poll_interval_seconds: float = 3.0,
    max_wait_seconds: float = 1800.0,
    timeout_per_poll: float = 30.0,
    zip_timeout: float = 120.0,
) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    deadline = time.monotonic() + max_wait_seconds
    saved_paths: list[str] = []
    saved_by_name: set[str] = set()
    while True:
        results = get_batch_results(batch_id, timeout=timeout_per_poll)
        total = len(results)
        for item in results:
            file_name = str(item.get("file_name", "")).strip()
            if not file_name or file_name in saved_by_name:
                continue
            state = str(item.get("state", "")).strip().lower()
            if state == "done":
                full_zip_url = str(item.get("full_zip_url", "")).strip()
                if not full_zip_url:
                    continue
                md = get_full_markdown_from_zip_url(full_zip_url, timeout=zip_timeout)
                stem, _ = os.path.splitext(os.path.basename(file_name))
                target_name = f"{stem}.md"
                i = 1
                while os.path.exists(os.path.join(output_dir, target_name)):
                    i += 1
                    target_name = f"{stem}-{i}.md"
                path = save_markdown_to_output(md, output_dir=output_dir, filename=target_name)
                saved_paths.append(path)
                saved_by_name.add(file_name)
                continue
            if state in _TERMINAL_FAILED_STATUS:
                err_msg = str(item.get("err_msg", "")).strip()
                logger.error(f"解析失败: file_name={file_name} state={state} err_msg={err_msg}")
                # Increment saved_by_name to avoid re-processing this failed file in next loop iteration
                saved_by_name.add(file_name)
                continue
        if total > 0 and len(saved_by_name) >= total:
            return saved_paths
        if time.monotonic() >= deadline:
            remaining = [str(r.get("file_name", "")).strip() for r in results if str(r.get("file_name", "")).strip() not in saved_by_name]
            logger.error(f"等待批量解析超时 batch_id={batch_id}, remaining={remaining}")
            return saved_paths
        time.sleep(max(0.2, float(poll_interval_seconds)))
