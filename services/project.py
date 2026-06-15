"""
项目 CRUD 服务

提供项目的增删改查操作，按创建时间升序排列。
"""

from datetime import datetime
from sqlalchemy.orm import Session
from models import Project, Task, NextWeekPlan


def list_projects(session: Session) -> list[Project]:
    """
    获取所有项目，按创建时间升序。

    返回:
        Project 对象列表（最早创建的在前）
    """
    return (
        session.query(Project)
        .order_by(Project.created_at.asc())
        .all()
    )


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


def delete_project(session: Session, project_id: int) -> dict:
    """
    删除项目，同时删除该项目下所有关联数据。

    参数:
        project_id: 项目 ID

    返回:
        {"deleted": bool, "tasks": int, "plans": int}
        - tasks: 被删除的任务数
        - plans: 被删除的计划数

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

    # 删除关联的计划（硬删除）
    session.query(NextWeekPlan).filter(NextWeekPlan.project_id == project_id).delete()
    # 删除关联的任务（硬删除，跳过软删除标记）
    session.query(Task).filter(Task.project_id == project_id).delete()
    # 删除项目
    session.delete(project)
    session.commit()

    return {"deleted": True, "tasks": task_count, "plans": plan_count}
