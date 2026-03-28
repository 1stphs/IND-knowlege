import os
import sys
import json
import logging
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.foxuai_client import NocoBaseClient

def dump_full_schema(collection_name):
    client = NocoBaseClient()
    url = f"{client.base_url}/collections:get?filter[name]={collection_name}&appends=fields"
    headers = client._get_headers()
    
    import httpx
    with httpx.Client(timeout=30.0) as h_client:
        response = h_client.get(url, headers=headers)
        response.raise_for_status()
        filename = f"full_schema_{collection_name}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(response.json(), f, indent=2, ensure_ascii=False)
        print(f"Dumped full schema to {filename}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        collection = "ind_knowledge_files"
    else:
        collection = sys.argv[1]
    dump_full_schema(collection)
