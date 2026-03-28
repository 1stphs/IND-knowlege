# IND GraphRAG System

面向药学注册资料（IND/NDA）的知识图谱与可溯源问答系统。  
目标是把非结构化文档转为结构化证据网络，并通过 `Hybrid GraphRAG` 提供**快速检索 + 可解释回答 + 来源可回溯**能力。

---

## 1. 系统目标与核心能力

- 统一处理 IND 文档（Markdown/PDF 转换结果），构建文本索引与图谱索引。
- 查询时同时利用词法检索、向量检索、图谱关系扩展，避免单一路径漏召回。
- 回答必须绑定证据（`evidence_id/source_md/source_location/chunk_id`），支持追溯到原文位置。
- 提供后台索引任务机制，支持异步提交、状态查询与前端状态页展示。

---

## 2. 总体架构（在线 + 离线）

### 2.1 架构分层

- 前端（`rag_frontend`）
  - React + TypeScript + Vite
  - 视图：文档语义图、知识图谱、RAG 问答、索引任务状态页
- 后端（`rag_backend`）
  - FastAPI 路由层（`/api/*`）
  - 服务层：`RagService / HybridRetriever / IngestionService / IndexJobService`
  - 存储层：`ChromaRepository`（向量） + `TfidfRepository`（词法）
- 数据层
  - Neo4j：图谱（Entity/Relation/Chunk/Evidence）
  - Chroma：向量索引（chunk 级）
  - Pickle/JSON：词法索引与索引任务状态

### 2.2 端到端数据流

1. 输入文档目录（`*.md`，通常来自 MinerU 输出）
2. `MarkdownTreeParser` 按章节切块，生成稳定 ID：
   - `document_id`, `section_id`, `chunk_id`, `evidence_id`
3. 同一批 chunk 同步写入：
   - Chroma（向量）
   - TF-IDF（词法）
   - Neo4j（Chunk/Evidence + Entity-Relation 证据回指）
4. 查询时 `HybridRetriever` 执行：
   - Query Understanding
   - Lexical Recall + Vector Recall + Graph Expansion
   - Merge/Rerank
   - Evidence Assembler
5. `RagService.chat()` 基于证据包生成回答，返回引用与图谱路径

---

## 3. 输入/输出契约

## 3.1 索引输入

- 输入：`markdown_dir`（目录）
- 文件要求：`*.md`，排除 `*.summary.md`
- 每个 chunk 元数据至少包含：
  - `document_id`, `section_id`, `chunk_id`, `evidence_id`
  - `source_md`, `source_location`, `snippet`, `chunk_hash`

## 3.2 问答输入（`POST /api/chat`）

```json
{
  "query": "TQB2858 的主要安全性风险是什么？",
  "top_k": 5,
  "retrieval_options": {
    "include_debug": false
  }
}
```

## 3.3 问答输出（`POST /api/chat`）

```json
{
  "answer": "......",
  "citations": [
    {
      "evidence_id": "ev_xxx",
      "document_id": "doc_xxx",
      "source_md": "xxx.md",
      "source_location": "2.5.5 > ... [chunk 1]",
      "chunk_id": "sec_xxx_chunk_0",
      "quote": "原文片段...",
      "score": 0.81,
      "evidence_type": "text",
      "score_breakdown": {
        "vector": 0.72,
        "keyword_overlap": 0.05
      }
    }
  ],
  "graph_paths": [
    {
      "summary": "实体A --[不良反应]--> 实体B",
      "evidence_id": "ev_xxx",
      "source_md": "xxx.md",
      "source_location": "..."
    }
  ],
  "retrieval_debug": {
    "query_understanding": {},
    "candidate_counts": {},
    "graph_routing": {}
  }
}
```

---

## 4. 知识图谱构建体系（Graph Build）

## 4.1 图谱模型

- TBox：`Class`（来自 `ontology/ind_schema.json`）
- ABox：`Entity` + `RELATED` 关系
- 证据层：`Document` -> `Chunk` -> `Evidence`
- 关系溯源：每条关系附带
  - `document_id`, `chunk_id`, `evidence_id`
  - `source_md`, `source_location`, `source_context`

## 4.2 构建链路

- `IngestionService` 负责统一入库，保证“同一 chunk”同时驱动：
  - 文本检索索引（向量 + 词法）
  - 图谱关系与证据回指
