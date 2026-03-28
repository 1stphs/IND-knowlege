import os
import sys
import json
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.foxuai_client import NocoBaseClient

def verify_data():
    client = NocoBaseClient()
    # 获取第一个条目
    print("--- 正在获取 ind_knowledge_files 的最新数据 ---")
    data = client.list_records("ind_knowledge_files", params={"pageSize": 5, "sort": "-updatedAt"})
    
    if data and "data" in data:
        for idx, row in enumerate(data["data"]):
            print(f"\n[记录 {idx+1}] ID: {row.get('id')}")
            print(f"文件名 (field_name): {row.get('field_name')}")
            print(f"摘要 (summary): {repr(row.get('summary'))[:100]}...")
            print(f"关键词 (keywords): {row.get('keywords')}")
            print(f"解析内容 (extracted_content): {repr(row.get('extracted_content'))[:100]}...")
    else:
        print("未获取到数据。")

if __name__ == "__main__":
    verify_data()
