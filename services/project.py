"""
项目 CRUD 服务

提供项目的增删改查、状态切换（进行中/已完成），按创建时间升序排列。
已完成项目不会出现在「新增任务 / 新增目标」的项目下拉中。
"""

from datetime import datetime
from sqlalchemy.orm import Session
from core.models import (
    Project, Task, NextWeekPlan, Goal,
    PROJECT_ACTIVE, PROJECT_COMPLETED, PROJECT_STATUSES,
)


def list_projects(session: Session, active_only: bool = False) -> list[Project]:
    """
    获取所有项目，按创建时间升序。

    参数:
        active_only: 只返回进行中项目（用于新增任务/目标的项目下拉）

    返回:
        Project 对象列表（最早创建的在前）
    """
    q = session.query(Project)
    if active_only:
        q = q.filter(Project.status != PROJECT_COMPLETED)
    return q.order_by(Project.created_at.asc()).all()


def get_project(session: Session, project_id: int) -> Project | None:
    """
    按 ID 获取项目。

    参数:
        project_id: 项目 ID

    返回:
        Project 对象，不存在返回 None
    """
    return session.query(Project).filter(Project.id == project_id).first()


def get_project_by_name(session: Session, name: str) -> Project | None:
    """
    按名称查找项目（trim 后精确匹配）。

    参数:
        name: 项目名称

    返回:
        Project 对象，不存在返回 None
    """
    trimmed = name.strip()
    return session.query(Project).filter(Project.name == trimmed).first()


def create_project(session: Session, name: str) -> Project:
    """
    新增项目。

    参数:
        name: 项目名称（不能为空，不可重复）

    返回:
        新创建的 Project 对象

    异常:
        ValueError: 名称为空
        ValueError: 名称已存在
    """
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("项目名称不能为空")

    existing = get_project_by_name(session, trimmed)
    if existing:
        raise ValueError(f"项目「{trimmed}」已存在")

    project = Project(name=trimmed)
    session.add(project)
    session.commit()
    return project


def update_project(session: Session, project_id: int, name: str) -> Project:
    """
    编辑项目名称。

    参数:
        project_id: 项目 ID
        name: 新名称

    返回:
        更新后的 Project 对象

    异常:
        ValueError: 项目不存在
        ValueError: 名称为空
        ValueError: 名称与其他项目重复
    """
    project = get_project(session, project_id)
    if not project:
        raise ValueError("项目不存在")

    trimmed = name.strip()
    if not trimmed:
        raise ValueError("项目名称不能为空")

    # 检查是否与其他项目重名
    dup = get_project_by_name(session, trimmed)
    if dup and dup.id != project_id:
        raise ValueError(f"项目「{trimmed}」已存在")

    project.name = trimmed
    project.updated_at = datetime.now()
    session.commit()
    return project


def update_project_status(session: Session, project_id: int, status: str) -> Project:
    """
    切换项目状态（进行中 / 已完成）。

    已完成项目不再出现在「新增任务 / 新增目标」的项目下拉中，
    但项目下的历史任务、计划、目标数据全部保留。

    参数:
        project_id: 项目 ID
        status: active（进行中）或 completed（已完成）

    返回:
        更新后的 Project 对象

    异常:
        ValueError: 项目不存在、状态值非法
    """
    if status not in PROJECT_STATUSES:
        raise ValueError(f"未知的项目状态：{status}")

    project = get_project(session, project_id)
    if not project:
        raise ValueError("项目不存在")

    project.status = status
    project.updated_at = datetime.now()
    session.commit()
    return project


def complete_project(session: Session, project_id: int) -> Project:
    """把项目标记为已完成（保留全部历史数据）"""
    return update_project_status(session, project_id, PROJECT_COMPLETED)


def reopen_project(session: Session, project_id: int) -> Project:
    """把项目重新标记为进行中"""
    return update_project_status(session, project_id, PROJECT_ACTIVE)


def delete_project(session: Session, project_id: int) -> dict:
    """
    删除项目，同时删除该项目下所有关联数据。

    参数:
        project_id: 项目 ID

    返回:
        {"deleted": bool, "tasks": int, "plans": int, "goals": int}
        - tasks: 被删除的任务数
        - plans: 被删除的计划数
        - goals: 被删除的目标数

    异常:
        ValueError: 项目不存在
    """
    project = get_project(session, project_id)
    if not project:
        raise ValueError("项目不存在")

    # 统计关联数据
    task_count = (
        session.query(Task)
        .filter(Task.project_id == project_id, Task.is_deleted == False)
        .count()
    )
    plan_count = (
        session.query(NextWeekPlan)
        .filter(NextWeekPlan.project_id == project_id)
        .count()
    )
    goal_count = (
        session.query(Goal)
        .filter(Goal.project_id == project_id)
        .count()
    )

    # 删除关联的目标（硬删除）
    session.query(Goal).filter(Goal.project_id == project_id).delete()
    # 删除关联的计划（硬删除）
    session.query(NextWeekPlan).filter(NextWeekPlan.project_id == project_id).delete()
    # 删除关联的任务（硬删除，跳过软删除标记）
    session.query(Task).filter(Task.project_id == project_id).delete()
    # 删除项目
    session.delete(project)
    session.commit()

    return {"deleted": True, "tasks": task_count, "plans": plan_count, "goals": goal_count}
