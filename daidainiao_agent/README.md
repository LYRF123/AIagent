# 呆呆鸟论文助手（daidainiao_agent）

`daidainiao_agent` 是一个面向论文阅读、资料检索和 AI Agent 面试准备的轻量研究助手。项目内置了一份小型公开论文示例语料，也支持导入本地 PDF、DOCX、TXT 文档，把它们加入知识库后进行检索、问答、对比、综述和离线评测。

项目既可以通过命令行使用，也提供了一个本地浏览器工作台。配置 DashScope API Key 后会调用阿里云 DashScope 的 Qwen 模型、Embedding 和重排能力；未配置模型密钥时会回退到本地规则生成和关键词检索流程。

## 主要功能

- 本地论文语料检索：基于 TF-IDF、BM25、查询扩展和混合排序检索相关论文片段。
- 证据约束问答：回答会附带证据片段、引用信息和调用轨迹，降低无依据生成的风险。
- 流式问答：Web 界面支持逐段返回回答，并在结束后展示完整证据和 JSON。
- 多轮会话：保存会话历史（`data/sessions.json`），追问时会扩展检索查询，并在生成时注入最近对话摘要。
- 模型配置档案：Web 设置中可保存、切换多套 API（URL / 模型 / Key），写入 `data/model_profiles.json` 与 `.env`。
- 论文对比：按论文 ID 或检索结果对比多篇论文的方法、发现和局限。
- 主题综述：围绕一个主题生成简短综述、趋势、代表论文、阅读顺序和开放问题。
- 本地文档导入：支持导入 PDF、DOCX、TXT，并自动刷新知识库索引；可在设置中删除已导入文档。
- 离线评测：运行内置 `demo_eval.json`，统计论文命中率、关键词命中率、平均回答长度和失败案例。
- Ragas 评估：配置 DashScope 后可运行 faithfulness、context precision、context recall、answer relevancy 等 LLM-as-judge 指标。
- CLI 与 Web UI：既能在终端运行，也能通过 `http://127.0.0.1:8000` 使用中文界面。

## 技术栈

- Python 3.11+
- scikit-learn：TF-IDF 检索
- 自实现 BM25：关键词召回
- LangChain + FAISS：向量检索
- DashScope Qwen：对话生成、Embedding、文本重排
- Ragas：RAG 回答质量和证据质量评估
- pypdf / python-docx：本地文件解析
- FastAPI + Uvicorn：默认后端服务（原生 http.server 通过 --legacy 可用）
- 原生 HTML/CSS/JavaScript：前端工作台

## 安装依赖

建议使用 Python 3.11 或更高版本。

```powershell
cd F:\codex\AIagent\daidainiao_agent
python -m pip install -e .
```

如果只想先体验无模型密钥的本地规则版本，也仍然需要安装项目依赖。

## DashScope 配置

不要把 API Key 写进代码仓库，建议通过环境变量配置：

```powershell
$env:DASHSCOPE_API_KEY = 'your-key'
$env:DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
$env:DASHSCOPE_MODEL = 'qwen-plus'
```

可选配置：

```powershell
$env:DASHSCOPE_EMBEDDING_MODEL = 'text-embedding-v4'
$env:DASHSCOPE_RERANK_MODEL = 'gte-rerank-v2'
```

项目也会读取 **`daidainiao_agent/.env`**（包根目录），但不要把包含真实密钥的 `.env` 提交到仓库。

在 Web **设置 → 模型 & 检索** 中填写 API 并点「保存并应用」时：

- **新建配置**须填写「配置名称」；
- 配置列表来自 `GET /settings/model` 的 `profiles` 字段，持久化在 `data/model_profiles.json`（已加入 `.gitignore`）；
- 仅修改「证据片段数 / 严格模式 / 重排」时只更新浏览器 localStorage，不会新增模型档案。

## 命令行使用

安装后可以直接使用 `daidainiao-agent` 命令，无需手动输入 `python -m daidainiao_agent.cli`：

```powershell
daidainiao-agent search --query "self reflection retrieval" --top-k 5
```

下面列出所有子命令的完整用法（`daidainiao-agent <子命令> ...` 与 `python -m daidainiao_agent.cli <子命令> ...` 等价）：

检索论文：

```powershell
python -m daidainiao_agent.cli search --query "self reflection retrieval" --top-k 5
```

基于证据回答问题：

```powershell
python -m daidainiao_agent.cli ask --question "ReAct 是如何把推理和工具调用结合起来的？"
```

对比论文：

```powershell
python -m daidainiao_agent.cli compare --ids react toolformer --focus "方法、结论和局限性"
```

生成主题综述：

```powershell
python -m daidainiao_agent.cli review --topic "multi agent software development"
```

运行离线评测：

```powershell
python -m daidainiao_agent.cli eval
```

默认评测使用内置示例语料，不加载本地已导入文档，避免本地上传资料影响 demo 指标。如需把本地导入文档也纳入评测，可加：

```powershell
python -m daidainiao_agent.cli eval --include-imported
```

运行 Ragas 评估：

```powershell
python -m daidainiao_agent.cli eval --ragas
```

`--ragas` 需要配置 `DASHSCOPE_API_KEY`，否则会保留基础评测结果，并在 JSON 结果中标记 Ragas 指标已跳过。

从本地论文文件夹生成评测集：

