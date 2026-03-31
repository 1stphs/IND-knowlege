**项目定位**

这个项目本质上不是“单纯的前后端网站”，而是一个围绕 IND/NDA 文档做知识抽取、建索引、图谱检索和证据问答的完整系统。它可以分成 3 层来看：

1. 离线文档加工层
2. 在线检索问答后端
3. 可视化前端

离线层负责把原始 PDF/Word/Excel 转成 Markdown、摘要、三元组和图谱素材；在线后端负责把 Markdown 建成可检索索引并提供 API；前端负责展示知识图谱、文档详情、索引任务状态和问答界面。设计说明在 [README.md](D:/益诺思/IND/IND-knowlege/README.md)，真实实现入口在 [rag_backend/main.py:1](D:/益诺思/IND/IND-knowlege/rag_backend/main.py#L1) 和 [rag_frontend/src/App.tsx:1](D:/益诺思/IND/IND-knowlege/rag_frontend/src/App.tsx#L1)。

**整体架构**

后端是单体 FastAPI。应用启动时加载根目录 `.env`，开启 CORS，然后把所有接口挂到 `/api` 前缀下，见 [rag_backend/main.py:8](D:/益诺思/IND/IND-knowlege/rag_backend/main.py#L8) 和 [rag_backend/api/routes.py:10](D:/益诺思/IND/IND-knowlege/rag_backend/api/routes.py#L10)。API 很集中，核心就是 5 类：

- `POST /api/chat`：RAG 问答
- `POST /api/index`：提交后台索引任务
- `GET /api/index/{job_id}`：查索引状态
- `GET /api/graph/knowledge`：知识图谱
- `GET /api/file/details`：文档详情

服务核心都收在 `RagService`，见 [rag_backend/service/rag_service.py:25](D:/益诺思/IND/IND-knowlege/rag_backend/service/rag_service.py#L25)。它内部再组合几个模块：

- `HybridRetriever`：混合检索总控，见 [rag_backend/service/hybrid_retriever.py:326](D:/益诺思/IND/IND-knowlege/rag_backend/service/hybrid_retriever.py#L326)
- `IndexJobService`：异步索引任务管理
- `IngestionService`：把 Markdown 真正写进索引和图谱
- `MarkdownTreeParser`：章节树和 chunk 切分
- `TextAnalyzer`：关键词/高频词分析

数据存储上是“三套并行”：

- Neo4j：实体、关系、Document/Chunk/Evidence 图结构
- Chroma：向量检索库
- 本地 `pickle/json`：TF-IDF 词法检索库、索引 manifest、任务状态

这里最关键的实现点是：同一份 Markdown 被切块后，会同时进入向量库、词法库、Neo4j，不是各搞各的，见 [rag_backend/service/ingestion_service.py:127](D:/益诺思/IND/IND-knowlege/rag_backend/service/ingestion_service.py#L127) 到 [rag_backend/service/ingestion_service.py:141](D:/益诺思/IND/IND-knowlege/rag_backend/service/ingestion_service.py#L141)。

前端是一个 React + Vite 单页应用，路由很简单，实际启用的页面只有：

- `/knowledge-graph`：本体/实体知识图谱
- `/file/:filename`：文档详情页
- `/qa`：全局问答
- `/index-status`：索引任务状态

见 [rag_frontend/src/App.tsx:44](D:/益诺思/IND/IND-knowlege/rag_frontend/src/App.tsx#L44)。代码里虽然有 [GlobalGraph.tsx](D:/益诺思/IND/IND-knowlege/rag_frontend/src/components/GlobalGraph.tsx)，但当前路由没有挂出来，所以它更像是预留或历史组件。

**前后端怎么配合**

前端基本不做业务计算，主要是发请求和渲染结果。

全局问答页 [rag_frontend/src/components/QAView.tsx:47](D:/益诺思/IND/IND-knowlege/rag_frontend/src/components/QAView.tsx#L47) 会直接请求 `http://localhost:8000/api/chat`，带上 `query/top_k/retrieval_options`。后端进入 [rag_backend/api/routes.py:14](D:/益诺思/IND/IND-knowlege/rag_backend/api/routes.py#L14)，再调用 `RagService.chat()`，见 [rag_backend/service/rag_service.py:428](D:/益诺思/IND/IND-knowlege/rag_backend/service/rag_service.py#L428)。

文档详情页更有意思。它先调 `GET /api/file/details` 拉到：

- 文档结构树
- chunk 元数据
- 关键词/高频词
- 文档级知识图谱
- 相关文档列表
- 问答作用域文档列表

见 [rag_frontend/src/components/FileDetailView.tsx:426](D:/益诺思/IND/IND-knowlege/rag_frontend/src/components/FileDetailView.tsx#L426)。然后用户在右下角文档问答里提问时，前端会把 `source_mds` 一起传给 `/api/chat`，把检索范围限制在“当前文档 + 关联文档”，见 [rag_frontend/src/components/FileDetailView.tsx:549](D:/益诺思/IND/IND-knowlege/rag_frontend/src/components/FileDetailView.tsx#L549)。

也就是说，前端不是只管显示，它还参与“限定检索作用域”的产品逻辑。

**后端运行流程**

最核心的在线流程是问答流程。

1. 前端把问题发到 `/api/chat`
2. `RagService.chat()` 接收 query，并读取可选的 `source_mds`
3. `HybridRetriever.retrieve()` 做混合召回
4. 召回结果被去重、重排、组装成统一 citation/evidence
5. `RagService` 再用 LLM 或降级摘要生成最终答案
6. 返回 `answer + citations + graph_paths + retrieval_debug`

其中 `HybridRetriever` 具体做了三路检索，见 [rag_backend/service/hybrid_retriever.py:335](D:/益诺思/IND/IND-knowlege/rag_backend/service/hybrid_retriever.py#L335)：

- `lexical_repo.search()`：TF-IDF 词法召回
- `vector_repo.search()`：Chroma 向量召回
- `graph_retriever.search()`：Neo4j 图谱召回

图谱召回不是盲查全图，而是先做 query understanding，抽关键词、实体候选、问题类型，再根据 `comparison/relationship/safety` 等类型限定谓词提示，见 [rag_backend/service/hybrid_retriever.py:393](D:/益诺思/IND/IND-knowlege/rag_backend/service/hybrid_retriever.py#L393) 和 [rag_backend/service/hybrid_retriever.py:64](D:/益诺思/IND/IND-knowlege/rag_backend/service/hybrid_retriever.py#L64)。

之后三路结果被统一合并：

- 按 `evidence_id` 去重
- 补充 `score_breakdown`
- 再做一层 rerank
- 最终装配成标准 citation 对象

这部分在 [rag_backend/service/hybrid_retriever.py:348](D:/益诺思/IND/IND-knowlege/rag_backend/service/hybrid_retriever.py#L348) 到 [rag_backend/service/hybrid_retriever.py:390](D:/益诺思/IND/IND-knowlege/rag_backend/service/hybrid_retriever.py#L390)。

最后答案生成分两种：

- 有 LLM key：调用 OpenAI 兼容接口，根据 evidence pack 生成 grounded answer，见 [rag_backend/service/rag_service.py:453](D:/益诺思/IND/IND-knowlege/rag_backend/service/rag_service.py#L453)
- 没有 LLM key：直接把前几个证据拼成摘要返回，系统仍可工作，见 [rag_backend/service/rag_service.py:454](D:/益诺思/IND/IND-knowlege/rag_backend/service/rag_service.py#L454)

这说明它的在线链路具备“弱降级能力”：LLM、Neo4j、Embedding 某一层不通时，不一定整个系统就死掉。

**索引和建库流程**

索引流程是另一条主链。

入口有两个：

- 直接运行 [rag_backend/init_db.py](D:/益诺思/IND/IND-knowlege/rag_backend/init_db.py)
- 前端/接口调用 `POST /api/index`

`init_db.py` 会默认去索引 `output/mineru_markdowns`，见 [rag_backend/init_db.py:10](D:/益诺思/IND/IND-knowlege/rag_backend/init_db.py#L10)。而 API 异步索引则会先创建 job，再开线程执行，见 [rag_backend/service/index_job_service.py](D:/益诺思/IND/IND-knowlege/rag_backend/service/index_job_service.py)。

真正干活的是 `IngestionService`：

1. 遍历目录里所有 `.md`，排除 `.summary.md`
2. 计算文件 hash，和 manifest 对比，没变就跳过
3. 用 `MarkdownTreeParser.build_chunks()` 切块
4. 删除该文档旧索引
5. 重建 Chroma 与 TF-IDF 索引
6. 把 `ontology/extracted_triples.json` 中对应文档的三元组匹配回 chunk
7. 写入 Neo4j 的 `Document/Chunk/Evidence/Entity/RELATED`

你可以直接看 [rag_backend/service/ingestion_service.py:84](D:/益诺思/IND/IND-knowlege/rag_backend/service/ingestion_service.py#L84) 和 [rag_backend/service/ingestion_service.py:202](D:/益诺思/IND/IND-knowlege/rag_backend/service/ingestion_service.py#L202)。

这里有个很重要的设计：Markdown 切块和三元组抽取不是同一步完成的。三元组来自离线生成的 `ontology/extracted_triples.json`，索引阶段只是把它们“挂回 chunk 和 evidence”，这样前端才能做证据追溯。

**离线数据准备流程**

根目录这批脚本是“数据生产线”，不是前后端直接运行时的主服务。

完整离线链路大概是：

1. 原始文档目录交给 [main.py](D:/益诺思/IND/IND-knowlege/main.py)
2. `main.py` 调 MinerU 把 PDF/Word/Excel 转成 Markdown
3. 为每个 Markdown 生成 `.summary.md`
4. 提取关键词和高频词
5. 生成单文档图和全局关系图 HTML
6. 后续再用 [semantic_extractor.py](D:/益诺思/IND/IND-knowlege/semantic_extractor.py) 从 Markdown 抽取三元组，写到 `ontology/extracted_triples.json`
7. 在线系统再拿这些 Markdown 和 triples 去建检索库与 Neo4j 图谱

其中：

- [main.py](D:/益诺思/IND/IND-knowlege/main.py) 偏“文档预处理 + 摘要 + 传统图输出”
- [semantic_extractor.py](D:/益诺思/IND/IND-knowlege/semantic_extractor.py) 偏“LLM 三元组抽取”
- [aggregate_summaries.py](D:/益诺思/IND/IND-knowlege/aggregate_summaries.py) 是摘要聚合辅助脚本
- [graph_builder.py](D:/益诺思/IND/IND-knowlege/graph_builder.py) 是早期 HTML 图输出工具

所以这个项目其实经历过一个演进：先有离线分析脚本，后面又长出了 `rag_backend + rag_frontend` 这套正式在线系统。

**启动方式**

最常用的启动方式，按实际依赖顺序建议这样走：

1. 准备环境变量  
   参考 [README.md](D:/益诺思/IND/IND-knowlege/README.md) 和 [.env.example](D:/益诺思/IND/IND-knowlege/.env.example)。至少建议配：
   - `OPENAI_API_KEY` 或 `OPENVIKING_LLM_API_KEY`
   - `OPENAI_EMBEDDING_API_KEY`
   - `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD`

2. 安装依赖
```bash
pip install -r rag_backend/requirements.txt
cd rag_frontend
npm install
```

3. 准备数据
   需要有 `output/mineru_markdowns/*.md`，以及更理想情况下有 `ontology/extracted_triples.json`。

4. 初始化索引
```bash
python rag_backend/init_db.py
```

5. 启动后端
```bash
cd rag_backend
python main.py
```
默认监听 `http://localhost:8000`，见 [rag_backend/main.py:23](D:/益诺思/IND/IND-knowlege/rag_backend/main.py#L23)。

6. 启动前端
```bash
cd rag_frontend
npm run dev
```

7. 打开前端开发地址
   Vite 默认一般是 `http://localhost:5173`

前端代码里 API 地址是写死的 `http://localhost:8000`，见 [rag_frontend/src/components/QAView.tsx:58](D:/益诺思/IND/IND-knowlege/rag_frontend/src/components/QAView.tsx#L58) 和 [rag_frontend/src/components/FileDetailView.tsx:550](D:/益诺思/IND/IND-knowlege/rag_frontend/src/components/FileDetailView.tsx#L550)，所以当前默认就是本机联调模式，不是通过代理或环境变量切换。

**你可以怎么理解这个项目**

最准确的一句话是：

这是一个“以 Markdown 为中间语料、以 Neo4j + Chroma + TF-IDF 为底座、以 FastAPI 为统一服务层、以 React 为可视化交互层”的 IND 文档 Hybrid GraphRAG 系统。

对，你记得的“接了 `foxu.ai`”是有依据的，但我刚核对完代码后，结论要分成两层来看：

当前这套正在跑的 `rag_backend` / `rag_frontend` 主链，文件来源是**本地 Markdown 目录**，不是运行时直接从 `foxu.ai` 拉。证据很明确：后端默认知识库目录写死在 [rag_service.py](D:/益诺思/IND/IND-knowlege/rag_backend/service/rag_service.py#L29) 的 `output/mineru_markdowns`，初始化索引也是读这个本地目录，见 [init_db.py](D:/益诺思/IND/IND-knowlege/rag_backend/init_db.py#L14)。索引接口 `POST /api/index` 接收的也是 `markdown_dir` 本地路径，见 [routes.py](D:/益诺思/IND/IND-knowlege/rag_backend/api/routes.py#L33)。

但另一边，项目里**确实保留了 FoxUAI 对接代码**。`.env` 里有 `FOXUAI_*` 配置，客户端在 [foxuai_client.py](D:/益诺思/IND/IND-knowlege/lib/foxuai_client.py#L11)，还有历史同步脚本比如 [sync_foxuai.py](D:/益诺思/IND/IND-knowlege/archive/sync_foxuai.py) 和 [sync_backfill.py](D:/益诺思/IND/IND-knowlege/archive/sync_backfill.py)。所以更准确地说是：**FoxUAI 负责同步/回传，当前在线 RAG 主服务消费的是已经落到本地的文件**。也就是说，`foxu.ai -> 本地落盘 -> 建索引 -> 前后端检索`，而不是 `前后端运行时 -> 实时读 foxu.ai`。

对，按你现在这份项目配置来看，`Neo4j` 也不是线上服务，而是本机或局域网实例。

代码里默认连的是 `.env` 里的 `NEO4J_URI=neo4j://127.0.0.1:7687`，见 [rag_service.py](D:/益诺思/IND/IND-knowlege/rag_backend/service/rag_service.py#L44) 和 [ingestion_service.py](D:/益诺思/IND/IND-knowlege/rag_backend/service/ingestion_service.py#L44)。`127.0.0.1` 就说明当前后端启动时只是在连你本机的 Neo4j，不是云上托管库。

- 最省事：连同环境一起交付  
  用 `Docker Compose` 把 `frontend + backend + neo4j` 一起打包，别人拉下来执行 `docker compose up` 就能跑。这是最适合演示和小规模交付的方式。

如果是“交付给客户/同事能直接用”，我最推荐第一种：  
把系统整理成“本地文件同步/导入 + 本地或容器化 Neo4j + 一键启动”的交付包。这样你现在这套代码改动最小。

