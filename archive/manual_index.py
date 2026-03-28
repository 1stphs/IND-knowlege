import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "rag_backend"))

from rag_backend.repository.tfidf_repo import TfidfRepository
from rag_backend.service.rag_service import RagService

def manual_index():
    db_path = os.path.join(os.getcwd(), "rag_backend", "simple_db")
    db_file = os.path.join(db_path, "db.pkl")
    
    if os.path.exists(db_file):
        print(f"Deleting corrupt DB: {db_file}")
        os.remove(db_file)
    
    service = RagService()
    # Path to markdown files
    md_dir = os.path.join(os.getcwd(), "output", "mineru_markdowns")
    print(f"Indexing from: {md_dir}")
    
    count = service.index_markdown_directory(md_dir)
    print(f"Successfully indexed {count} chunks.")

if __name__ == "__main__":
    manual_index()
