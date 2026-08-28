# 重塑差距分析

基于 [Engineering Precision] 设计方案 vs 现有应用功能的逐项对比。

---

## 一、架构层

| 维度 | 现有 | 设计目标 | 差距 |
|------|------|----------|------|
| **前端框架** | Gradio 5（单页 Tab） | 混合路线：Gradio 作 API 网关 + 后端渲染入口，前端用 **Alpine.js**（CDN 引入 ~15KB）在 `gr.HTML()` 内实现响应式组件 | **中** — 现有架构可行，需定义前后端通信契约 |
| **数据持久化** | SQLAlchemy → SQLite | ✅ 统一保留 SQLite。放弃 localStorage，**不存在两套存储** | 无差距 — 数据一致性优先，离线通过 Service Worker 实现 |
| **页面划分** | 4 个 Tab（看板/历史/设置 + 计划内嵌） | 3 个页面（/tasks, /stats, /projects）通过 **hash 路由** 切换（`/#/tasks`），兼容 Gradio 单页架构 | **中** — hash 路由可模拟页面切换 |
| **数据共享** | 服务端 session | ✅ 保留服务端 session + API 请求 | 无差距 — 所有 Service 层代码可复用 |
| **前端后端通信** | Gradio 原生事件链（`js_cmd_box` + `js_trigger`） | **REST API**（`fetch` + JSON），定义显式 API 契约 | **中** — 需新写 API 路由层，废弃现有通信通道 |
| **构建/部署** | 需 Python 环境 | ✅ 不变。Alpine.js + ECharts 均通过 CDN 引入，无需 npm/webpack | 无差距 |

---

## 二、功能层

### 2.1 我的待办（/tasks）

| 功能 | 现有状态 | 目标要求 | 差距 |
|------|---------|---------|------|
| **树形任务列表** | ✅ 有（`<details>/<summary>`） | ✅ 有（缩进 + 展开/折叠箭头 + `└─` 连接符） | 小 — 渲染方式不同 |
| **勾选完成 → 置灰划线** | ✅ 有 | ✅ 有 | 无差距 |
| **新增任务弹窗** | ❌ 行内表单 | ✅ 弹窗表单（名称/描述/项目/预估工时/实际工时/截止日期/状态/父任务选择） | **大** — 字段差 6 个 |
| **编辑任务弹窗** | ❌ 行内编辑（仅名称+工时） | ✅ 与新建共用弹窗，预填，父任务防循环校验 | **大** — 功能严重不足 |
| **删除任务** | ✅ 单条软删除，确认弹窗提示子任务一并删除 | ✅ 单条 + 批量删除，确认弹窗 | 中 — 缺批量删除、批量完成、批量移动项目 |
| **多维筛选** | ⚠️ 有历史查询（周范围+项目+状态+关键词） | ✅ 搜索框（匹配名称+描述）+ 项目/状态 两个 Select | 中 — 缺实时过滤 |
| **预估/实际工时** | ❌ 只有单 hours 字段 | ✅ 两个字段，用于偏差计算 | **大** — 数据模型需拆分为二 |
| **截止日期** | ❌ 只有 week_start/week_end | ✅ 单 due_date | 中 — 字段语义不同 |
| **底部统计栏** | ❌ 无 | ✅ 总任务数 / 已完成数 / 完成率进度条 | **大** — 全新组件 |
| **防循环校验（父任务）** | ❌ 无（仅 parent_id 自引用） | ✅ 父任务下拉自动排除自身及子孙 | 中 — 新校验逻辑 |
| **父任务完成逻辑** | ⚠️ 现有是"子全完成→自动完成父" | ✅ 统一规则：父完成时所有子任务自动完成；禁止直接勾选父（需从子操作） | 中 — 需修改现有逻辑 |
| **任务排序/拖拽** | ❌ 无 | ✅ `sort_order` 字段 + 拖拽交互 | **大** — 全新字段 + UI |
| **逾期高亮** | ❌ 无 | ✅ due_date 过期任务红色标识，/stats 页单独统计 | 中 — 全新 |
| **键盘快捷键** | ❌ 无 | ✅ N 新建 / E 编辑 / / 搜索 / Esc 关闭弹窗 | 小 — 纯前端 |
| **空状态** | ❌ 无 | ✅ 无任务时显示空状态文案/引导 | 小 — 纯前端 |
| **数据导入/导出** | ⚠️ 有 markdown 导出 | ✅ JSON/CSV 全量导入导出 | 中 — 数据安全必备 |
| ~~优先级 P0-P3~~ | — | ❌ 暂不需要 | 已取消 |

### 2.2 工时统计（/stats）

| 功能 | 现有状态 | 目标要求 | 差距 |
|------|---------|---------|------|
| **时间维度切换** | ❌ 只有周维度 | ✅ 今日/本周/本月/全部 四个 Tab | **大** — 全新 |
| **KPI 卡片** | ❌ 无 | ✅ 总预估工时 / 总实际工时 / 工时偏差（红/绿） | **大** — 全新 |
| **项目工时柱状图** | ❌ 无 | ✅ ECharts 分组柱状图（每个项目两柱：预估 vs 实际） | **大** — 全新 |
| **项目完成率** | ⚠️ 没有可视化进度条 | ✅ 每行进度条（≥90% 绿 / 60-89% 黄 / <60% 红） | **大** — 全新 |