- `ontology/triples_to_neo4j.py` 支持离线导入与约束创建：
  - `Document/Chunk/Evidence/Entity/Class` 相关约束与节点写入

---

## 5. RAG 检索链路（Hybrid GraphRAG）

`Query -> Understanding -> Lexical + Vector + Graph -> Merge/Rerank -> Evidence -> Answer`

## 5.1 Query Understanding

- 提取 `keywords/entity_candidates/query_type`
- `query_type` 路由：`fact/comparison/relationship/safety`

## 5.2 Graph Expansion 收紧策略

- Neo4j 检索启用：
  - 实体候选白名单过滤（模式 + 关键词）
  - 谓词路由（按 `query_type` 限制允许谓词）
- 避免全图盲扫，降低噪声与查询成本

## 5.3 结果合并与证据组装

- 融合词法、向量、图谱候选并重排
- 统一输出 `citations`，前后端共享同一证据对象

## 5.4 失败降级

- 向量层不可用时自动降级词法检索（系统不断路）
- Neo4j 不可用时图谱候选为空，但文本链路仍可工作

---

## 6. API 清单

- `POST /api/chat`
  - 混合检索 + 证据问答
- `POST /api/index`
  - 提交异步索引任务（返回 `job_id`）
- `GET /api/index/{job_id}`
  - 查询索引任务状态
- `GET /api/graph/global`
  - 文档语义关联图
- `GET /api/graph/knowledge`
  - 知识图谱视图数据
- `GET /api/file/details?filename=...`
  - 文档章节树、关键词、摘要、chunk 元数据

---

## 7. 技术栈

- 后端
  - FastAPI, Uvicorn
  - OpenAI Python SDK
  - Neo4j Python Driver
  - ChromaDB
  - scikit-learn + jieba（词法检索）
- 前端
  - React, TypeScript, Vite
  - react-router-dom
  - reactflow / react-force-graph 相关组件
- 解析与知识抽取
  - MinerU（文档结构化）
  - 自定义语义抽取脚本（`semantic_extractor.py`）

---

## 8. 环境变量配置

在项目根目录创建 `.env`：

```env
# 回答生成（LLM）
OPENAI_API_KEY=your_llm_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# 向量检索（Embedding）
OPENAI_EMBEDDING_API_KEY=your_embedding_key
OPENAI_EMBEDDING_BASE_URL=https://api.openai.com/v1
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

使用 aihubmix embedding：

```env
OPENAI_EMBEDDING_API_KEY=your_key
OPENAI_EMBEDDING_BASE_URL=https://aihubmix.com/v1
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

说明：
- `RagService` 启动时会自动加载项目根目录 `.env`。
- 若 embedding key 缺失，系统会尝试本地 embedding 并在失败时降级词法检索。

---

## 9. 快速启动

### 9.1 安装依赖

```bash
pip install -r rag_backend/requirements.txt
cd rag_frontend && npm install
```

### 9.2 初始化索引（推荐）

```bash
python rag_backend/init_db.py
```

或启动后通过 API 提交索引任务：

```bash
POST /api/index
```

### 9.3 启动服务

```bash
# 后端
cd rag_backend
python main.py

# 前端
cd rag_frontend
npm run dev
```

---

## 10. 目录结构（关键部分）

- `ontology/`
  - `ind_schema.json`（本体）
  - `extracted_triples.json`（抽取结果）
  - `triples_to_neo4j.py`（图谱导入）
- `rag_backend/`
  - `api/routes.py`
  - `service/rag_service.py`
  - `service/hybrid_retriever.py`
  - `service/ingestion_service.py`
  - `service/index_job_service.py`
  - `service/markdown_parser.py`
  - `repository/chroma_repo.py`
  - `repository/tfidf_repo.py`
- `rag_frontend/src/components/`
  - `QAView.tsx`
  - `IndexStatusView.tsx`
  - `KnowledgeGraph.tsx`
  - `GlobalGraph.tsx`

---

## 11. 当前实现边界与建议

- 当前阶段是单体 FastAPI 形态，优先保证主链收敛与可维护性。
- 如果数据规模和并发继续增大，建议下一阶段演进：
  - 向量库迁移到 Qdrant/Milvus（可选）
  - 索引任务迁移到独立队列 worker
  - 增加系统级监控（索引耗时、召回分布、引用命中率）

