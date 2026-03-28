import os
import sys
import json
import logging
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.foxuai_client import NocoBaseClient

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_schema(collection_name):
    client = NocoBaseClient()
    headers = client._get_headers()
    import httpx
    
    # Try multiple endpoints
    endpoints = [
        f"{client.base_url}/collections:get?filter[name]={collection_name}&appends=fields",
        f"{client.base_url}/fields:list?filter[collectionName]={collection_name}",
        f"{client.base_url}/{collection_name}:fields"
    ]
    
    for url in endpoints:
        try:
            print(f"Trying URL: {url}")
            with httpx.Client(timeout=30.0) as h_client:
                response = h_client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json().get('data', [])
                    if isinstance(data, dict) and 'fields' in data:
                        return data['fields']
                    elif isinstance(data, list):
                        return data
        except Exception as e:
            print(f"Failed {url}: {e}")
    return []

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_schema.py <collection_name>")
        # Default to the one we need most
        collection = "ind_knowledge_files"
    else:
        collection = sys.argv[1]
        
    print(f"Fetching fields for {collection}...")
    fields = get_schema(collection)
    
    # 提取关键信息：name, uiSchema.title
    field_info = []
    for f in fields:
        info = {
            "name": f.get("name"),
            "title": f.get("uiSchema", {}).get("title"),
            "type": f.get("type")
        }
        field_info.append(info)
    
    with open("schema_summary.json", "w", encoding="utf-8") as f:
        json.dump(field_info, f, indent=2, ensure_ascii=False)
    
    print("Done. Saved to schema_summary.json")
    for info in field_info:
        print(f"  - {info['name']} ({info['title']}): {info['type']}")
