import logging
import os
import re
from collections import defaultdict

from dotenv import load_dotenv
from neo4j import GraphDatabase

from analyzer import TextAnalyzer
try:
    from repository.chroma_repo import ChromaRepository
    from repository.tfidf_repo import TfidfRepository
except ModuleNotFoundError:
    from rag_backend.repository.chroma_repo import ChromaRepository
    from rag_backend.repository.tfidf_repo import TfidfRepository

logger = logging.getLogger(__name__)

QUERY_TYPE_PREDICATE_HINTS = {
    "fact": (),
    "comparison": ("result", "dose", "endpoint", "phase", "regimen", "剂量", "终点", "结果", "方案"),
    "relationship": ("target", "mechanism", "bind", "related", "ingredient", "component", "作用", "机制", "关联"),
    "safety": ("risk", "safety", "toxicity", "adverse", "ae", "不良", "风险", "毒性", "安全"),
}

ENTITY_STOPWORDS = {
    "什么",
    "哪些",
    "哪个",
    "多少",
    "如何",
    "有关",
    "关系",
    "关联",
    "说明",
    "介绍",
    "情况",
    "一下",
    "请问",
    "这个",
    "那个",
    "是否",
    "以及",
    "有哪些",
    "what",
    "tell",
    "about",
}


class GraphRetriever:
    def __init__(self):
        self.driver = None
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD")
        if neo4j_password:
            try:
                self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
            except Exception as exc:
                logger.warning("Neo4j unavailable during graph retriever init: %s", exc)

    def search(
        self,
        entity_candidates: list[str],
        query_type: str,
        keywords: list[str],
        raw_query: str,
        top_k: int = 6,
        source_mds: list[str] | None = None,
    ):
        search_terms = self._prepare_search_terms(entity_candidates, keywords, raw_query)
        if not self.driver or not search_terms:
            return [], [], {"search_terms": search_terms, "matched_entities": [], "predicate_hints": [], "fallback_used": False}

        results = []
        path_summaries = []
        predicate_hints = self._route_predicates(query_type)
        matched_entities = self._resolve_entities(search_terms, top_k=max(top_k * 3, 12), source_mds=source_mds)
        if not matched_entities:
            return [], [], {"search_terms": search_terms, "matched_entities": [], "predicate_hints": list(predicate_hints), "fallback_used": False}

        try:
            matched_entity_ids = [item["entity_id"] for item in matched_entities]
            relation_records = self._fetch_relations(matched_entity_ids, limit=top_k * 4, source_mds=source_mds)
            fallback_used = False

            if predicate_hints:
                filtered_records = self._filter_records_by_predicate_hint(relation_records, predicate_hints)
                if filtered_records:
                    relation_records = filtered_records
                else:
                    fallback_used = True

            entity_resolution = {item["entity_id"].lower(): item for item in matched_entities}
            for record in relation_records:
                predicate = self._normalize_predicate_label(record["predicate"])
                score = self._score_record(record, search_terms, predicate_hints, entity_resolution)
                evidence_id = record["evidence_id"] or f"graph_{record['chunk_id'] or record['subject_id']}_{record['object_id']}"
                results.append(
                    {
                        "id": evidence_id,
                        "content": record["source_context"] or f"{record['subject_id']} {predicate} {record['object_id']}",
                        "metadata": {
                            "document_id": record["document_id"],
                            "chunk_id": record["chunk_id"],
                            "evidence_id": evidence_id,
                            "source_md": record["source_md"],
                            "source_location": record["source_location"],
                            "snippet": record["source_context"] or f"{record['subject_id']} {predicate} {record['object_id']}",
                        },
                        "score": score,
                        "evidence_type": "graph",
                        "graph_path": {
                            "nodes": [record["subject_id"], record["object_id"]],
                            "predicate": predicate,
                        },
                    }
                )
                path_summaries.append(
                    {
                        "summary": f"{record['subject_id']} --[{predicate}]--> {record['object_id']}",
                        "evidence_id": evidence_id,
                        "source_md": record["source_md"],
                        "source_location": record["source_location"],
                    }
                )
        except Exception as exc:
            logger.warning("Graph retrieval failed: %s", exc)
            fallback_used = False

        results.sort(key=lambda item: item["score"], reverse=True)
        return (
            results[:top_k],
            path_summaries[:top_k],
            {
                "search_terms": search_terms,
                "matched_entities": matched_entities[:8],
                "predicate_hints": list(predicate_hints),
                "fallback_used": fallback_used,
                "source_mds": source_mds or [],
            },
        )

    def _route_predicates(self, query_type: str):
        return QUERY_TYPE_PREDICATE_HINTS.get(query_type, ())

    def _prepare_search_terms(self, candidates: list[str], keywords: list[str], raw_query: str) -> list[str]:
        raw_terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_.-]{2,}", raw_query)
        expanded_terms = []
        for term in candidates + keywords + raw_terms:
            if not term:
                continue
            expanded_terms.append(term)
            if "-" in term:
                expanded_terms.extend(fragment for fragment in term.split("-") if len(fragment) >= 2)

        deduped = []
        for term in expanded_terms:
            normalized = term.strip().lower()
            if len(normalized) < 2 or normalized in ENTITY_STOPWORDS:
                continue
            if normalized not in deduped:
                deduped.append(normalized)
        return deduped[:14]

    def _resolve_entities(self, search_terms: list[str], top_k: int, source_mds: list[str] | None = None) -> list[dict]:
        if source_mds:
            query = """
            MATCH (e:Entity)-[r:RELATED]-()
            WHERE r.source_md IN $source_mds
            WITH DISTINCT e,
                 [term IN $terms WHERE toLower(e.id) = term] AS exact_terms,
                 [term IN $terms WHERE toLower(e.id) CONTAINS term] AS fuzzy_terms
            WHERE size(exact_terms) > 0 OR size(fuzzy_terms) > 0
            RETURN e.id AS entity_id,
                   size(exact_terms) AS exact_hits,
                   size(fuzzy_terms) AS fuzzy_hits
            ORDER BY exact_hits DESC, fuzzy_hits DESC, size(e.id) ASC
            LIMIT $limit
            """
        else:
            query = """
            MATCH (e:Entity)
            WITH e,
                 [term IN $terms WHERE toLower(e.id) = term] AS exact_terms,
                 [term IN $terms WHERE toLower(e.id) CONTAINS term] AS fuzzy_terms
            WHERE size(exact_terms) > 0 OR size(fuzzy_terms) > 0
            RETURN e.id AS entity_id,
                   size(exact_terms) AS exact_hits,
                   size(fuzzy_terms) AS fuzzy_hits
            ORDER BY exact_hits DESC, fuzzy_hits DESC, size(e.id) ASC
            LIMIT $limit
            """
        resolved = []
        with self.driver.session() as session:
            records = session.run(query, terms=search_terms, limit=top_k, source_mds=source_mds or [])
            for record in records:
                resolved.append(
                    {
                        "entity_id": record["entity_id"],
                        "exact_hits": record["exact_hits"],
                        "fuzzy_hits": record["fuzzy_hits"],
                    }
                )
        return resolved

    def _fetch_relations(self, matched_entities: list[str], limit: int, source_mds: list[str] | None = None) -> list[dict]:
        if source_mds:
            query = """
            MATCH (s:Entity)-[r:RELATED]->(o:Entity)
            WHERE (s.id IN $entities OR o.id IN $entities)
              AND r.source_md IN $source_mds
            RETURN s.id AS subject_id,
                   o.id AS object_id,
                   r.original_predicate AS predicate,
                   r.document_id AS document_id,
                   r.chunk_id AS chunk_id,
                   r.evidence_id AS evidence_id,
                   r.source_md AS source_md,
                   r.source_location AS source_location,
                   r.source_context AS source_context
            LIMIT $limit
            """
        else:
            query = """
            MATCH (s:Entity)-[r:RELATED]->(o:Entity)
            WHERE s.id IN $entities OR o.id IN $entities
            RETURN s.id AS subject_id,
                   o.id AS object_id,
                   r.original_predicate AS predicate,
                   r.document_id AS document_id,
                   r.chunk_id AS chunk_id,
                   r.evidence_id AS evidence_id,
                   r.source_md AS source_md,
                   r.source_location AS source_location,
                   r.source_context AS source_context
            LIMIT $limit
            """
        records = []
        with self.driver.session() as session:
            raw = session.run(query, entities=matched_entities, limit=limit, source_mds=source_mds or [])
            for record in raw:
                records.append(dict(record))
        return records

    def _filter_records_by_predicate_hint(self, relation_records: list[dict], predicate_hints: tuple[str, ...]) -> list[dict]:
        filtered = []
        for record in relation_records:
            predicate_text = self._normalize_predicate_label(record["predicate"]).lower()
            if any(hint in predicate_text for hint in predicate_hints):
                filtered.append(record)
        return filtered

    def _normalize_predicate_label(self, predicate: str | None) -> str:
        if not predicate:
            return "RELATED"
        text = str(predicate).strip()
        match = re.search(r"""['"]id['"]\s*:\s*['"]([^'"]+)['"]""", text)
        if match:
            return match.group(1)
        return text

    def _score_record(self, record: dict, search_terms: list[str], predicate_hints: tuple[str, ...], entity_resolution: dict[str, dict]) -> float:
        predicate_label = self._normalize_predicate_label(record["predicate"])
        haystack = f"{record['subject_id']} {record['object_id']} {predicate_label} {record.get('source_context') or ''}".lower()
        term_hits = sum(1 for term in search_terms if term in haystack)

        anchor_bonus = 0.0
        for entity_id in (record["subject_id"], record["object_id"]):
            resolution = entity_resolution.get(entity_id.lower())
            if not resolution:
                continue
            anchor_bonus = max(
                anchor_bonus,
                0.2 + min(resolution.get("exact_hits", 0), 2) * 0.16 + min(resolution.get("fuzzy_hits", 0), 3) * 0.05,
            )

        predicate_bonus = 0.0
        predicate_text = predicate_label.lower()
        if predicate_hints and any(hint in predicate_text for hint in predicate_hints):
            predicate_bonus = 0.08

        context_bonus = 0.06 if record.get("source_context") else 0.0
        return min(0.99, 0.28 + anchor_bonus + term_hits * 0.05 + predicate_bonus + context_bonus)


