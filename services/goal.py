"""
目标看板服务

目标事项永久存在，不受周时间约束，状态只能手动流转：
    not_started → in_progress → completed（可撤销回 in_progress）

备注用于记录卡点等信息，可为空。
"""

from datetime import datetime

from sqlalchemy.orm import Session

from core.models import (
    Goal, Project,
    GOAL_NOT_STARTED, GOAL_IN_PROGRESS, GOAL_COMPLETED, GOAL_STATUSES,
    PROJECT_COMPLETED,
)

# 看板排序：进行中 → 未开始 → 已完成
_STATUS_ORDER = {GOAL_IN_PROGRESS: 0, GOAL_NOT_STARTED: 1, GOAL_COMPLETED: 2}


# ──────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────
def get_goal(session: Session, goal_id: int) -> Goal | None:
    """按 ID 获取目标"""
    return session.query(Goal).filter(Goal.id == goal_id).first()


def list_goals(
    session: Session,
    project_id: int | None = None,
    status: str | None = None,
    include_completed: bool = True,
) -> list[Goal]:
    """
    获取目标列表（按状态优先级 + 创建时间排序）。

    参数:
        project_id: 项目过滤（可选）
        status: 状态过滤 not_started/in_progress/completed（可选）
        include_completed: 是否包含已完成目标

    返回:
        Goal 列表
    """
    q = session.query(Goal)
    if project_id is not None:
        q = q.filter(Goal.project_id == project_id)
    if status is not None:
        if status not in GOAL_STATUSES:
            raise ValueError(f"未知的目标状态：{status}")
        q = q.filter(Goal.status == status)
    elif not include_completed:
        q = q.filter(Goal.status != GOAL_COMPLETED)

    goals = q.all()
    goals.sort(
        key=lambda g: (
            _STATUS_ORDER.get(g.status, 99),
            g.created_at or datetime.min,
        )
    )
    return goals


def get_goals_grouped_by_project(
    session: Session,
    include_completed: bool = True,
) -> dict[int, dict]:
    """
    按项目分组获取目标。

    返回:
        {project_id: {"project": Project, "goals": [Goal], "in_progress": int, "completed": int}}
    """
    goals = list_goals(session, include_completed=include_completed)
    grouped: dict[int, dict] = {}
    for g in goals:
        entry = grouped.setdefault(
            g.project_id,
            {"project": g.project, "goals": [], "in_progress": 0, "completed": 0},
        )
        entry["goals"].append(g)
        if g.status == GOAL_IN_PROGRESS:
            entry["in_progress"] += 1
        elif g.status == GOAL_COMPLETED:
            entry["completed"] += 1
    return grouped


def count_goals_by_status(session: Session) -> dict[str, int]:
    """统计各状态目标数量（用于看板顶部汇总）"""
    counts = {s: 0 for s in GOAL_STATUSES}
    for (status,) in session.query(Goal.status).all():
        counts[status] = counts.get(status, 0) + 1
    return counts


# ──────────────────────────────────────────────
# 写操作
# ──────────────────────────────────────────────
def _get_goal_or_raise(session: Session, goal_id: int) -> Goal:
    goal = get_goal(session, goal_id)
    if not goal:
        raise ValueError("目标不存在")
    return goal


def _validate_project(session: Session, project_id: int) -> Project:
    """校验项目存在且仍在进行中"""
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")
    if project.status == PROJECT_COMPLETED:
        raise ValueError(f"项目「{project.name}」已完成，请先重新启用后再添加目标")
    return project


def _clean_optional_text(value: str | None) -> str | None:
    """备注等可选文本：纯空白视为空字符串（允许清空），None 原样返回"""
    if value is None:
        return None
    return value.strip()


def create_goal(
    session: Session,
    project_id: int,
    title: str,
    note: str | None = None,
) -> Goal:
    """
    新增目标（默认「未开始」）。

    参数:
        project_id: 关联项目 ID（必须存在且未完成）
        title: 目标名称（不可为空）
        note: 备注（可选）

    返回:
        新创建的 Goal 对象

    异常:
        ValueError: 名称为空、项目不存在或已完成
    """
    trimmed = (title or "").strip()
    if not trimmed:
        raise ValueError("目标名称不能为空")

    _validate_project(session, project_id)

    goal = Goal(
        project_id=project_id,
        title=trimmed,
        note=_clean_optional_text(note),
        status=GOAL_NOT_STARTED,
    )
    session.add(goal)
    session.commit()
    return goal


def update_goal(
    session: Session,
    goal_id: int,
    title: str | None = None,
    note: str | None = None,
    project_id: int | None = None,
) -> Goal:
    """
    编辑目标名称 / 备注 / 关联项目。参数为 None 的字段保持不变。

    参数:
        goal_id: 目标 ID
        title: 新名称（可选）
        note: 新备注（可选；空字符串表示清空备注）
        project_id: 新项目 ID（可选）

    返回:
        更新后的 Goal 对象

    异常:
        ValueError: 目标不存在、名称为空、项目不存在或已完成
    """
    goal = _get_goal_or_raise(session, goal_id)

    if title is not None:
        trimmed = title.strip()
        if not trimmed:
            raise ValueError("目标名称不能为空")
        goal.title = trimmed

    if note is not None:
        goal.note = _clean_optional_text(note)

    if project_id is not None and project_id != goal.project_id:
        _validate_project(session, project_id)
        goal.project_id = project_id

    goal.updated_at = datetime.now()
    session.commit()
    return goal


def start_goal(session: Session, goal_id: int) -> Goal:
    """
    开始目标：未开始 → 进行中。

    异常:
        ValueError: 目标不存在、当前状态不允许开始
    """
    goal = _get_goal_or_raise(session, goal_id)
    if goal.status == GOAL_IN_PROGRESS:
        raise ValueError("目标已在进行中")
    if goal.status == GOAL_COMPLETED:
        raise ValueError("目标已完成，如需继续请先撤销完成")

    goal.status = GOAL_IN_PROGRESS
    goal.started_at = datetime.now()
    goal.updated_at = datetime.now()
    session.commit()
    return goal


def complete_goal(session: Session, goal_id: int) -> Goal:
    """
    结束目标：进行中 → 已完成。

    异常:
        ValueError: 目标不存在、未开始或已完成
    """
    goal = _get_goal_or_raise(session, goal_id)
    if goal.status == GOAL_NOT_STARTED:
        raise ValueError("目标尚未开始，请先点「开始」")
    if goal.status == GOAL_COMPLETED:
        raise ValueError("目标已完成")

    goal.status = GOAL_COMPLETED
    goal.completed_at = datetime.now()
    goal.updated_at = datetime.now()
    session.commit()
    return goal


def undo_complete_goal(session: Session, goal_id: int) -> Goal:
    """
    撤销完成：已完成 → 进行中（保留开始时间）。

    异常:
        ValueError: 目标不存在、不是已完成状态
    """
    goal = _get_goal_or_raise(session, goal_id)
    if goal.status != GOAL_COMPLETED:
        raise ValueError("仅已完成的目标可以撤销")

    goal.status = GOAL_IN_PROGRESS
    goal.completed_at = None
    if goal.started_at is None:
        goal.started_at = datetime.now()
    goal.updated_at = datetime.now()
    session.commit()
    return goal


def delete_goal(session: Session, goal_id: int) -> Goal:
    """
    删除目标（硬删除，需前端二次确认）。

    异常:
        ValueError: 目标不存在
    """
    goal = _get_goal_or_raise(session, goal_id)
    session.delete(goal)
    session.commit()
    return goal
