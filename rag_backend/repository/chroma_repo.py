import os

import chromadb
from chromadb.utils import embedding_functions


class ChromaRepository:
    def __init__(self, db_dir: str = "./chroma_db"):
        self.client = chromadb.PersistentClient(path=db_dir)
        self.available = True

        api_key, api_base, embedding_model = self._resolve_embedding_config()
        self.embedding_config = {
            "has_api_key": bool(api_key),
            "api_base": api_base,
            "model": embedding_model,
        }

        if api_key:
            self.emb_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=api_key,
                api_base=api_base,
                model_name=embedding_model,
            )
        else:
            self.emb_fn = embedding_functions.DefaultEmbeddingFunction()
            print(
                "Embedding API key missing; Chroma will try local ONNX embedding. "
                "Set OPENAI_EMBEDDING_API_KEY to avoid local model download."
            )

        self.collection = self._get_or_create_collection_with_compat()

    def _resolve_embedding_config(self):
        api_key = (
            os.getenv("OPENAI_EMBEDDING_API_KEY", "").strip()
            or os.getenv("OPENVIKING_EMBEDDING_API_KEY", "").strip()
            or os.getenv("OPENVIKING_LLM_API_KEY", "").strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
            or os.getenv("API_KEY", "").strip()
        )
        api_base = (
            os.getenv("OPENAI_EMBEDDING_BASE_URL", "").strip()
            or os.getenv("OPENVIKING_EMBEDDING_API_BASE", "").strip()
            or os.getenv("OPENVIKING_LLM_API_BASE", "").strip()
            or os.getenv("OPENAI_BASE_URL", "").strip()
            or os.getenv("BASE_URL", "").strip()
            or "https://api.openai.com/v1"
        )
        embedding_model = (
            os.getenv("OPENAI_EMBEDDING_MODEL", "").strip()
            or os.getenv("OPENVIKING_EMBEDDING_MODEL", "").strip()
            or "text-embedding-3-small"
        )
        return api_key, api_base, embedding_model

    def _get_or_create_collection_with_compat(self):
        collection_name = "ind_knowledge"
        try:
            return self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.emb_fn,
                metadata={"hnsw:space": "cosine"},
            )
        except ValueError as exc:
            if "Embedding function conflict" not in str(exc):
                raise
            print(
                "Detected embedding function conflict in existing Chroma collection. "
                "Recreating collection and requiring re-index."
            )
            self.client.delete_collection(collection_name)
            return self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.emb_fn,
                metadata={"hnsw:space": "cosine"},
            )

    def upsert_documents(self, ids: list[str], documents: list[str], metadatas: list[dict]):
        if not ids:
            return
        batch_size = 100
        try:
            for start in range(0, len(ids), batch_size):
                end = start + batch_size
                self.collection.upsert(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )
        except Exception as exc:
            self.available = False
            print(f"Chroma upsert unavailable, falling back to lexical retrieval only: {exc}")

    def add_documents(self, ids: list[str], documents: list[str], metadatas: list[dict]):
        self.upsert_documents(ids, documents, metadatas)

    def delete_document(self, document_id: str):
        try:
            existing = self.collection.get(where={"document_id": document_id})
            delete_ids = existing.get("ids", [])
            if delete_ids:
                self.collection.delete(ids=delete_ids)
        except Exception:
            self.available = False

    def search(self, query: str, top_k: int = 3, source_mds: list[str] | None = None):
        if not self.available:
            return []
        try:
            allowed_sources = [item for item in (source_mds or []) if item]
            query_kwargs = {
                "query_texts": [query],
                "n_results": max(top_k, top_k * 8) if allowed_sources else top_k,
            }
            if len(allowed_sources) == 1:
                query_kwargs["where"] = {"source_md": allowed_sources[0]}
            results = self.collection.query(**query_kwargs)
        except Exception as exc:
            self.available = False
            print(f"Chroma search unavailable, falling back to lexical retrieval only: {exc}")
            return []
        if not results.get("ids"):
            return []

        ids = results["ids"][0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        normalized = []
        allowed_source_set = set(source_mds or [])
        for record_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            if allowed_source_set and metadata.get("source_md") not in allowed_source_set:
                continue
            similarity = max(0.0, 1.0 - float(distance))
            normalized.append(
                {
                    "id": record_id,
                    "document": document,
                    "metadata": metadata,
                    "score": similarity,
                }
            )
            if len(normalized) >= top_k:
                break
        return normalized
