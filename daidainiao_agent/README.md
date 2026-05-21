# 呆呆鸟论文助手（daidainiao_agent）

`daidainiao_agent` 是一个面向论文阅读、资料检索和 AI Agent 面试准备的轻量研究助手。项目内置了一份小型公开论文示例语料，也支持导入本地 PDF、DOCX、TXT 文档，把它们加入知识库后进行检索、问答、对比、综述和离线评测。

项目既可以通过命令行使用，也提供了一个本地浏览器工作台。配置 DashScope API Key 后会调用阿里云 DashScope 的 Qwen 模型、Embedding 和重排能力；未配置模型密钥时会回退到本地规则生成和关键词检索流程。

## 主要功能

- 本地论文语料检索：基于 TF-IDF、BM25、查询扩展和混合排序检索相关论文片段。
- 证据约束问答：回答会附带证据片段、引用信息和调用轨迹，降低无依据生成的风险。
- 流式问答：Web 界面支持逐段返回回答，并在结束后展示完整证据和 JSON。
- 多轮会话：保存会话历史，后续问题会结合最近上下文做检索。
- 论文对比：按论文 ID 或检索结果对比多篇论文的方法、发现和局限。
- 主题综述：围绕一个主题生成简短综述、趋势、代表论文、阅读顺序和开放问题。
- 本地文档导入：支持导入 PDF、DOCX、TXT，并自动刷新知识库索引。
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

项目也会读取仓库根目录下的 `.env` 文件，但不要把包含真实密钥的 `.env` 提交到仓库。

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
python -m daidainiao_agent.server
```

然后在浏览器打开：

```text
http://127.0.0.1:8000
```

如果要让 Web 工作台使用自定义论文库和评测集，可以先设置：

```powershell
$env:DAIDAINIAO_AGENT_CORPUS = 'data\literature_papers.json'
$env:DAIDAINIAO_AGENT_EVAL_PATH = 'data\literature_eval.json'
python -m daidainiao_agent.server
```

Web 界面提供以下入口：

- 呆呆鸟助手聊天主界面（流式问答 + 会话侧栏）
- 思考步骤动画：检索 → 拆解 → 生成 → 引用
- 证据片段折叠卡（默认展示前 3 条）
- 新建 / 切换 / 清空对话
- 导入 PDF / DOCX / TXT 文档

## 项目结构

```text
daidainiao_agent/
  daidainiao_agent/           # Python 包
  frontend/
    index.html                # Web 页面（呆呆鸟聊天主界面）
    app.js                    # 前端交互入口
    ui-v2.css                 # v2 主题覆盖
    workspace.js              # 工作台侧栏
    confirm.js                # 确认弹窗
    icons/                    # 呆呆鸟等品牌图标
    state.js                  # DOM 引用与前端状态
    api.js                    # REST API 调用
    stream.js                 # /ask-stream SSE 流式驱动
    styles.css                # 基础样式
    handlers/
      sidebar.js              # 侧栏开关
    render/
      chat.js                 # 聊天气泡、思考动画、证据片段
      sessions.js             # 会话列表
      escape.js               # 转义与 markdown 辅助
    __init__.py
    agent.py                  # 研究助手核心逻辑（编排层）
    answer_generator.py       # 答案生成（规则 + LLM + 流式）
    app_service.py            # 会话和问答应用服务
    cli.py                    # 命令行入口
    comparison.py             # 论文对比逻辑
    corpus.py                 # 论文语料加载和维护
    evaluation.py             # 离线评测
    file_import.py            # PDF/DOCX/TXT 导入
    hybrid.py                 # 混合检索和重排
    llm.py                    # DashScope/Qwen 客户端
    logging_config.py         # 日志配置
    models.py                 # Pydantic 数据模型
    rag.py                    # LangChain + FAISS 向量检索
    retrieval.py              # TF-IDF、BM25、查询扩展
    review.py                 # 主题综述逻辑
    server.py                 # 本地 HTTP 服务（legacy）
    fastapi_server.py         # FastAPI 服务（默认）
    server_utils.py           # 导入等 HTTP 工具
    pipeline.py / steps.py    # 问答流水线
    session_store.py          # 会话持久化
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
