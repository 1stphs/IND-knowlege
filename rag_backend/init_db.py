import os
from dotenv import load_dotenv

try:
    from service.rag_service import RagService
except ModuleNotFoundError:
    from rag_backend.service.rag_service import RagService

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

def init_db():
    print("Initializing hybrid retrieval indexes with existing markdowns...")
    service = RagService()
    md_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output", "mineru_markdowns"))
    if not os.path.exists(md_dir):
        print(f"Warning: Directory {md_dir} does not exist. No documents indexed.")
        return
        
    try:
        result = service.index_markdown_directory(md_dir)
        print(
            "Successfully indexed "
            f"{result['indexed_documents']} documents / {result['indexed_chunks']} chunks."
        )
    except Exception as e:
        print(f"Failed to index documents: {e}")

if __name__ == "__main__":
    init_db()
