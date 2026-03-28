from fastapi import APIRouter, HTTPException, Query

try:
    from schema.chat_schema import ChatRequest, ChatResponse, IndexJobResponse, IndexRequest
    from service.rag_service import RagService
except ModuleNotFoundError:
    from rag_backend.schema.chat_schema import ChatRequest, ChatResponse, IndexJobResponse, IndexRequest
    from rag_backend.service.rag_service import RagService

router = APIRouter()
rag_service = RagService()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        result = rag_service.chat(
            request.query,
            request.top_k,
            (
                request.retrieval_options.model_dump()
                if request.retrieval_options and hasattr(request.retrieval_options, "model_dump")
                else request.retrieval_options.dict()
                if request.retrieval_options
                else None
            ),
        )
        return ChatResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/index", response_model=IndexJobResponse)
async def index_endpoint(request: IndexRequest):
    try:
        job = rag_service.submit_index_job(request.markdown_dir)
        return IndexJobResponse(**job)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/index/{job_id}", response_model=IndexJobResponse)
async def get_index_job(job_id: str):
    try:
        job = rag_service.get_index_job(job_id)
        return IndexJobResponse(**job)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/graph/global")
async def get_global_graph(threshold: float = Query(0.15, ge=0.0, le=1.0)):
    try:
        return rag_service.get_global_graph_data(threshold)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/graph/knowledge")
async def get_knowledge_graph():
    try:
        return rag_service.get_knowledge_graph_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/file/details")
async def get_file_details(filename: str):
    try:
        return rag_service.get_markdown_tree(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
