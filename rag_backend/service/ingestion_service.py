import hashlib
import json
import logging
import os
from collections import defaultdict

from neo4j import GraphDatabase

try:
    from repository.chroma_repo import ChromaRepository
    from repository.tfidf_repo import TfidfRepository
    from service.markdown_parser import MarkdownTreeParser
except ModuleNotFoundError:
    from rag_backend.repository.chroma_repo import ChromaRepository
    from rag_backend.repository.tfidf_repo import TfidfRepository
    from rag_backend.service.markdown_parser import MarkdownTreeParser

logger = logging.getLogger(__name__)


def _hash_file(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def _normalize_entity(raw_value):
    if isinstance(raw_value, dict):
        entity_id = raw_value.get("id") or raw_value.get("name") or str(raw_value)
        entity_type = raw_value.get("type") or raw_value.get("subclass") or "Entity"
    else:
        entity_id = str(raw_value or "").strip()
        entity_type = "Entity"
    return entity_id.strip(), entity_type.strip()


class IngestionService:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.chroma_repo = ChromaRepository(os.path.join(root_dir, "rag_backend", "chroma_db"))
        self.lexical_repo = TfidfRepository(os.path.join(root_dir, "rag_backend", "simple_db"))
        self.triples_path = os.path.join(root_dir, "ontology", "extracted_triples.json")
        self.manifest_path = os.path.join(root_dir, "rag_backend", "simple_db", "index_manifest.json")
        self.manifest = self._load_manifest()

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD")
        self.neo4j_driver = None
        if neo4j_password:
            try:
                self.neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
                self._ensure_graph_constraints()
            except Exception as exc:
                logger.warning("Neo4j unavailable during ingestion init: %s", exc)

    def _load_manifest(self):
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as file_obj:
                    return json.load(file_obj)
            except Exception:
                return {}
        return {}

    def _save_manifest(self):
        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as file_obj:
            json.dump(self.manifest, file_obj, ensure_ascii=False, indent=2)

    def _load_triples(self):
        if not os.path.exists(self.triples_path):
            return []
        with open(self.triples_path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)

    def _ensure_graph_constraints(self):
        if not self.neo4j_driver:
            return
        with self.neo4j_driver.session() as session:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.document_id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (cl:Class) REQUIRE cl.id IS UNIQUE")

    def ingest_directory(self, directory: str) -> dict:
        if not os.path.exists(directory):
            raise ValueError(f"Directory {directory} does not exist.")

        triples = self._load_triples()
        indexed_documents = 0
        indexed_chunks = 0
        skipped_documents = 0
        errors = []

        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".md") or filename.endswith(".summary.md"):
                continue

            file_path = os.path.join(directory, filename)
            try:
                result = self.ingest_file(file_path, triples)
                indexed_documents += int(result["indexed"])
                skipped_documents += int(result["skipped"])
                indexed_chunks += result["chunks"]
            except Exception as exc:
                logger.exception("Failed to ingest %s", filename)
                errors.append({"file": filename, "error": str(exc)})

        self._save_manifest()
        return {
            "indexed_documents": indexed_documents,
            "skipped_documents": skipped_documents,
            "indexed_chunks": indexed_chunks,
            "errors": errors,
        }

    def ingest_file(self, file_path: str, triples: list[dict] | None = None) -> dict:
        with open(file_path, "r", encoding="utf-8") as file_obj:
            content = file_obj.read()

        source_md = os.path.basename(file_path)
        document_id = MarkdownTreeParser.document_id_for(source_md)
        file_hash = _hash_file(content)

        if self.manifest.get(document_id, {}).get("file_hash") == file_hash:
            return {"indexed": False, "skipped": True, "chunks": 0, "document_id": document_id}

        chunks = MarkdownTreeParser.build_chunks(content, source_md)
        chunk_lookup = {chunk.chunk_id: chunk for chunk in chunks}

        self.chroma_repo.delete_document(document_id)
        self.lexical_repo.delete_document(document_id)

        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = [chunk.to_metadata() for chunk in chunks]

        self.chroma_repo.upsert_documents(ids, documents, metadatas)
        self.lexical_repo.upsert_documents(ids, documents, metadatas)

        source_triples = self._build_chunk_triples(source_md, chunks, triples or self._load_triples())
        self._upsert_graph_document(document_id, source_md, chunks, source_triples)

        self.manifest[document_id] = {
            "source_md": source_md,
            "file_hash": file_hash,
            "chunks": len(chunks),
        }
        return {"indexed": True, "skipped": False, "chunks": len(chunks), "document_id": document_id}

    def _build_chunk_triples(self, source_md: str, chunks: list, triples: list[dict]) -> list[dict]:
        relevant_triples = [triple for triple in triples if triple.get("source_md") == source_md]
        if not relevant_triples:
            return []

        by_section = defaultdict(list)
        for chunk in chunks:
            key = " > ".join(chunk.section_path)
            by_section[key].append(chunk)

        enriched = []
        for triple in relevant_triples:
            chunk = self._match_chunk(triple, chunks, by_section)
            subject_id, subject_type = _normalize_entity(triple.get("subject"))
            object_id, object_type = _normalize_entity(triple.get("object"))
            predicate = str(triple.get("predicate") or "RELATED").strip()
            if not subject_id or not object_id:
                continue

            relation_seed = (
                f"{chunk.chunk_id}:{subject_id}:{predicate}:{object_id}:{triple.get('source_location', '')}"
            )
            relation_id = hashlib.sha1(relation_seed.encode("utf-8")).hexdigest()[:16]
            enriched.append(
                {
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.chunk_id,
                    "evidence_id": chunk.evidence_id,
                    "source_md": chunk.source_md,
                    "source_location": triple.get("source_location") or chunk.source_location,
                    "source_context": triple.get("source_context") or chunk.snippet,
                    "subject_id": subject_id,
                    "subject_type": subject_type,
                    "object_id": object_id,
                    "object_type": object_type,
                    "predicate": predicate,
                    "relation_id": relation_id,
                }
            )
        return enriched

    def _match_chunk(self, triple: dict, chunks: list, by_section: dict) -> object:
        source_location = str(triple.get("source_location") or "").strip()
        if source_location:
            for section_path, section_chunks in by_section.items():
                if section_path and section_path in source_location:
                    return section_chunks[0]
            for chunk in chunks:
                if chunk.source_location in source_location:
                    return chunk
        return chunks[0]

    def _upsert_graph_document(self, document_id: str, source_md: str, chunks: list, triples: list[dict]):
        if not self.neo4j_driver:
            return

        with self.neo4j_driver.session() as session:
            session.run(
                """
                MATCH (d:Document {document_id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
                OPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(ev:Evidence)
                DETACH DELETE ev, c, d
                """,
                document_id=document_id,
            )
            session.run(
                """
                MATCH ()-[r:RELATED {document_id: $document_id}]->()
                DELETE r
                """,
                document_id=document_id,
            )
            session.run(
                """
                MERGE (d:Document {document_id: $document_id})
                SET d.source_md = $source_md
                """,
                document_id=document_id,
                source_md=source_md,
            )

            for chunk in chunks:
                session.run(
                    """
                    MATCH (d:Document {document_id: $document_id})
                    MERGE (c:Chunk {chunk_id: $chunk_id})
                    SET c.document_id = $document_id,
                        c.section_id = $section_id,
                        c.evidence_id = $evidence_id,
                        c.source_md = $source_md,
                        c.source_location = $source_location,
                        c.snippet = $snippet,
                        c.content = $content,
                        c.chunk_hash = $chunk_hash
                    MERGE (d)-[:HAS_CHUNK]->(c)
                    """,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    section_id=chunk.section_id,
                    evidence_id=chunk.evidence_id,
                    source_md=chunk.source_md,
                    source_location=chunk.source_location,
                    snippet=chunk.snippet,
                    content=chunk.content,
                    chunk_hash=chunk.chunk_hash,
                )

            for triple in triples:
                session.run(
                    """
                    MERGE (s:Entity {id: $subject_id})
                    ON CREATE SET s.type = $subject_type
                    MERGE (o:Entity {id: $object_id})
                    ON CREATE SET o.type = $object_type
                    MERGE (ev:Evidence {evidence_id: $evidence_id})
                    SET ev.document_id = $document_id,
                        ev.chunk_id = $chunk_id,
                        ev.source_md = $source_md,
                        ev.source_location = $source_location,
                        ev.source_context = $source_context
                    WITH s, o, ev
                    MATCH (c:Chunk {chunk_id: $chunk_id})
                    MERGE (s)-[r:RELATED {relation_id: $relation_id}]->(o)
                    SET r.original_predicate = $predicate,
                        r.document_id = $document_id,
                        r.chunk_id = $chunk_id,
                        r.evidence_id = $evidence_id,
                        r.source_md = $source_md,
                        r.source_location = $source_location,
                        r.source_context = $source_context
                    MERGE (c)-[:HAS_EVIDENCE]->(ev)
                    MERGE (ev)-[:SUPPORTS]->(s)
                    MERGE (ev)-[:SUPPORTS]->(o)
                    """,
                    **triple,
                )
