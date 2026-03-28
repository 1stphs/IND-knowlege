import os
import httpx
import json
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("FOXUAI_BASE_URL")
AUTH_TOKEN = os.getenv("FOXUAI_AUTHORIZATION")

def list_fields(collection_name):
    # NocoBase 字段列表接口通常是这种格式
    url = f"{BASE_URL}/{collection_name}:fields"
    # 或者尝试这个
    # url = f"{BASE_URL}/collections/{collection_name}/fields:list"
    headers = {"Authorization": AUTH_TOKEN}
    response = httpx.get(url, headers=headers)
    try:
        return response.json()
    except Exception as e:
        print(f"Failed to decode JSON for {collection_name}: {e}")
        print(f"Response text: {response.text[:500]}")
        return None

if __name__ == "__main__":
    print(f"Listing fields for ind_knowledge_files...")
    files_fields = list_fields("ind_knowledge_files")
    with open("fields_files.json", "w", encoding="utf-8") as f:
        json.dump(files_fields, f, indent=2, ensure_ascii=False)
    
    print(f"Listing fields for ind_knowledge...")
    knowledge_fields = list_fields("ind_knowledge")
    with open("fields_knowledge.json", "w", encoding="utf-8") as f:
        json.dump(knowledge_fields, f, indent=2, ensure_ascii=False)
    
    print("Done. Saved to fields_files.json and fields_knowledge.json")
