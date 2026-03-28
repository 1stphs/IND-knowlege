import os
import sys
import json
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.foxuai_client import NocoBaseClient

def inspect_fields():
    client = NocoBaseClient()
    url = f"{client.base_url}/collections:get?filter[name]=ind_knowledge_files&appends=fields"
    headers = client._get_headers()
    
    import httpx
    with httpx.Client(timeout=30.0) as h_client:
        response = h_client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json().get('data', {})
        fields = data.get('fields', [])
        
        print(f"{'Key':<15} | {'Name':<20} | {'Title':<20} | {'Type':<10}")
        print("-" * 75)
        for f in fields:
            key = f.get('key')
            name = f.get('name')
            title = f.get('uiSchema', {}).get('title')
            f_type = f.get('type')
            print(f"{str(key):<15} | {str(name):<20} | {str(title):<20} | {str(f_type):<10}")

if __name__ == "__main__":
    inspect_fields()
