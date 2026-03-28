import os
import sys
from lib.foxuai_client import NocoBaseClient

def debug_matching():
    client = NocoBaseClient()
    with open("debug_output.txt", "w", encoding="utf-8") as out:
        out.write("--- FoxUAI Records ---\n")
        resp = client.list_records("ind_knowledge", params={"pageSize": 10})
        data = resp.get("data", [])
        for row in data:
            out.write(f"\nID: {row.get('id')} -> title: {row.get('title')}, field_name: {row.get('field_name')}\n")
            k_id = row.get("id")
            try:
                f_resp = client.list_records(f"ind_knowledge/{k_id}/ind_knowledge_files", params={"appends": ["file"]})
                f_data = f_resp.get("data", [])
                if f_data:
                    import json
                    out.write("\nFirst File Record JSON:\n")
                    out.write(json.dumps(f_data[0], indent=2, ensure_ascii=False) + "\n")
                for f_item in f_data:
                    attachments = f_item.get("file")
                    if not attachments: continue
                    if isinstance(attachments, dict): attachments = [attachments]
                    for att in attachments:
                        out.write(f"   -> File ID: {f_item.get('id')}, Attachment title: {att.get('title')}\n")
            except Exception as e:
                out.write("   -> Failed to get files\n")

        out.write("\n--- Local Files (first 10) ---\n")
        mineru_dir = "output/mineru_markdowns"
        if os.path.exists(mineru_dir):
            files = [f for f in os.listdir(mineru_dir) if f.endswith(".md") and not f.endswith(".summary.md")]
            for f in files[:10]:
                out.write(f"{f}\n")
        else:
            out.write(f"Directory not found {mineru_dir}\n")
        
if __name__ == "__main__":
    debug_matching()
