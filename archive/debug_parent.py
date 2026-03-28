import os
import httpx
import json
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("FOXUAI_BASE_URL")
AUTH_TOKEN = os.getenv("FOXUAI_AUTHORIZATION")

def get_record(resource, pk):
    url = f"{BASE_URL}/{resource}:get?filterByTk={pk}"
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    response = httpx.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Error getting record {pk}: {response.status_code} {response.text}")
        return None
    return response.json().get('data', {})

if __name__ == "__main__":
    # Parent record ID from previous child record debug
    parent_id = "355252859633664"
    print(f"Fetching parent record {parent_id}...")
    parent_data = get_record("ind_knowledge", parent_id)
    if parent_data:
        # Avoid printing full ind_knowledge_files (too big)
        files = parent_data.pop("ind_knowledge_files", [])
        print(f"Parent keys: {sorted(parent_data.keys())}")
        print(f"Record JSON: {json.dumps(parent_data, indent=2, ensure_ascii=False)}")
        print(f"Number of attached files: {len(files)}")
    else:
        print("Failed to get parent record.")