class Reranker:
    def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        ranked = []
        normalized_terms = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}", query.lower()))
        for candidate in candidates:
            content = (candidate.get("content") or candidate.get("document") or "").lower()
            lexical_hits = sum(1 for term in normalized_terms if term in content)
            score_breakdown = candidate.setdefault("score_breakdown", {})
            score_breakdown["keyword_overlap"] = lexical_hits * 0.05
            candidate["score"] = candidate.get("score", 0.0) + lexical_hits * 0.05
            ranked.append(candidate)
        ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return ranked[:top_k]


class EvidenceAssembler:
    def assemble(self, candidates: list[dict]) -> list[dict]:
        deduped: dict[str, dict] = {}
        for candidate in candidates:
            metadata = candidate.get("metadata", {})
            evidence_id = metadata.get("evidence_id") or candidate.get("id")
            existing = deduped.get(evidence_id)
            if not existing or candidate.get("score", 0.0) > existing.get("score", 0.0):
                deduped[evidence_id] = {
                    "evidence_id": evidence_id,
                    "document_id": metadata.get("document_id") or metadata.get("source"),
                    "source_md": metadata.get("source_md") or metadata.get("source"),
                    "source_location": metadata.get("source_location") or metadata.get("chunk"),
                    "chunk_id": metadata.get("chunk_id") or metadata.get("chunk"),
                    "quote": metadata.get("snippet") or (candidate.get("content") or "")[:240],
                    "score": round(candidate.get("score", 0.0), 4),
                    "evidence_type": candidate.get("evidence_type", "text"),
                    "score_breakdown": candidate.get("score_breakdown", {}),
                }
        return list(deduped.values())


