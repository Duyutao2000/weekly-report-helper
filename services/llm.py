"""
大模型 API 调用服务

使用 OpenAI 兼容 SDK，通过环境变量配置 API Key / Base URL / Model。
支持自动重试（指数退避 + 抖动），错误分类处理。
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

from utils.retry import with_retry, categorize_error, backoff_delay

logger = logging.getLogger(__name__)

# 加载 .env
load_dotenv()

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")

# ──────────────────────────────────────────────
# Prompt 模板加载
# ──────────────────────────────────────────────
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _load_template(filename: str) -> str:
    """加载 prompt 模板文件"""
    path = TEMPLATES_DIR / filename
    if not path.exists():
        logger.warning(f"模板文件不存在: {path}")
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ──────────────────────────────────────────────
# 核心调用
# ──────────────────────────────────────────────
@with_retry
def _call_api(prompt: str, system_prompt: str = "") -> str:
    """
    单次 LLM API 调用（含重试装饰器）。

    参数:
        prompt: 用户 prompt
        system_prompt: 系统角色设定

    返回:
        模型生成的文本

    异常:
        ValueError: API Key 未配置
        RuntimeError: 重试耗尽
        TimeoutError: 总超时
    """
    if not LLM_API_KEY:
        raise ValueError("LLM_API_KEY 未配置，请在 .env 文件中设置")

    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
    )

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    logger.info(f"调用 LLM: model={LLM_MODEL}, prompt 长度={len(prompt)}")

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.3,  # 低温度，偏向确定性输出（非思考模式下生效）
        max_tokens=2048,
        extra_body={"thinking": {"type": "disabled"}},  # 显式关闭思考模式，避免浪费 token
    )

    content = response.choices[0].message.content or ""
    logger.info(f"LLM 返回: 长度={len(content)}")
    return content


# ──────────────────────────────────────────────
# 业务接口
# ──────────────────────────────────────────────
def generate_report(tasks_text: str, plans_text: str = "") -> str:
    """
    生成周报。

    参数:
        tasks_text: 按格式组织的已完成任务文本
        plans_text: 按格式组织的下周计划文本（可为空）

    返回:
        大模型生成的周报内容

    异常:
        ValueError: API Key 未配置
        RuntimeError: LLM 调用失败
    """
    template = _load_template("report_prompt.txt")
    prompt = template.replace("{tasks}", tasks_text).replace("{plans}", plans_text)
    return _call_api(prompt, system_prompt="你是一个专业的周报撰写助手，擅长将技术开发任务转化为书面化、成果导向的周报。你始终保留所有技术细节（表名、字段名、技术方案、系统名），只润色语言表达。")


def generate_plan(tasks_text: str) -> str:
    """
    生成下周计划文本。

    参数:
        tasks_text: 按格式组织的计划任务文本

    返回:
        大模型生成的计划内容

    异常:
        ValueError: API Key 未配置
        RuntimeError: LLM 调用失败
    """
    template = _load_template("plan_prompt.txt")
    prompt = template.replace("{tasks}", tasks_text)
    return _call_api(prompt, system_prompt="你是一个专业的计划撰写助手。")
