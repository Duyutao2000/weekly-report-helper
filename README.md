# 📊 个人周报助手

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Gradio](https://img.shields.io/badge/Gradio-5.x-orange.svg)](https://www.gradio.app/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-green.svg)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

本地待办事项管理工具，支持每周任务追踪、下周计划管理，并可一键调用 LLM 生成书面化周报。

## ✨ 功能

- **树形任务看板** — 项目-任务-子任务三级嵌套，可折叠/展开，复选框标记完成，行内编辑名称和工时
- **项目与任务隔离** — 项目库在设置页统一管理；任务看板中删除操作仅清除当前周任务，不影响项目本身
- **周期切换** — 自定义周范围，历史任务持久化，切换周期只切换视图不丢数据
- **下周计划** — 当周填写下周计划，下周自动弹窗提醒同步，免重复录入
- **周报生成** — LLM 一键生成书面化周报，保留技术细节（表名、字段名、方案名），支持 DeepSeek / 千问 / GPT
- **历史查询** — 按周范围、项目、状态、关键词多条件筛选

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Conda（推荐）或 venv

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd weekly-report-helper

# 创建并激活环境（env_name 替换为你的环境名）
conda create -n <env_name> python=3.12 -y
conda activate <env_name>

# 安装依赖
pip install -r requirements.txt
```

### 配置 LLM API

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API Key：

```env
LLM_API_KEY=sk-your-api-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

支持所有 OpenAI 兼容接口（DeepSeek、通义千问、智谱、OpenAI 等），只需修改 `LLM_BASE_URL` 和 `LLM_MODEL`。

### 启动

```bash
python app.py
```

浏览器打开 `http://127.0.0.1:7860`。

## 📖 使用指南

### 1. 初始设置

进入「⚙ 设置」页签，创建项目。

### 2. 本周任务

在「🏠 任务看板」中：
- 点击项目节点的 **➕** 新增子任务，填写描述和工时
- 勾选复选框标记完成，点击工时数字修改工时
- 完成后点击「🤖 生成周报」

### 3. 下周计划

切换到「📅 下周计划」标签：
- 添加计划任务（无需填写工时）
- 切换到下周时会自动弹窗提醒同步

### 4. 历史回顾

「📋 历史任务」页签支持按周期、项目、状态、关键词组合查询。

## 📁 项目结构

```
weekly-report-helper/
├── app.py                    # Gradio 主界面
├── core/
│   └── models.py             # SQLAlchemy 数据模型 + DB 初始化
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量模板
├── start.bat                 # Windows 快速启动脚本
├── services/
│   ├── project.py            # 项目 CRUD
│   ├── task.py               # 任务 CRUD + 状态流转
│   ├── plan.py               # 下周计划 + 同步逻辑
│   ├── report.py             # 周报/计划生成
│   └── llm.py                # LLM API 调用 + 自动重试
├── utils/
│   └── retry.py              # 指数退避重试策略
├── templates/
│   ├── report_prompt.txt     # 周报生成 Prompt
│   └── plan_prompt.txt       # 计划生成 Prompt
└── data/                     # 运行时数据（自动创建）
    ├── todo.db               # SQLite 数据库
    └── app.log               # 应用日志
```

## 🔧 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| Web UI | Gradio 5 | 单页应用，内嵌 HTML/JS 树形组件 |
| ORM | SQLAlchemy 2.0 | 五表模型，带关系预加载 |
| 数据库 | SQLite | 本地单文件，零配置 |
| LLM SDK | OpenAI | 兼容多厂商（DeepSeek / 千问 / GPT） |
| 重试策略 | 指数退避 + Full Jitter | 自动区分可重试/不可重试错误 |

## 📝 数据模型

```
projects ──1:N── tasks         (任务，含软删除、状态流转)
projects ──1:N── next_week_plans (下周计划，带 synced_at 追踪)
reports                        (周报，含 task_ids 快照)
settings                       (键值对全局配置)
```

## 📄 License

MIT