### 2.3 项目管理（/projects）

| 功能 | 现有状态 | 目标要求 | 差距 |
|------|---------|---------|------|
| **项目 CRUD** | ✅ 有（设置 Tab 内） | ✅ 独立页面 | 中 — 位置不同，功能需增强 |
| **行内编辑重命名** | ✅ 有 | ✅ 回车保存 / Esc 取消 | 小 — 现有交互略有不同 |
| **删除确认 + 关联任务归为"未分类"** | ❌ 现有是硬删除 | ✅ 删除后任务保留，归入"未分类" | **大** — 完全不同 |
| **项目维度统计表** | ❌ 无 | ✅ 项目名 / 任务数 / 完成率 / 预估工时 / 实际工时 | **大** — 全新 |

---

## 三、数据模型层

### 3.1 Task 字段对比

| 字段 | 现有 | 目标 | 变动 |
|------|------|------|------|
| id | ✅ | ✅ | — |
| description | ✅ | ✅ | — |
| project_id | ✅（FK→projects） | ✅ **保留 FK→projects** | —。删除项目时 `SET NULL`，任务归"未分类" |
| parent_id | ✅ | ✅ | — |
| sort_order | ❌ | ✅ `INTEGER DEFAULT 0` | **新增** — 拖拽排序 |
| is_expanded | ❌ | ✅ `BOOLEAN DEFAULT true` | **新增** — 树形折叠状态持久化 |
| status | ✅ (pending/completed) | ✅ | — |
| hours | ✅ (单个，可为 NULL) | ❌ 拆分为 estimated_hours + actual_hours | **拆字段**。两字段均允许 NULL，NULL ≠ 0 |
| due_date | ❌ (只有 week_start/week_end) | ✅ 单截止日期 | **替换字段** |
| created_at | ✅ | ✅ | — |
| updated_at | ✅ | ✅（用于冲突检测） | — |
| completed_at | ✅ | ✅ 保留 | — |
| deleted_at | ❌（只有 is_deleted） | ✅ `DATETIME NULL` | **增强** — 从 is_deleted 布尔值改为时间戳，支持回收站 |
| week_start / week_end | ✅ | ❌ 不适用 | **移除字段** |

> **NULL 语义**：`estimated_hours IS NULL` = "尚未预估"，`actual_hours IS NULL` = "尚未记录"。0 是合法值（0h 任务）。
>
> **软删除统一**：所有删除使用软删除（deleted_at 时间戳）。项目删除 → 关联任务 `project_id = NULL`（显示"未分类"），任务保留。任务删除 → 标记 `deleted_at`，支持回收站恢复。

### 3.2 存储层（统一为 SQLite）

| 维度 | 现有 | 目标 |
|------|------|------|
| **引擎** | SQLite via SQLAlchemy | ✅ **保留 SQLite**。放弃 localStorage，不存在两套数据 |
| **表数** | 5 张表 | 4-5 张（合并 Task 字段，视情况保留 plan/report/setting） |
| **同步机制** | 服务端 session 提交 | ✅ 保留 |
| **离线能力** | 无 | ⚠️ 非必需。后续可通过 Service Worker 缓存 API 响应实现 |

---

## 四、视觉与交互层

### 4.1 配色体系

| Token | 现有 | 目标 |
|-------|------|------|
| **底色** | `#fff` / `#f8f8f8` 暖白 | 冷灰白底 |
| **主色** | `#2e7d32` 绿 | `HSL(222, 88%, 51%)` 靛蓝 |
| **文字** | `#000` / `#333` / `#666` | 深墨色 |
| **边框** | `#ddd` / `#e0e0e0` | 辅助色（极浅灰） |
| **阴影** | 少量 | `shadow-none`，仅靠边框与背景色差 |
| **已完成** | 灰色 + 删除线 + 绿色勾 | 灰色 + 删除线（**不用绿色**） |


### 4.2 字体与排版

| Token | 现有 | 目标 |
|-------|------|------|
| **中文字体** | Songti SC / Noto Serif SC | **Noto Sans SC**（无衬线） |
| **英文 UI 字体** | Times New Roman / Noto Serif SC | **Inter** |
| **工时数字** | 常规字体 | **等宽字体**（tabular-nums） |
| **字号层级** | 14px 统一 | text-2xl / text-sm / text-xs |
| **行高** | 未明确 | leading-6 |
| **组件间距** | 未明确 | gap-3 |

### 4.3 视觉细节

| 特征 | 现有 | 目标 |
|------|------|------|
| **圆角** | 3-4px | `rounded-sm`（2px） |
| **树形连接符** | ❌ 无（用 details/summary ▶） | ✅ `└─` 竖线连接符 |
| **动效** | `transition: opacity 0.1s` | checkbox 勾选缩放 95%、树形展开 height transition 150ms |
| **列表可扫描性** | 中等 | 高密度、低干扰任务控制台 |

