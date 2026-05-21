# 呆呆鸟论文助手（AIagent）

应用代码在 **`daidainiao_agent/`** 目录。克隆后进入该目录安装依赖并启动服务。

```powershell
cd daidainiao_agent
python -m pip install -e .
python -m daidainiao_agent.cli serve
```

浏览器打开：<http://127.0.0.1:8000>

## 文档

| 文档 | 说明 |
|------|------|
| [daidainiao_agent/README.md](daidainiao_agent/README.md) | 安装、CLI、Web UI、上下文组织、API 说明 |
| [daidainiao_agent/docs/plan.md](daidainiao_agent/docs/plan.md) | 前端产品方向与实现计划 |
| [daidainiao_agent/data/README.md](daidainiao_agent/data/README.md) | 本地数据目录（会话、索引、模型配置等） |

## 近期能力概览

- **呆呆鸟** 品牌 Web 工作台：流式问答、证据片段、多轮会话
- **模型配置档案**：设置中保存/切换多套 API（持久化到 `data/model_profiles.json`，不入库）
- **文档导入**：PDF / DOCX / TXT，支持在设置中删除已导入文档
- **混合检索**：TF-IDF + BM25 + 向量，可选 BGE 重排
