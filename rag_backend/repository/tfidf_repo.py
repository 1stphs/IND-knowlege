import os
import pickle

import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class TfidfRepository:
    def __init__(self, db_dir: str = "./simple_db"):
        self.db_dir = db_dir
        self.db_file = os.path.join(db_dir, "db.pkl")
        os.makedirs(db_dir, exist_ok=True)

        self.records: dict[str, dict] = {}
        self.documents: list[str] = []
        self.metadatas: list[dict] = []
        self.ids: list[str] = []
        self.vectorizer = TfidfVectorizer(tokenizer=jieba.lcut, token_pattern=None)
        self.tfidf_matrix = None

        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "rb") as file_obj:
                    data = pickle.load(file_obj)
                    self.records = data.get("records", {})
                    if not self.records and data.get("documents"):
                        for index, document in enumerate(data.get("documents", [])):
                            metadata = data.get("metadatas", [])[index]
                            record_id = metadata.get("chunk_id") or f"legacy_{index}"
                            self.records[record_id] = {"document": document, "metadata": metadata}
                    self._rebuild_matrix()
            except Exception as exc:
                print(f"Failed to load DB: {exc}")

    def _persist(self):
        with open(self.db_file, "wb") as file_obj:
            pickle.dump({"records": self.records}, file_obj)

    def _rebuild_matrix(self):
        self.ids = list(self.records.keys())
        self.documents = [self.records[record_id]["document"] for record_id in self.ids]
        self.metadatas = [self.records[record_id]["metadata"] for record_id in self.ids]
        if self.documents:
            self.tfidf_matrix = self.vectorizer.fit_transform(self.documents)
        else:
            self.tfidf_matrix = None

    def upsert_documents(self, ids: list[str], documents: list[str], metadatas: list[dict]):
        for record_id, document, metadata in zip(ids, documents, metadatas):
            self.records[record_id] = {"document": document, "metadata": metadata}
        self._rebuild_matrix()
        self._persist()

    def add_documents(self, ids: list[str], documents: list[str], metadatas: list[dict]):
        self.upsert_documents(ids, documents, metadatas)

    def delete_document(self, document_id: str):
        removable = [
            record_id
            for record_id, payload in self.records.items()
            if payload["metadata"].get("document_id") == document_id
        ]
        for record_id in removable:
            del self.records[record_id]
        if removable:
            self._rebuild_matrix()
            self._persist()

    def search(self, query: str, top_k: int = 3, source_mds: list[str] | None = None):
        if self.tfidf_matrix is None or not self.documents:
            return []

        query_vec = self.vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
        sorted_indices = np.argsort(similarities)[::-1]
        allowed_sources = set(source_mds or [])

        results = []
        for index in sorted_indices:
            score = float(similarities[index])
            if score <= 0.01:
                continue
            if allowed_sources and self.metadatas[index].get("source_md") not in allowed_sources:
                continue
            results.append(
                {
                    "id": self.ids[index],
                    "document": self.documents[index],
                    "metadata": self.metadatas[index],
                    "score": score,
                }
            )
            if len(results) >= top_k:
                break
        return results
