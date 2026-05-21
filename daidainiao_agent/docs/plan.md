# 呆呆鸟助手 — 产品方向与前端计划

## 产品决策（当前实现）

**主界面 = 对话优先；工作台 = 辅助面板（并存，不收敛删除）。**

| 区域 | 角色 | 说明 |
|------|------|------|
| 侧栏 | 会话与工具入口 | 新建对话、历史、导入文档、设置；「工作台」为次级入口 |
| 主栏 | 流式问答 | `/ask-stream` SSE、思考步骤动画、证据折叠、引用跳转 |
| 工作台侧板 | 深度能力 | Tab：`evidence` 证据 · `documents` 知识库 · `lab` RAG Lab · `reading` 阅读 · `review` 综述 · `status` 状态（`workspace.js`） |
| 设置弹层 | 模型与检索 | 多配置档案、Top K、严格证据、重排 |

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
| 定时步骤 | 检索 → 分解 → 生成（模拟进度） |
| 首个 `chunk` | 进入生成态，追加 delta |
| `final` | 隐藏思考 → Markdown 答案 + 证据片段 + 检索链路（details） |
| `error` / 断流 | 助手气泡内错误条 + **重试**；Toast 提示 |
| 用户点停止 | `AbortController`；有部分内容则保留并标注「已停止生成」 |

---

## 已完成

- [x] Claude 风格对话壳：侧栏、欢迎屏、消息气泡、Composer
- [x] SSE 流式与思考步骤动画
- [x] 证据片段折叠、引用 chip 跳转、检索链路 details
- [x] 产品工作台侧板（`workspace.js`）：证据 / 知识库 / RAG Lab / 阅读 / 综述 / 状态
- [x] 设置：模型档案、Top K、严格证据、重排、文档列表
- [x] 模型档案后端持久化（`model_profiles.py` + `GET/POST /settings/model`）
- [x] 设置内删除已导入文档；导入成功 5 秒可关提示
- [x] 会话消息截断 API（`POST /sessions/{id}/truncate`）
- [x] 多页 PDF 证据按 `(paper_id, section, locator)` 去重展示
- [x] 流式错误/中断：状态条、错误条、重试、停止按钮、Toast
- [x] 确认对话框（`confirm.js`）用于清空/删除会话
- [x] 欢迎屏快捷提问 chips
- [x] 响应式：768px 侧栏 overlay、工作台抽屉

---

## 待办（按优先级）

- [ ] 后端 SSE 推送真实 pipeline 步骤（替代前端定时模拟）
- [ ] 工作台与当前会话证据自动同步（回答完成后可选自动展开）
- [ ] 会话列表搜索 / 分组
- [ ] 深色模式
- [ ] 导出回答（Markdown / PDF）接回 `export` API

---

## 关键文件

| 文件 | 职责 |
|------|------|
| `frontend/index.html` | 壳结构：侧栏、对话、工作台、设置 |
| `frontend/app.js` | 提交、设置、上传、快捷键、欢迎 prompt |
| `frontend/stream.js` | SSE 读取、错误/停止/重试 |
| `frontend/render/chat.js` | 消息与证据渲染 |
| `frontend/workspace.js` | 工作台各 Tab |
| `frontend/styles.css` | 布局与组件样式 |
| `frontend/state.js` | 会话/设置/ DOM 引用 |
| `frontend/api.js` | REST 封装 |
| `frontend/confirm.js` | 确认弹层 |
| `frontend/handlers/sidebar.js` | 侧栏开合、窄屏 overlay、localStorage 记忆 |

---

## 验证

1. 启动：`python -m daidainiao_agent.cli serve`
2. 打开 `http://localhost:8000`
3. 检查：提问 → 思考动画 → 流式文字 → 证据折叠；断网/停生成 → 错误条或停止提示；侧栏历史；工作台 Tab；设置保存；窄屏侧栏与抽屉
