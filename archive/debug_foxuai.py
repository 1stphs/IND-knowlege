import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.foxuai_client import NocoBaseClient

def inspect_response():
    load_dotenv()
    client = NocoBaseClient()
    
    print("--- 正在调用 ind_knowledge:list ---")
    data = client.list_records("ind_knowledge", params={"pageSize": 1})
    
    if data and "data" in data and len(data["data"]) > 0:
        first_item = data["data"][0]
        print("\n[ind_knowledge 记录示例]:")
        print(json.dumps(first_item, indent=2, ensure_ascii=False))
        
        k_id = first_item.get("id")
        print(f"\n--- 正在获取关联文件 (ID: {k_id}) ---")
        files_data = client.list_records(f"ind_knowledge/{k_id}/ind_knowledge_files", params={"pageSize": 1})
        
        if files_data and "data" in files_data and len(files_data["data"]) > 0:
            print("\n[ind_knowledge_files 记录示例]:")
            print(json.dumps(files_data["data"][0], indent=2, ensure_ascii=False))
        else:
            print("\n未找到关联文件。")
    else:
        print("\n未获取到任何知识库记录。")

if __name__ == "__main__":
    inspect_response()
