from typing import Any

from pydantic import BaseModel, Field


class RetrievalOptions(BaseModel):
    include_debug: bool = False
    source_mds: list[str] | None = None


class ChatRequest(BaseModel):
    query: str
    top_k: int = 5
    retrieval_options: RetrievalOptions | None = None


class Citation(BaseModel):
    evidence_id: str
    document_id: str | None = None
    source_md: str | None = None
    source_location: str | None = None
    chunk_id: str | None = None
    quote: str | None = None
    score: float = 0.0
    evidence_type: str = "text"
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class GraphPath(BaseModel):
    summary: str
    evidence_id: str
    source_md: str | None = None
    source_location: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    graph_paths: list[GraphPath]
    retrieval_debug: dict[str, Any] | None = None


class IndexRequest(BaseModel):
    markdown_dir: str = "../output_TQB2858_8.4_refined/mineru_markdowns"


class IndexJobResponse(BaseModel):
    job_id: str
    status: str
    markdown_dir: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str | None = None