```powershell
python scripts/generate_ragas_eval.py --input-dir "F:\文献" --output-corpus data\literature_papers.json --output-eval data\literature_eval.json
```

使用生成的 corpus 和评测集运行：

```powershell
python -m daidainiao_agent.cli --corpus data\literature_papers.json eval --eval-path data\literature_eval.json --ragas
```

## 启动 Web 工作台

```powershell
python -m daidainiao_agent.cli serve
# 或指定端口：python -m daidainiao_agent.cli serve --host 127.0.0.1 --port 8000
```

然后在浏览器打开：

```text
http://127.0.0.1:8000
```

**安全提示**：默认服务无登录鉴权，仅建议在本地（`127.0.0.1`）使用，勿将端口暴露到公网。上传文件上限 50MB；评测集路径仅允许项目 `data/` 或项目根目录下的文件。可选环境变量：`DAIDAINIAO_CORS_ORIGINS`（逗号分隔来源）、`DAIDAINIAO_DEBUG=1`（SSE 错误显示详情）。

旧版 stdlib HTTP 服务（不推荐）：

```powershell
python -m daidainiao_agent.cli serve --legacy
```

如果要让 Web 工作台使用自定义论文库和评测集，可以先设置：

```powershell
$env:DAIDAINIAO_AGENT_CORPUS = 'data\literature_papers.json'
$env:DAIDAINIAO_AGENT_EVAL_PATH = 'data\literature_eval.json'
python -m daidainiao_agent.cli serve
```

Web 界面提供以下入口：

- 呆呆鸟助手聊天主界面（流式问答 + 会话侧栏）
- 思考步骤动画：检索 → 拆解 → 生成 → 引用
- 证据片段折叠卡（默认可展开更多；多页 PDF 按页/locator 去重展示）
- 新建 / 切换 / 清空 / 截断对话
- 导入 PDF / DOCX / TXT；设置中管理已导入文档与模型档案

## 上下文如何组织

单次问答时，后端会拼装三层上下文（详见 `answer_generator.py` / `agent.py`）：

| 层级 | 来源 | 作用 |
|------|------|------|
| 会话历史 | `data/sessions.json`，按 `session_id` 加载 | 追问时扩展检索查询；生成时取最近 **4 轮** 压缩进 prompt |
| 检索证据 | 混合检索 → 重排 → `top_k` 条 `Evidence` | 作为 RAG 依据，要求回答带 `[1][2]` 引用 |
| LLM Prompt | system + 单条 user | user 中含「历史摘要 + 当前问题 + 证据全文」 |

前端每次请求只传 `question`、`session_id`、`top_k`、`strict_grounded`、`use_rerank`；完整聊天记录由服务端按会话 ID 读取。

## 主要 HTTP API（FastAPI）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/settings/model` | 当前模型状态 + `profiles` 配置列表 |
| POST | `/settings/model` | 保存/切换模型档案，写 `.env` |
| POST | `/ask-stream` | SSE 流式问答 |
| POST | `/import-document` | 上传 PDF/DOCX/TXT |
| POST | `/delete-document` | 删除已导入文档 |
| POST | `/sessions/{id}/truncate` | 从某条消息起截断会话 |
| GET | `/sessions` | 会话列表 |

## 项目结构

```text
daidainiao_agent/
  daidainiao_agent/           # Python 包
    agent.py                  # 研究助手编排
    answer_generator.py       # 答案生成、prompt、证据去重
    app_service.py            # 会话与问答服务
    cli.py                    # 命令行入口
    fastapi_server.py         # FastAPI 服务（默认）
    model_profiles.py         # 模型配置档案读写
    session_store.py          # 会话持久化
    pipeline.py / steps.py    # 问答流水线
    hybrid.py / rag.py / retrieval.py  # 检索
    ...
  frontend/
    index.html / app.js / stream.js / workspace.js
    render/ confirm.js / handlers/
  data/
    demo_papers.json          # 内置论文语料
    demo_eval.json            # 内置评测集
    README.md                 # 本地数据说明
  docs/
    plan.md
    screenshots/
  scripts/
    generate_ragas_eval.py    # 从本地文献文件夹生成 Ragas 评测集
    prepare_openalex.py       # OpenAlex 数据转换
    prepare_qasper.py         # QASPER 评测集转换
  tests/
    conftest.py
    test_agent.py
    test_cli_and_server.py
    test_grounding_and_files.py
    test_sessions.py
  uploads/
    .gitkeep                  # 用户上传 PDF/DOCX/TXT（内容不入库）
```

## 本地数据扩展

1. 下载 OpenAlex works JSONL、arXiv 元数据或其他公开论文数据。
2. 使用 `scripts/prepare_openalex.py` 转换为本项目的论文 JSON 格式。
3. 如需评测数据，可使用 `scripts/prepare_qasper.py` 把 QASPER 转成项目内置评测格式。
4. 替换或追加 `data/demo_papers.json` 后，即可在 CLI 和 Web UI 中检索新语料。
5. 也可以直接在 Web 工作台中上传 PDF、DOCX 或 TXT，导入后会自动加入知识库。

## 测试

```powershell
python -m pytest -q
```

如果测试阶段提示缺少 `langchain_community`、`faiss-cpu` 等包，请先确认已经在 Python 3.11 环境里完成依赖安装。
