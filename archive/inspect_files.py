import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.foxuai_client import NocoBaseClient

def inspect_files():
    load_dotenv()
    client = NocoBaseClient()
    
    # 根据刚才查出的 id: 3552550
    k_id = 3552550
    print(f"--- 正在获取 ID 为 {k_id} 的关联文件 ---")
    files_data = client.list_records(f"ind_knowledge/{k_id}/ind_knowledge_files", params={"pageSize": 1})
    
    if files_data and "data" in files_data and len(files_data["data"]) > 0:
        first_file_record = files_data["data"][0]
        print("\n[文件记录详情]:")
        # 递归展示所有非 null 的字段，方便查看具体结构
        clean_record = {k: v for k, v in first_file_record.items() if v is not None}
        print(json.dumps(clean_record, indent=2, ensure_ascii=False))
        
        # 重点看有没有文件路径或 URL
        if "file" in first_file_record:
            print("\n发现 'file' 字段:")
            print(json.dumps(first_file_record["file"], indent=2, ensure_ascii=False))
    else:
        print("\n未找到任何关联文件记录。")

if __name__ == "__main__":
    inspect_files()
