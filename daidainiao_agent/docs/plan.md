# 呆呆鸟助手 — 产品方向与前端计划

## 产品决策（当前实现）

**主界面 = 对话优先；工作台 = 辅助面板（并存，不收敛删除）。**

| 区域 | 角色 | 说明 |
|------|------|------|
| 侧栏 | 会话与工具入口 | 新建对话、历史、导入文档、设置；「工作台」为次级入口 |
| 主栏 | 流式问答 | `/ask-stream` SSE、思考步骤动画、证据折叠、引用跳转 |
| 工作台侧板 | 深度能力 | Tab：`evidence` 证据 · `documents` 知识库 · `lab` RAG Lab · `reading` 阅读 · `review` 综述 · `status` 状态（`workspace.js`） |
| 设置弹层 | 模型与检索 | 多配置档案、Top K、严格证据、重排、自我修正、主题 |

窄屏（≤768px）：侧栏 overlay；工作台全屏抽屉。中屏（769–1180px）：工作台右侧滑出。

---

## 布局（与 `index.html` 一致）

```
┌──────────┬────────────────────────────┬─────────────────┐
│  侧栏     │      对话主区域              │ 工作台（可收起）  │
│  232px   │  标题 + 状态条 + 消息区      │  Tab：证据/库/…  │
│          │  输入框 [停止] [发送]        │                  │
└──────────┴────────────────────────────┴─────────────────┘
```

移动端：仅侧栏 + 对话；工作台通过侧栏或顶栏按钮打开。

---

## 流式 UX（`stream.js` + `render/chat.js`）

| 时机 | UI |
|------|-----|
| 请求发出 | 用户气泡 + 助手气泡（思考指示器）；`#chat-stream-status` 显示状态 |
| 后端 `step` 事件 | 粗粒度：`retrieve` / `decompose` / `generate` / `cite`；检索子阶段：`tfidf` / `bm25` / `vector` / `fusion` / `rerank`（状态条 + 思考条联动） |
| 首个 `chunk` | 进入生成态，追加 delta |
| `final` | 隐藏思考 → Markdown 答案 + 证据片段 + 检索链路（details）；可选自动刷新工作台证据 |
| `error` / 断流 | 助手气泡内错误条 + **重试**；Toast 提示 |
| 用户点停止 | `AbortController`；有部分内容则保留并标注「已停止生成」 |

---

## 已完成

- [x] Claude 风格对话壳：侧栏、欢迎屏、消息气泡、Composer
- [x] SSE 流式与思考步骤动画
- [x] 证据片段折叠、引用 chip 跳转、检索链路 details
- [x] 产品工作台侧板（`workspace.js`）：证据 / 知识库 / RAG Lab / 阅读 / 综述 / 状态
- [x] 设置：模型档案、Top K、严格证据、重排、自我修正、主题、证据自动同步
- [x] 模型档案后端持久化（`model_profiles.py` + `GET/POST /settings/model`）
- [x] 设置内删除已导入文档；导入成功 5 秒可关提示
- [x] 会话消息截断 API（`POST /sessions/{id}/truncate`）
- [x] 多页 PDF 证据按 `(paper_id, section, locator)` 去重展示
- [x] 流式错误/中断：状态条、错误条、重试、停止按钮、Toast
- [x] 确认对话框（`confirm.js`）用于清空/删除会话
- [x] 欢迎屏快捷提问 chips
- [x] 响应式：768px 侧栏 overlay、工作台抽屉
- [x] 后端 SSE 粗粒度 pipeline 步骤（`retrieve` / `decompose` / `generate` / `cite`）
- [x] 检索子阶段 SSE（`hybrid.py` + `agent.py` `step_sink` → `stream.js`）
- [x] 工作台证据自动同步（`final` 后 `renderLatestEvidence`，设置可关）
- [x] 会话列表搜索 / 今天·更早分组
- [x] 深色模式（CSS 变量 + 设置 `system` / `light` / `dark`）
- [x] 导出回答 Markdown（`POST /export/markdown` + 复制/下载）
- [x] RAG Lab 一键 Baseline 与失败案例展示优化
- [x] 可选 API Token（`DAIDAINIAO_API_TOKEN` + Bearer 中间件）

---

## 待办（后续）

- [ ] 导出 PDF（浏览器打印或 `weasyprint` 等）
- [ ] 全局单例语料热更新 / 多 worker 限流（部署文档）
- [ ] Legacy `server.py` 弃用时间表

---

## 关键文件

| 文件 | 职责 |
|------|------|
| `frontend/index.html` | 壳结构：侧栏、对话、工作台、设置 |
| `frontend/app.js` | 提交、设置、上传、快捷键、欢迎 prompt |
| `frontend/stream.js` | SSE 读取、错误/停止/重试 |
| `frontend/workspace.js` | 工作台 Tab 与 API 调用 |
| `frontend/render/sessions.js` | 会话列表渲染与搜索 |
| `daidainiao_agent/agent.py` | 编排、流式 step、检索准备 |
| `daidainiao_agent/hybrid.py` | 混合检索与子阶段回调 |
| `daidainiao_agent/fastapi_server.py` | HTTP API |
| `daidainiao_agent/export.py` | Markdown 格式化 |