class HybridRetriever:
    def __init__(self, root_dir: str):
        self.analyzer = TextAnalyzer()
        self.vector_repo = ChromaRepository(os.path.join(root_dir, "rag_backend", "chroma_db"))
        self.lexical_repo = TfidfRepository(os.path.join(root_dir, "rag_backend", "simple_db"))
        self.graph_retriever = GraphRetriever()
        self.reranker = Reranker()
        self.assembler = EvidenceAssembler()

    def retrieve(self, query: str, top_k: int = 5, source_mds: list[str] | None = None) -> dict:
        query_understanding = self._understand_query(query)
        lexical = self.lexical_repo.search(query, top_k=top_k * 3, source_mds=source_mds)
        vector = self.vector_repo.search(query, top_k=top_k * 3, source_mds=source_mds)
        graph, graph_paths, graph_debug = self.graph_retriever.search(
            query_understanding["entity_candidates"],
            query_understanding["query_type"],
            query_understanding["keywords"],
            query,
            top_k=top_k,
            source_mds=source_mds,
        )

        merged = []
        for item in lexical:
            item["content"] = item["document"]
            item["evidence_type"] = "text"
            item["score_breakdown"] = {"lexical": round(item["score"], 4)}
            merged.append(item)
        for item in vector:
            item["content"] = item["document"]
            item["evidence_type"] = "text"
            item["score_breakdown"] = {"vector": round(item["score"], 4)}
            merged.append(item)
        for item in graph:
            item["score_breakdown"] = {"graph": round(item["score"], 4)}
            merged.append(item)

        merged = self._merge_scores(merged)
        ranked = self.reranker.rerank(query, merged, top_k)
        citations = self.assembler.assemble(ranked)
        evidence_pack = [
            {
                "evidence_id": citation["evidence_id"],
                "source_md": citation["source_md"],
                "source_location": citation["source_location"],
                "evidence_type": citation["evidence_type"],
                "quote": citation["quote"],
            }
            for citation in citations
        ]
        return {
            "citations": citations,
            "graph_paths": graph_paths,
            "retrieval_debug": {
                "query_understanding": query_understanding,
                "candidate_counts": {
                    "lexical": len(lexical),
                    "vector": len(vector),
                    "graph": len(graph),
                    "ranked": len(ranked),
                },
                "scope_documents": source_mds or [],
                "graph_routing": graph_debug,
            },
            "evidence_pack": evidence_pack,
        }

    def _understand_query(self, query: str) -> dict:
        keywords = [keyword for keyword, _score in self.analyzer.get_keywords(query, top_k=8)]
        regex_terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_.-]{2,}", query)
        entity_candidates = []
        for term in keywords + regex_terms:
            if term not in entity_candidates:
                entity_candidates.append(term)
        query_type = "fact"
        if any(token in query for token in ["比较", "区别", "相比"]):
            query_type = "comparison"
        elif any(token in query for token in ["关系", "关联", "机制"]):
            query_type = "relationship"
        elif any(token in query for token in ["不良反应", "安全", "风险"]):
            query_type = "safety"
        return {
            "keywords": keywords,
            "entity_candidates": entity_candidates[:10],
            "query_type": query_type,
        }

    def _merge_scores(self, candidates: list[dict]) -> list[dict]:
        grouped: dict[str, dict] = {}
        for candidate in candidates:
            metadata = candidate.get("metadata", {})
            evidence_id = metadata.get("evidence_id") or candidate.get("id")
            if evidence_id not in grouped:
                grouped[evidence_id] = candidate
                continue
            grouped[evidence_id]["score"] = max(grouped[evidence_id].get("score", 0.0), candidate.get("score", 0.0))
            grouped[evidence_id].setdefault("score_breakdown", {}).update(candidate.get("score_breakdown", {}))

        merged = list(grouped.values())
        by_document = defaultdict(int)
        for candidate in merged:
            document_id = candidate.get("metadata", {}).get("document_id")
            if document_id:
                by_document[document_id] += 1

        for candidate in merged:
            metadata = candidate.get("metadata", {})
            document_id = metadata.get("document_id")
            source_bonus = 0.02 if by_document.get(document_id, 0) > 1 else 0.0
            candidate.setdefault("score_breakdown", {})["source_quality"] = source_bonus
            candidate["score"] = min(1.0, candidate.get("score", 0.0) + source_bonus)
        return merged
