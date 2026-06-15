"""
周报生成服务

负责：
  1. 构建 LLM prompt 输入（按项目分组 + 工时汇总）
  2. 调用 LLM 生成周报文本
  3. 保存到 reports 表（含 task_ids 快照）
  4. 前置校验：当周无已完成任务时拒绝生成
"""

import json
import logging
from datetime import date

from sqlalchemy.orm import Session

from models import Report
from services.task import get_completed_tasks_by_week
from services.llm import generate_report

logger = logging.getLogger(__name__)


def _build_tasks_text(tasks: list) -> str:
    """
    将已完成任务列表构建为 prompt 输入文本。

    输出格式：
    【项目名】总工时：XXh
    1. 任务描述 (Xh)
    2. 任务描述 (Xh)
    """
    from collections import defaultdict, OrderedDict

    # 保持项目顺序
    grouped = OrderedDict()
    for t in tasks:
        if t.project.name not in grouped:
            grouped[t.project.name] = {"tasks": [], "total": 0.0}
        grouped[t.project.name]["tasks"].append(t)
        grouped[t.project.name]["total"] += t.hours or 0

    lines = []
    for proj_name, data in grouped.items():
        lines.append(f"【{proj_name}】总工时：{data['total']:.1f}h")
        for i, t in enumerate(data["tasks"], 1):
            hours_str = f"{t.hours}h" if t.hours is not None else "工时未填"
            lines.append(f"  {i}. {t.description} ({hours_str})")
        lines.append("")
    return "\n".join(lines)


def _build_plan_text(plans: list) -> str:
    """
    将计划列表构建为 prompt 输入文本。
    """
    from collections import defaultdict
    grouped = defaultdict(list)
    for p in plans:
        grouped[p.project.name].append(p)

    lines = []
    for proj_name in grouped:
        lines.append(f"项目：{proj_name}")
        for p in grouped[proj_name]:
            lines.append(f"  - {p.description}")
        lines.append("")
    return "\n".join(lines)


def generate_weekly_report(
    session: Session,
    week_start: date,
    week_end: date,
) -> Report:
    """
    生成周报。

    流程：
    1. 查询当周已完成任务
    2. 前置校验：无可完成任务则报错
    3. 构建 prompt → 调用 LLM
    4. 保存到 reports 表（含 task_ids 快照）

    参数:
        week_start: 周开始日期
        week_end: 周结束日期

    返回:
        新创建的 Report 对象

    异常:
        ValueError: 当周无已完成任务
        RuntimeError: LLM 调用失败
    """
    # 1. 查询已完成任务
    tasks = get_completed_tasks_by_week(session, week_start, week_end)

    # 2. 前置校验
    if not tasks:
        raise ValueError("本周没有已完成的任务，无法生成周报")

    # 3. 构建 prompt
    tasks_text = _build_tasks_text(tasks)
    logger.info(f"生成周报：{len(tasks)} 个已完成任务")

    # 4. 调用 LLM
    content = generate_report(tasks_text)

    # 5. 保存到 reports 表
    task_ids = json.dumps([t.id for t in tasks], ensure_ascii=False)
    report = Report(
        week_start=week_start,
        week_end=week_end,
        content=content,
        task_ids=task_ids,
    )
    session.add(report)
    session.commit()

    logger.info(f"周报已保存: report_id={report.id}, tasks={task_ids}")
    return report


def generate_weekly_plan(
    session: Session,
    week_start: date,
    week_end: date,
    plans: list | None = None,
) -> str:
    """
    生成下周计划文本（不写入数据库，仅返回 LLM 结果）。

    前置校验：plans 列表不能为空。

    参数:
        week_start: 目标周开始日期
        week_end: 目标周结束日期
        plans: 计划对象列表（如未提供则从数据库查询）

    返回:
        LLM 生成的计划文本

    异常:
        ValueError: 无计划数据
        RuntimeError: LLM 调用失败
    """
    # 如果未传入 plans，从数据库查询
    if plans is None:
        from services.plan import get_plans_by_target_week
        plans = get_plans_by_target_week(session, week_start, week_end)

    if not plans:
        raise ValueError("没有下周计划数据，请先添加计划")

    tasks_text = _build_plan_text(plans)
    logger.info(f"生成计划：{len(plans)} 个计划任务")

    return generate_plan(tasks_text)


def get_latest_report(
    session: Session,
    week_start: date,
    week_end: date,
) -> Report | None:
    """
    获取指定周的最新周报。

    参数:
        week_start: 周开始日期
        week_end: 周结束日期

    返回:
        Report 对象或 None
    """
    return (
        session.query(Report)
        .filter(
            Report.week_start == week_start,
            Report.week_end == week_end,
        )
        .order_by(Report.created_at.desc())
        .first()
    )
