"""
任务 CRUD 服务

提供任务的增删改查、完成/撤销、历史查询功能。
工时精度：0.5h，应用层负责入参校验和舍入。
"""

from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from models import Task, Project


# ──────────────────────────────────────────────
# 工时精度校验
# ──────────────────────────────────────────────
ALLOWED_HOURS = frozenset(round(i * 0.5, 1) for i in range(0, 161))  # 0 ~ 80h 以 0.5 为步长


def validate_hours(hours: float | None) -> float | None:
    """
    校验并舍入工时到最近的 0.5。

    参数:
        hours: 原始工时值（可为 None）

    返回:
        舍入后的工时（float），None 保持 None

    异常:
        ValueError: 工时 < 0
    """
    if hours is None:
        return None
    if hours < 0:
        raise ValueError("工时不能为负数")
    rounded = round(hours * 2) / 2  # 舍入到最近 0.5
    return max(0.0, rounded)


# ──────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────
def get_task(session: Session, task_id: int) -> Task | None:
    """按 ID 获取任务（不含已删除）"""
    return (
        session.query(Task)
        .filter(Task.id == task_id, Task.is_deleted == False)
        .first()
    )


def get_tasks_by_week(
    session: Session,
    week_start: date,
    week_end: date,
    include_deleted: bool = False,
) -> list[Task]:
    """
    按周获取任务列表。

    参数:
        week_start: 周开始日期
        week_end: 周结束日期
        include_deleted: 是否包含已删除任务（历史页面可能不需要）

    返回:
        任务列表（按项目、创建时间排序）
    """
    q = session.query(Task).filter(
        Task.week_start == week_start,
        Task.week_end == week_end,
    )
    if not include_deleted:
        q = q.filter(Task.is_deleted == False)
    return (
        q.join(Project)
        .order_by(Project.created_at.asc(), Task.created_at.asc())
        .all()
    )


def get_completed_tasks_by_week(
    session: Session,
    week_start: date,
    week_end: date,
) -> list[Task]:
    """按周获取已完成任务（用于周报生成）"""
    return (
        session.query(Task)
        .filter(
            Task.week_start == week_start,
            Task.week_end == week_end,
            Task.status == "completed",
            Task.is_deleted == False,
        )
        .join(Project)
        .order_by(Project.created_at.asc(), Task.completed_at.asc())
        .all()
    )


def get_tasks_grouped_by_project(
    session: Session,
    week_start: date,
    week_end: date,
) -> dict[int, dict]:
    """
    按项目分组获取当前周任务。

    返回:
        {project_id: {"project": Project, "tasks": [Task], "total_hours": float}}
    """
    tasks = get_tasks_by_week(session, week_start, week_end)
    grouped: dict[int, dict] = {}
    for t in tasks:
        pid = t.project_id
        if pid not in grouped:
            grouped[pid] = {
                "project": t.project,
                "tasks": [],
                "total_hours": 0.0,
            }
        grouped[pid]["tasks"].append(t)
        if t.hours:
            grouped[pid]["total_hours"] += t.hours
    # 计算每个项目的工时总和（保留一位小数）
    for v in grouped.values():
        v["total_hours"] = round(v["total_hours"], 1)
    return grouped


