import json
import logging
import os
import sys

from neo4j import GraphDatabase
from openai import OpenAI
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from analyzer import TextAnalyzer
try:
    from service.hybrid_retriever import HybridRetriever
    from service.index_job_service import IndexJobService
    from service.markdown_parser import MarkdownTreeParser
except ModuleNotFoundError:
    from rag_backend.service.hybrid_retriever import HybridRetriever
    from rag_backend.service.index_job_service import IndexJobService
    from rag_backend.service.markdown_parser import MarkdownTreeParser

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        load_dotenv(os.path.join(self.root_dir, ".env"))
        self.kb_dir = os.path.join(self.root_dir, "output", "mineru_markdowns")
        self.schema_path = os.path.join(self.root_dir, "ontology", "ind_schema.json")
        self.triples_path = os.path.join(self.root_dir, "ontology", "extracted_triples.json")

        self.analyzer = TextAnalyzer()
        self.hybrid_retriever = HybridRetriever(self.root_dir)
        self.index_jobs = IndexJobService(self.root_dir)

        self.api_key = os.getenv("OPENVIKING_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
        self.api_base = os.getenv(
            "OPENVIKING_LLM_API_BASE",
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.client = OpenAI(api_key=self.api_key, base_url=self.api_base) if self.api_key else None

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD")
        self.neo4j_driver = None
        if neo4j_password:
            try:
                self.neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
            except Exception as exc:
                logger.warning("Neo4j unavailable during service init: %s", exc)

    def submit_index_job(self, directory: str):
        return self.index_jobs.submit(directory)

    def get_index_job(self, job_id: str):
        job = self.index_jobs.get(job_id)
        if not job:
            raise FileNotFoundError(f"Index job {job_id} not found.")
        return job

    def index_markdown_directory(self, directory: str):
        return self.index_jobs.ingestion_service.ingest_directory(directory)

    def get_markdown_tree(self, filename: str):
        file_path = os.path.join(self.kb_dir, filename)
        if not os.path.exists(file_path) and not file_path.endswith(".md"):
            file_path += ".md"
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {filename} not found.")

        source_md = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8") as file_obj:
            content = file_obj.read()

        tree = MarkdownTreeParser.parse_to_tree(content)
        chunks = MarkdownTreeParser.build_chunks(content, source_md)
        summary_path = file_path[:-3] + ".summary.md" if file_path.endswith(".md") else f"{file_path}.summary.md"
        summary_text = ""
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as summary_obj:
                summary_text = summary_obj.read()

        keywords = self.analyzer.get_keywords(content, top_k=8)
        hf_words = self.analyzer.get_high_freq_words(content, top_k=10)
        knowledge_graph = self.get_document_knowledge_graph(source_md)
        related_documents = self.get_related_documents_for_document(source_md)
        return {
            "filename": source_md,
            "document_id": MarkdownTreeParser.document_id_for(source_md),
            "keywords": [item[0] for item in keywords],
            "hf_words": [item[0] for item in hf_words],
            "summary": summary_text,
            "structure": tree,
            "chunks": [chunk.to_metadata() for chunk in chunks],
            "knowledge_graph": knowledge_graph,
            "related_documents": related_documents,
            "scope_documents": [source_md] + [item["source_md"] for item in related_documents],
        }

    def get_global_graph_data(self, threshold: float = 0.15):
        documents = self.hybrid_retriever.lexical_repo.documents
        metadatas = self.hybrid_retriever.lexical_repo.metadatas
        if not documents:
            return {"nodes": [], "edges": []}

        similarities = self.analyzer.vectorizer.fit_transform(documents) if False else None
        file_to_terms = {}
        for document, metadata in zip(documents, metadatas):
            source = metadata.get("source_md")
            file_to_terms.setdefault(source, []).append(document)

        nodes = [{"id": source, "label": source, "group": 1} for source in file_to_terms.keys()]
        edges = []
        sources = list(file_to_terms.keys())
        for left_index, left in enumerate(sources):
            left_text = "\n".join(file_to_terms[left])
            left_keywords = {keyword for keyword, _score in self.analyzer.get_keywords(left_text, top_k=20)}
            for right in sources[left_index + 1 :]:
                right_text = "\n".join(file_to_terms[right])
                right_keywords = {keyword for keyword, _score in self.analyzer.get_keywords(right_text, top_k=20)}
                overlap = len(left_keywords & right_keywords)
                union = len(left_keywords | right_keywords) or 1
                score = overlap / union
                if score > threshold:
                    edges.append(
                        {
                            "source": left,
                            "target": right,
                            "value": round(score, 4),
                            "label": f"{score:.2f}",
                        }
                    )
        return {"nodes": nodes, "edges": edges}

    def get_knowledge_graph_data(self):
        nodes = []
        links = []
        node_id_map = {}

        if self.neo4j_driver:
            try:
                with self.neo4j_driver.session() as session:
                    class_results = session.run("MATCH (c:Class) RETURN c.id AS id, c.description AS description")
                    for record in class_results:
                        class_id = record["id"]
                        nodes.append(
                            {
                                "id": class_id,
                                "label": class_id,
                                "type": "Class",
                                "group": 0,
                                "description": record["description"],
                            }
                        )
                        node_id_map[class_id] = "Class"

                    entity_results = session.run("MATCH (e:Entity) RETURN e.id AS id LIMIT 1000")
                    for record in entity_results:
                        entity_id = record["id"]
                        if entity_id in node_id_map:
                            continue
                        nodes.append({"id": entity_id, "label": entity_id, "type": "Instance", "group": 2})
                        node_id_map[entity_id] = "Instance"

                    relation_results = session.run(
                        """
                        MATCH (s:Entity)-[r:RELATED]->(o:Entity)
                        RETURN s.id AS source,
                               o.id AS target,
                               r.original_predicate AS predicate,
                               r.source_context AS context,
                               r.source_location AS location,
                               r.source_md AS source_md,
                               r.chunk_id AS chunk_id,
                               r.evidence_id AS evidence_id
                        LIMIT 1500
                        """
                    )
                    for record in relation_results:
                        links.append(
                            {
                                "source": record["source"],
                                "target": record["target"],
                                "label": record["predicate"] or "RELATED",
                                "value": 1,
                                "source_context": record["context"],
                                "source_location": record["location"],
                                "source_md": record["source_md"],
                                "chunk_id": record["chunk_id"],
                                "evidence_id": record["evidence_id"],
                            }
                        )
            except Exception as exc:
                logger.warning("Failed to load graph from Neo4j: %s", exc)

        if nodes:
            return {"nodes": nodes, "links": links}
        return self._load_graph_fallback()

    def get_document_knowledge_graph(self, source_md: str):
        nodes = []
        links = []
        node_id_map = {}

        if self.neo4j_driver:
            try:
                with self.neo4j_driver.session() as session:
                    relation_results = session.run(
                        """
                        MATCH (s:Entity)-[r:RELATED]->(o:Entity)
                        WHERE r.source_md = $source_md
                        RETURN s.id AS source,
                               o.id AS target,
                               r.original_predicate AS predicate,
                               r.source_context AS context,
                               r.source_location AS location,
                               r.source_md AS source_md,
                               r.chunk_id AS chunk_id,
                               r.evidence_id AS evidence_id
                        LIMIT 400
                        """,
                        source_md=source_md,
                    )
                    for record in relation_results:
                        source = record["source"]
                        target = record["target"]
                        if source not in node_id_map:
                            nodes.append({"id": source, "label": source, "type": "Instance", "group": 2})
                            node_id_map[source] = "Instance"
                        if target not in node_id_map:
                            nodes.append({"id": target, "label": target, "type": "Instance", "group": 2})
                            node_id_map[target] = "Instance"
                        links.append(
                            {
                                "source": source,
                                "target": target,
                                "label": record["predicate"] or "RELATED",
                                "value": 1,
                                "source_context": record["context"],
                                "source_location": record["location"],
                                "source_md": record["source_md"],
                                "chunk_id": record["chunk_id"],
                                "evidence_id": record["evidence_id"],
                            }
                        )
            except Exception as exc:
                logger.warning("Failed to load document graph from Neo4j: %s", exc)

        if nodes:
            return {"nodes": nodes, "links": links}
        return self._load_document_graph_fallback(source_md)

    def get_related_documents_for_document(self, source_md: str, limit: int = 10):
        if self.neo4j_driver:
            try:
                with self.neo4j_driver.session() as session:
                    records = session.run(
                        """
                        MATCH (s:Entity)-[r:RELATED]->(o:Entity)
                        WHERE r.source_md = $source_md
                        WITH collect(DISTINCT s.id) + collect(DISTINCT o.id) AS entity_ids
                        UNWIND entity_ids AS entity_id
                        WITH DISTINCT entity_id
                        MATCH (e:Entity {id: entity_id})-[r2:RELATED]-()
                        WHERE r2.source_md IS NOT NULL AND r2.source_md <> $source_md
                        RETURN r2.source_md AS source_md, count(*) AS overlap_count
                        ORDER BY overlap_count DESC, source_md ASC
                        LIMIT $limit
                        """,
                        source_md=source_md,
                        limit=limit,
                    )
                    return [
                        {
                            "source_md": record["source_md"],
                            "overlap_count": record["overlap_count"],
                        }
                        for record in records
                        if record["source_md"]
                    ]
            except Exception as exc:
                logger.warning("Failed to load related documents from Neo4j: %s", exc)

        return self._load_related_documents_fallback(source_md, limit=limit)

    def _load_graph_fallback(self):
        nodes = []
        links = []
        node_id_map = {}
        try:
            if os.path.exists(self.schema_path):
                with open(self.schema_path, "r", encoding="utf-8") as file_obj:
                    schema_data = json.load(file_obj)
                classes = schema_data.get("ontology", {}).get("classes", [])

                def walk(items):
                    for item in items:
                        if isinstance(item, str):
                            class_id = item
                            description = ""
                            children = []
                        else:
                            class_id = item.get("id")
                            description = item.get("description", "")
                            children = item.get("subclasses", [])
                        if class_id and class_id not in node_id_map:
                            nodes.append(
                                {
                                    "id": class_id,
                                    "label": class_id,
                                    "type": "Class",
                                    "group": 0,
                                    "description": description,
                                }
                            )
                            node_id_map[class_id] = "Class"
                        if children:
                            walk(children)

                walk(classes)

            if os.path.exists(self.triples_path):
                with open(self.triples_path, "r", encoding="utf-8") as file_obj:
                    triples = json.load(file_obj)[:500]
                for triple in triples:
                    subject = self._extract_node_id(triple.get("subject"))
                    obj = self._extract_node_id(triple.get("object"))
                    if subject not in node_id_map:
                        nodes.append({"id": subject, "label": subject, "type": "Instance", "group": 2})
                        node_id_map[subject] = "Instance"
                    if obj not in node_id_map:
                        nodes.append({"id": obj, "label": obj, "type": "Instance", "group": 2})
                        node_id_map[obj] = "Instance"
                    links.append(
                        {
                            "source": subject,
                            "target": obj,
                            "label": triple.get("predicate") or "RELATED",
                            "value": 1,
                            "source_context": triple.get("source_context", ""),
                            "source_location": triple.get("source_location", ""),
                            "source_md": triple.get("source_md", ""),
                            "chunk_id": triple.get("chunk_id", ""),
                            "evidence_id": "",
                        }
                    )
        except Exception as exc:
            logger.warning("Fallback graph loading failed: %s", exc)
        return {"nodes": nodes, "links": links}

    def _load_document_graph_fallback(self, source_md: str):
        nodes = []
        links = []
        node_id_map = {}
        try:
            if os.path.exists(self.triples_path):
                with open(self.triples_path, "r", encoding="utf-8") as file_obj:
                    triples = json.load(file_obj)
                for triple in triples:
                    if triple.get("source_md") != source_md:
                        continue
                    subject = self._extract_node_id(triple.get("subject"))
                    obj = self._extract_node_id(triple.get("object"))
                    if subject not in node_id_map:
                        nodes.append({"id": subject, "label": subject, "type": "Instance", "group": 2})
                        node_id_map[subject] = "Instance"
                    if obj not in node_id_map:
                        nodes.append({"id": obj, "label": obj, "type": "Instance", "group": 2})
                        node_id_map[obj] = "Instance"
                    links.append(
                        {
                            "source": subject,
                            "target": obj,
                            "label": triple.get("predicate") or "RELATED",
                            "value": 1,
                            "source_context": triple.get("source_context", ""),
                            "source_location": triple.get("source_location", ""),
                            "source_md": triple.get("source_md", ""),
                            "chunk_id": triple.get("chunk_id", ""),
                            "evidence_id": triple.get("evidence_id", ""),
                        }
                    )
        except Exception as exc:
            logger.warning("Document graph fallback loading failed: %s", exc)
        return {"nodes": nodes, "links": links}

    def _load_related_documents_fallback(self, source_md: str, limit: int = 10):
        if not os.path.exists(self.triples_path):
            return []

        try:
            with open(self.triples_path, "r", encoding="utf-8") as file_obj:
                triples = json.load(file_obj)
        except Exception as exc:
            logger.warning("Related documents fallback loading failed: %s", exc)
            return []

        current_entities = set()
        for triple in triples:
            if triple.get("source_md") != source_md:
                continue
            current_entities.add(self._extract_node_id(triple.get("subject")))
            current_entities.add(self._extract_node_id(triple.get("object")))

        overlap_counts: dict[str, int] = {}
        for triple in triples:
            other_source = triple.get("source_md")
            if not other_source or other_source == source_md:
                continue
            subject = self._extract_node_id(triple.get("subject"))
            obj = self._extract_node_id(triple.get("object"))
            if subject in current_entities or obj in current_entities:
                overlap_counts[other_source] = overlap_counts.get(other_source, 0) + 1

        related_documents = [
            {"source_md": other_source, "overlap_count": count}
            for other_source, count in sorted(overlap_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]
        return related_documents

    def _extract_node_id(self, item):
        if isinstance(item, dict):
            return item.get("id") or item.get("name") or str(item)
        return str(item)

    def chat(self, query: str, top_k: int = 5, retrieval_options: dict | None = None):
        source_mds = []
        if retrieval_options and retrieval_options.get("source_mds"):
            source_mds = [item for item in retrieval_options.get("source_mds", []) if item]
        retrieval = self.hybrid_retriever.retrieve(query, top_k=top_k, source_mds=source_mds or None)
        citations = retrieval["citations"]
        graph_paths = retrieval["graph_paths"]
        retrieval_debug = retrieval["retrieval_debug"]

        if not citations:
            return {
                "answer": "当前没有检索到足够证据来支持结论，请尝试缩小问题范围或指定更明确的实体、研究阶段或文档名称。",
                "citations": [],
                "graph_paths": [],
                "retrieval_debug": retrieval_debug,
            }

        answer = self._generate_grounded_answer(query, retrieval["evidence_pack"], retrieval_debug)
        return {
            "answer": answer,
            "citations": citations,
            "graph_paths": graph_paths,
            "retrieval_debug": retrieval_debug,
        }

    def _generate_grounded_answer(self, query: str, evidence_pack: list[dict], retrieval_debug: dict):
        if not self.client:
            top_evidence = evidence_pack[:3]
            joined = "；".join(
                f"{item['source_md']} / {item['source_location']}：{item['quote'][:120]}"
                for item in top_evidence
            )
            return f"已检索到与问题最相关的证据片段：{joined}"

        evidence_text = "\n\n".join(
            (
                f"[{item['evidence_id']}] {item['source_md']} | {item['source_location']} | "
                f"{item['evidence_type']}\n{item['quote']}"
            )
            for item in evidence_pack[:6]
        )
        prompt = f"""你是一个专业的药学注册知识库助手。你只能根据给定证据回答，不能补充未被证据支持的事实。

如果证据不足，请明确回答“现有证据不足以支持结论”。
请优先概括结论，再补充关键依据，但不要伪造引用。

### 查询理解
{json.dumps(retrieval_debug["query_understanding"], ensure_ascii=False)}

### 证据包
{evidence_text}

### 用户问题
{query}
"""
        model_name = os.getenv("OPENVIKING_LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
        try:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个严谨的药学注册知识助手。回答必须只基于证据包，不要引用证据包之外的信息。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            return response.choices[0].message.content
        except Exception as exc:
            logger.warning("LLM answer generation failed, falling back to evidence summary: %s", exc)
            top_evidence = evidence_pack[:3]
            joined = "；".join(
                f"{item['source_md']} / {item['source_location']}：{item['quote'][:120]}"
                for item in top_evidence
            )
            return f"已基于当前检索证据返回摘要：{joined}"
