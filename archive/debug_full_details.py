import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.foxuai_client import NocoBaseClient

def inspect_full_details():
    load_dotenv()
    client = NocoBaseClient()
    
    # 1. 获取知识库条目，尝试追加关联
    print("--- 正在调用 ind_knowledge:list (带 appends=ind_knowledge_files) ---")
    data = client.list_records("ind_knowledge", params={
        "pageSize": 1,
        "appends": ["ind_knowledge_files"]
    })
    
    if data and "data" in data and len(data["data"]) > 0:
        item = data["data"][0]
        print("\n[ind_knowledge 完整结构]:")
        # 移除大量 null 字段以保持清晰
        print(json.dumps({k: v for k, v in item.items() if v is not None}, indent=2, ensure_ascii=False))
        
        # 2. 深入查看文件记录，强制追加附件字段 'file'
        k_id = item.get("id")
        print(f"\n--- 正在调用 ind_knowledge_files:list (带 appends=file) for ID: {k_id} ---")
        files_path = f"ind_knowledge/{k_id}/ind_knowledge_files"
        files_data = client.list_records(files_path, params={
            "pageSize": 1,
            "appends": ["file"]
        })
        
        if files_data and "data" in files_data and len(files_data["data"]) > 0:
            file_record = files_data["data"][0]
            print("\n[ind_knowledge_files 完整结构]:")
            print(json.dumps({k: v for k, v in file_record.items() if v is not None}, indent=2, ensure_ascii=False))
        else:
            print("\n未找到带附件的文件记录。")
    else:
        print("\n未获取到数据。")

if __name__ == "__main__":
    inspect_full_details()
