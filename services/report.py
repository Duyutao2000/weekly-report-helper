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

from core.models import Report
from datetime import timedelta
from services.task import get_completed_tasks_by_week
from services.llm import generate_report

logger = logging.getLogger(__name__)


def _build_task_tree(tasks: list) -> tuple[list, dict]:
    """
    将扁平任务列表按 parent_id 构建为树结构。

    返回:
        (roots, children_map)
        - roots: 根节点列表（父节点不在本批次中的任务）
        - children_map: {parent_id: [子任务列表]}，按完成时间排序
    """
    task_ids = {t.id for t in tasks}

    children_map: dict = {}
    roots = []
    for t in tasks:
        if t.parent_id is not None and t.parent_id in task_ids:
            children_map.setdefault(t.parent_id, []).append(t)
        else:
            roots.append(t)

    # 每个父节点下的子任务按完成时间排序
    for pid in children_map:
        children_map[pid].sort(key=lambda c: c.completed_at or c.created_at)

    return roots, children_map


def _render_task_node(
    task,
    children_map: dict,
    index: int,
    indent_level: int = 0,
) -> str:
    """
    递归渲染树节点为文本行。

    格式:
        N. 父任务描述 (Xh)
           - 子任务描述 (Xh)
    """
    indent = "  " * indent_level
    hours_str = f"{task.hours:.1f}h" if task.hours is not None else "工时未填"

    if indent_level == 0:
        line = f"{indent}{index}. {task.description} ({hours_str})"
    else:
        line = f"{indent}- {task.description} ({hours_str})"

    lines = [line]
    children = children_map.get(task.id, [])
    for child in children:
        lines.append(_render_task_node(child, children_map, 0, indent_level + 1))
    return "\n".join(lines)


def _build_tasks_text(tasks: list) -> str:
    """
    将已完成任务列表按父子层级构建为 prompt 输入文本。

    总工时仅统计根节点（其 hours 已自动汇总所有子孙），避免重复计算。
    子任务的父节点不在本批次时，子任务自动提升为根节点。
    """
    from collections import OrderedDict

    roots, children_map = _build_task_tree(tasks)

    # 按项目分组（仅根节点参与分组）
    grouped = OrderedDict()
    for t in roots:
        proj_name = t.project.name
        if proj_name not in grouped:
            grouped[proj_name] = {"roots": [], "total": 0.0}
        grouped[proj_name]["roots"].append(t)
        grouped[proj_name]["total"] += t.hours or 0

    lines = []
    for proj_name, data in grouped.items():
        lines.append(f"【{proj_name}】总工时：{data['total']:.1f}h")
        for i, root in enumerate(data["roots"], 1):
            lines.append(_render_task_node(root, children_map, i, indent_level=0))
        lines.append("")
    return "\n".join(lines)


def _build_plan_text(plans: list) -> str:
    """
    将计划列表构建为 prompt 输入文本。

    按项目分组，编号列表，简洁格式。
    """
    from collections import OrderedDict

    # 按项目分组（保持顺序）
    grouped = OrderedDict()
    for p in plans:
        proj_name = p.project.name
        if proj_name not in grouped:
            grouped[proj_name] = []
        grouped[proj_name].append(p)

    lines = []
    for proj_name, items in grouped.items():
        lines.append(f"【{proj_name}】")
        for i, p in enumerate(items, 1):
            lines.append(f"  {i}. {p.description}")
        lines.append("")
    return "\n".join(lines)


def generate_weekly_report(
    session: Session,
    week_start: date,
    week_end: date,
) -> Report:
    """
    生成周报（包含本周完成 + 下周计划）。

    流程：
    1. 查询当周已完成任务
    2. 前置校验：无可完成任务则报错
    3. 查询下周计划（如有）
    4. 构建 prompt → 调用 LLM（同时生成本周周报和下周计划）
    5. 保存到 reports 表（含 task_ids 快照）

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

    # 3. 查询下周计划（下周 = 本周一 + 7 天）
    from services.plan import get_plans_by_target_week
    next_ws = week_start + timedelta(days=7)
    next_we = week_end + timedelta(days=7)
    plans = get_plans_by_target_week(session, next_ws, next_we)

    # 4. 构建 prompt
    tasks_text = _build_tasks_text(tasks)
    plans_text = _build_plan_text(plans) if plans else "（暂无下周计划）"
    logger.info(f"生成周报：{len(tasks)} 个已完成任务，{len(plans)} 个下周计划")

    # 5. 调用 LLM
    content = generate_report(tasks_text, plans_text)

    # 6. 保存到 reports 表
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
