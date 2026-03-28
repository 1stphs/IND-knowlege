import pickle
import os

db_file = r"d:\益诺思\IND\IND-knowlege\rag_backend\simple_db\db.pkl"
if os.path.exists(db_file):
    with open(db_file, "rb") as f:
        data = pickle.load(f)
        metas = data.get("metadatas", [])
        sources = set(m.get("source") for m in metas)
        print(f"Total chunks: {len(metas)}")
        print(f"Total unique sources: {len(sources)}")
        print(f"Sources: {list(sources)[:10]}...")
else:
    print("DB file not found")