def get_all_tasks(
    session: Session,
    week_start: date | None = None,
    week_end: date | None = None,
    project_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[Task]:
    """
    历史任务查询（支持多条件筛选）。

    参数:
        week_start/week_end: 周范围过滤（可选）
        project_id: 项目过滤（可选）
        status: 状态过滤 pending/completed（可选）
        keyword: 描述关键词搜索（可选，LIKE 模糊匹配）

    返回:
        筛选后的任务列表（按周倒序 + 项目 + 创建时间）
    """
    q = session.query(Task).filter(Task.is_deleted == False)

    if week_start:
        q = q.filter(Task.week_start >= week_start)
    if week_end:
        q = q.filter(Task.week_end <= week_end)
    if project_id:
        q = q.filter(Task.project_id == project_id)
    if status:
        q = q.filter(Task.status == status)
    if keyword:
        q = q.filter(Task.description.like(f"%{keyword}%"))

    return (
        q.join(Project)
        .options(joinedload(Task.project))
        .order_by(Task.week_start.desc(), Project.created_at.asc(), Task.created_at.asc())
        .all()
    )


# ──────────────────────────────────────────────
# 写操作
# ──────────────────────────────────────────────
def create_task(
    session: Session,
    project_id: int,
    description: str,
    hours: float | None,
    week_start: date,
    week_end: date,
) -> Task:
    """
    新增任务。

    参数:
        project_id: 项目 ID
        description: 任务描述（不可为空）
        hours: 工时（可为 None，表示待填写）
        week_start: 周开始日期
        week_end: 周结束日期

    返回:
        新创建的 Task 对象

    异常:
        ValueError: 描述为空、项目不存在、工时校验失败
    """
    desc = description.strip()
    if not desc:
        raise ValueError("任务描述不能为空")

    # 校验项目存在
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")

    validated_hours = validate_hours(hours)

    task = Task(
        project_id=project_id,
        description=desc,
        hours=validated_hours,
        status="pending",
        week_start=week_start,
        week_end=week_end,
    )
    session.add(task)
    session.commit()
    return task


def update_task(
    session: Session,
    task_id: int,
    project_id: int | None = None,
    description: str | None = None,
    hours: float | None = None,
) -> Task:
    """
    编辑任务。

    仅允许编辑 pending 状态的任务。
    参数为 None 的字段保持不变。

    参数:
        task_id: 任务 ID
        project_id: 新项目 ID（可选）
        description: 新描述（可选）
        hours: 新工时（可选）

    返回:
        更新后的 Task 对象

    异常:
        ValueError: 任务不存在、任务已完成不可编辑、校验失败
    """
    task = get_task(session, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.status == "completed":
        raise ValueError("已完成的任务不可编辑，请先撤销完成")

    if project_id is not None:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError("项目不存在")
        task.project_id = project_id

    if description is not None:
        desc = description.strip()
        if not desc:
            raise ValueError("任务描述不能为空")
        task.description = desc

    if hours is not None:
        task.hours = validate_hours(hours)

    task.updated_at = datetime.now()
    session.commit()
    return task


def complete_task(session: Session, task_id: int) -> Task:
    """
    完成任务，记录完成时间。

    参数:
        task_id: 任务 ID

    返回:
        更新后的 Task 对象

    异常:
        ValueError: 任务不存在、任务已是完成状态
    """
    task = get_task(session, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.status == "completed":
        raise ValueError("任务已完成，无需重复操作")

    task.status = "completed"
    task.completed_at = datetime.now()
    task.updated_at = datetime.now()
    session.commit()
    return task


def undo_complete_task(session: Session, task_id: int) -> Task:
    """
    撤销完成任务，恢复为 pending。

    参数:
        task_id: 任务 ID

    返回:
        更新后的 Task 对象

    异常:
        ValueError: 任务不存在、任务不是完成状态
    """
    task = get_task(session, task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.status != "completed":
        raise ValueError("仅已完成的任务可以撤销")

    task.status = "pending"
    task.completed_at = None
    task.updated_at = datetime.now()
    session.commit()
    return task


def delete_task(session: Session, task_id: int) -> Task:
    """
    软删除任务。

    参数:
        task_id: 任务 ID

    返回:
        标记为删除的 Task 对象

    异常:
        ValueError: 任务不存在
    """
    task = get_task(session, task_id)
    if not task:
        raise ValueError("任务不存在")

    task.is_deleted = True
    task.updated_at = datetime.now()
    session.commit()
    return task


# ──────────────────────────────────────────────
# 聚合查询
# ──────────────────────────────────────────────
def get_week_total_hours(session: Session, week_start: date, week_end: date) -> float:
    """
    计算当周已分配工时总和（含 pending + completed，不含软删除）。

    参数:
        week_start: 周开始日期
        week_end: 周结束日期

    返回:
        总工时（float，保留一位小数）
    """
    tasks = (
        session.query(Task)
        .filter(
            Task.week_start == week_start,
            Task.week_end == week_end,
            Task.is_deleted == False,
        )
        .all()
    )
    total = sum(t.hours or 0.0 for t in tasks)
    return round(total, 1)
