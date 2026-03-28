import os
import httpx
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class NocoBaseClient:
    """
    NocoBase API 客户端，用于对接 FoxUAI 平台。
    支持 resource:action 模式调用。
    """
    
    def __init__(self, base_url: Optional[str] = None, auth: Optional[str] = None):
        load_dotenv()
        # 基础 URL 处理，确保以 /api 结尾且不带冗余斜杠
        raw_url = base_url or os.getenv("FOXUAI_BASE_URL", "https://www.foxuai.com")
        self.base_url = raw_url.rstrip("/") + "/api"
        self.auth = auth or os.getenv("FOXUAI_AUTHORIZATION")
        
        if not self.auth:
            logger.warning("FOXUAI_AUTHORIZATION 未配置，API 调用可能会失败。")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.auth if self.auth.startswith("Bearer ") else f"Bearer {self.auth}",
            "Content-Type": "application/json"
        }

    def request(self, method: str, path: str, params: Optional[Dict] = None, json: Optional[Dict] = None) -> Any:
        """底层请求方法"""
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = self._get_headers()
        
        with httpx.Client(timeout=30.0) as client:
            response = client.request(method, url, params=params, json=json, headers=headers)
            response.raise_for_status()
            return response.json()

    def list_records(self, resource: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        列表获取接口 (resource:list)
        """
        return self.request("GET", f"{resource}:list", params=params)

    def get_record(self, resource: str, id: Any, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        单条详情获取 (resource:get)
        """
        return self.request("GET", f"{resource}:get", params={"filterByTk": id, **(params or {})})

    def update_record(self, resource: str, id: Any, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        更新单条记录 (resource:update)
        使用 filterByTk 指定要更新的记录 ID，并通过 JSON payload 发送更新的数据
        """
        return self.request("POST", f"{resource}:update", params={"filterByTk": id}, json=data)

    def download_file(self, url: str, output_path: str):
        """下载文件到本地"""
        # 如果是相对路径，补全域名
        is_internal = False
        if url.startswith("/"):
            url = os.getenv("FOXUAI_BASE_URL", "https://www.foxuai.com").rstrip("/") + url
            is_internal = True
        elif url.startswith(self.base_url.replace("/api", "")):
            is_internal = True
            
        headers = self._get_headers() if is_internal else {}
            
        with httpx.Client() as client:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
        return output_path
