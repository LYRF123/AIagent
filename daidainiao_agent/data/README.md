# 本地数据目录

以下内容**不提交 Git**（见根目录 `.gitignore`），仅在本地运行时使用：

| 路径 | 说明 |
|------|------|
| `demo_papers.json` / `demo_eval.json` | 内置示例语料与评测集（已纳入版本库） |
| `imported_papers.json` | 用户导入的论文元数据 |
| `model_profiles.json` | 模型 API 配置（含密钥，切勿提交） |
| `faiss_index/` | 向量索引缓存 |
| `index_meta.json` | 索引元数据 |
| `models/` | 本地重排模型权重（如 `bge-reranker-base`） |
| `sessions.json` | 多轮会话记录 |

首次克隆后执行 `pip install -e .`，通过 Web 或 CLI 导入文档即可自动生成上述文件。

`model_profiles.json` 支持数组或 `{ "active_profile_id", "profiles" }` 两种格式；服务启动后会按当前 `.env` 中的模型自动匹配「当前」档案。
