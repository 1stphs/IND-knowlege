import pickle
import os

db_file = r"d:\益诺思\IND\IND-knowlege\rag_backend\simple_db\db.pkl"
try:
    with open(db_file, "rb") as f:
        data = pickle.load(f)
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        print(f"File: {db_file}")
        print(f"Docs count: {len(docs)}")
        print(f"Metas count: {len(metas)}")
        if metas:
            print(f"Sample source: {metas[0].get('source')}")
except Exception as e:
    print(f"Error: {e}")