### 4.4 布局

| 特征 | 现有 | 目标 |
|------|------|------|
| **整体布局** | 单列流式 | Sidebar + Main Content 左右分栏 |
| **内容区宽度** | 自适应 | max-w-5xl |
| **弹窗宽度** | 无弹窗 | 新建/编辑 max-w-xl |

---

## 五、设计禁忌检查

| 禁忌 | 现状 |
|------|------|
| ❌ 大圆角（rounded-xl） | 现有 3-4px，接近 rounded-sm（2px），需微调 |
| ❌ 装饰性插图/渐变 Banner | 现有无，保持 |
| ❌ 自定义非标准 token | 现有用硬编码色值，需转为设计 token 体系 |

---

## 六、可保留/需迁移的现有模块

| 模块 | 建议 |
|------|------|
| **下周计划** | 设计规格未提及，可保留或在 /tasks 中合并 |
| **周范围切换** | 设计规格无周概念，需重新审视 |
| **SQLite 持久化** | ✅ 保留。混合路线下后端 + 数据库不变 |
| **Service 层** | ✅ 保留。Python 服务层全部可复用 |
| **LLM 周报生成** | ✅ 保留。API Key 在后端不暴露 |
| **数据迁移脚本** | ❌ 无 | ✅ 必需。启动时自动检测旧 schema，执行 ALTER TABLE 和字段拆分（hours→estimated/actual，week_start/week_end→due_date，is_deleted→deleted_at） |

---

## 七、API 设计（REST 契约）

混合路线下，Gradio 内嵌 Alpine.js 前端通过 `fetch` 调用后端 API。需新写 API 路由层（可用 FastAPI 或 Gradio 内置 `gr.Request`），废弃现有的 `js_cmd_box` + `js_trigger` 通信通道。

### 最小 API 集合

```
GET    /api/tasks?project=&status=&q=&sort=         # 任务列表（支持筛选+排序）
POST   /api/tasks                                    # 创建任务
PUT    /api/tasks/{id}                               # 更新任务
DELETE /api/tasks/{id}                               # 软删除
POST   /api/tasks/batch-delete                       # 批量删除
POST   /api/tasks/batch-update                       # 批量完成/移动项目
GET    /api/tasks/tree                               # 树形结构（含子孙）
PUT    /api/tasks/{id}/sort                          # 更新排序

GET    /api/projects                                 # 项目列表
POST   /api/projects                                 # 创建项目
PUT    /api/projects/{id}                            # 重命名
DELETE /api/projects/{id}                            # 删除（任务归"未分类"）

GET    /api/stats?range=today|week|month|all          # 统计数据
POST   /api/report                                   # LLM 周报生成
GET    /api/export?format=json|csv                    # 数据导出
POST   /api/import                                   # 数据导入
```

### 前端技术选型确认

| 维度 | 决策 |
|------|------|
| **前端框架** | **Alpine.js**（CDN 引入 ~15KB，声明式响应式，无需构建步骤，适合 Gradio 内嵌） |
| **路由方案** | **hash 路由**（`/#/tasks`, `/#/stats`, `/#/projects`），兼容 Gradio 单页架构 |
| **图表库** | **ECharts**（CDN 按需加载，仅在 `/stats` 页面动态注入 `<script>`） |
| **后端** | ✅ 保留 Gradio（利用其内置 FastAPI 路由挂载 `/api/*` 端点） |
| **项目结构** | `app.py` 仅保留 Gradio 启动 + API 路由注册；前端代码独立为 `static/` 目录 |

---

## 八、优先级建议

### P0 — 架构基础（必须先做）
1. 确认最终架构决策（已完成：SQLite + Alpine.js + hash 路由 + REST API）
2. 定义 API 契约（按 Section 七设计）
3. 编写数据迁移脚本（启动时自动转换旧数据）

### P1 — 核心功能改造
4. 重构 Task 数据模型（hours 拆分 + due_date + sort_order + deleted_at 替换 is_deleted）
5. 实现 REST API 路由层（替代 `js_cmd_box` 通信）
6. 前端框架搭建（Alpine.js 初始化 + hash 路由 + Sidebar + Main 布局）
7. 配色 + 字体体系替换（CSS 变量系统）

### P2 — 页面功能实现
8. 我的待办页：弹窗表单 + 树形渲染 + 多维筛选 + 底部统计栏 + 删除/排序/逾期高亮
9. 工时统计页：KPI 卡片 + ECharts 柱状图 + 完成率进度条 + 时间维度切换
10. 项目管理页：独立页面 + 行内重命名 + 项目统计表 + 删除归"未分类"

### P3 — 体验打磨
11. 树形 └─ 连接符替换 details/summary
12. 动效（checkbox 缩放、树形展开 transition）
13. 键盘快捷键（N/E//Esc） + 空状态 UI
14. 数据导入/导出（JSON/CSV）
