"""
下周计划 CRUD 服务

提供计划的增删改查、同步到任务表功能。
- week_start/week_end 存储的是目标周（计划打算在哪周执行）
- synced_at 为 NULL 表示未同步，非 NULL 记录同步时间
"""

from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import NextWeekPlan, Task, Project


# ──────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────
def get_plan(session: Session, plan_id: int) -> NextWeekPlan | None:
    """按 ID 获取计划"""
    return session.query(NextWeekPlan).filter(NextWeekPlan.id == plan_id).first()


def get_plans_by_target_week(
    session: Session,
    week_start: date,
    week_end: date,
) -> list[NextWeekPlan]:
    """
    获取指定目标周的所有计划（按项目排序）。

    参数:
        week_start: 目标周开始日期
        week_end: 目标周结束日期
    """
    return (
        session.query(NextWeekPlan)
        .filter(
            NextWeekPlan.week_start == week_start,
            NextWeekPlan.week_end == week_end,
        )
        .join(Project)
        .order_by(Project.created_at.asc(), NextWeekPlan.created_at.asc())
        .all()
    )


def get_plans_grouped_by_project(
    session: Session,
    week_start: date,
    week_end: date,
) -> dict[int, dict]:
    """
    按项目分组获取目标周计划。

    返回:
        {project_id: {"project": Project, "plans": [NextWeekPlan]}}
    """
    plans = get_plans_by_target_week(session, week_start, week_end)
    grouped: dict[int, dict] = {}
    for p in plans:
        pid = p.project_id
        if pid not in grouped:
            grouped[pid] = {"project": p.project, "plans": []}
        grouped[pid]["plans"].append(p)
    return grouped


def get_unsynced_plans_for_week(
    session: Session,
    week_start: date,
    week_end: date,
) -> list[NextWeekPlan]:
    """
    获取目标周内未同步的计划（用于切换周期时检测）。

    参数:
        week_start: 目标周开始日期
        week_end: 目标周结束日期

    返回:
        未同步的计划列表
    """
    return (
        session.query(NextWeekPlan)
        .filter(
            NextWeekPlan.week_start == week_start,
            NextWeekPlan.week_end == week_end,
            NextWeekPlan.synced_at.is_(None),
        )
        .all()
    )


# ──────────────────────────────────────────────
# 写操作
# ──────────────────────────────────────────────
def create_plan(
    session: Session,
    project_id: int,
    description: str,
    week_start: date,
    week_end: date,
) -> NextWeekPlan:
    """
    新增计划任务。

    参数:
        project_id: 项目 ID
        description: 任务描述（不可为空）
        week_start: 目标周开始日期
        week_end: 目标周结束日期

    返回:
        新创建的 NextWeekPlan 对象

    异常:
        ValueError: 描述为空、项目不存在
    """
    desc = description.strip()
    if not desc:
        raise ValueError("计划描述不能为空")

    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")

    plan = NextWeekPlan(
        project_id=project_id,
        description=desc,
        week_start=week_start,
        week_end=week_end,
    )
    session.add(plan)
    session.commit()
    return plan


def update_plan(
    session: Session,
    plan_id: int,
    project_id: int | None = None,
    description: str | None = None,
    week_start: date | None = None,
    week_end: date | None = None,
) -> NextWeekPlan:
    """
    编辑计划（仅未同步的计划可编辑）。

    参数:
        plan_id: 计划 ID
        project_id: 新项目 ID（可选）
        description: 新描述（可选）
        week_start: 新目标周开始（可选）
        week_end: 新目标周结束（可选）

    返回:
        更新后的 NextWeekPlan 对象

    异常:
        ValueError: 计划不存在、已同步不可编辑、校验失败
    """
    plan = get_plan(session, plan_id)
    if not plan:
        raise ValueError("计划不存在")
    if plan.synced_at is not None:
        raise ValueError("已同步的计划不可编辑")

    if project_id is not None:
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError("项目不存在")
        plan.project_id = project_id

    if description is not None:
        desc = description.strip()
        if not desc:
            raise ValueError("计划描述不能为空")
        plan.description = desc

    if week_start is not None:
        plan.week_start = week_start
    if week_end is not None:
        plan.week_end = week_end

    plan.updated_at = datetime.now()
    session.commit()
    return plan


def delete_plan(session: Session, plan_id: int) -> NextWeekPlan:
    """
    删除计划（仅未同步的可以删除，已同步的只读）。

    参数:
        plan_id: 计划 ID

    返回:
        被删除的 NextWeekPlan 对象

    异常:
        ValueError: 计划不存在、已同步不可删除
    """
    plan = get_plan(session, plan_id)
    if not plan:
        raise ValueError("计划不存在")
    if plan.synced_at is not None:
        raise ValueError("已同步的计划不可删除，请在对应任务中操作")

    session.delete(plan)
    session.commit()
    return plan


# ──────────────────────────────────────────────
# 同步逻辑
# ──────────────────────────────────────────────
def count_unsynced_plans_for_week(
    session: Session,
    week_start: date,
    week_end: date,
) -> int:
    """
    统计目标周内未同步的计划数量（用于弹窗提示）。

    参数:
        week_start: 目标周开始日期
        week_end: 目标周结束日期

    返回:
        未同步计划数
    """
    return len(get_unsynced_plans_for_week(session, week_start, week_end))


def sync_plans_to_tasks(
    session: Session,
    week_start: date,
    week_end: date,
) -> int:
    """
    将目标周内未同步的计划复制到任务表，并标记为已同步。

    同步逻辑：
    1. 查找 week_start/week_end 匹配且 synced_at IS NULL 的计划
    2. 每条计划在 tasks 表创建一条 pending 任务（hours=NULL）
    3. 更新计划的 synced_at 为当前时间

    参数:
        week_start: 目标周开始日期
        week_end: 目标周结束日期

    返回:
        同步的计划数量

    异常:
        ValueError: 无可同步的计划
    """
    plans = get_unsynced_plans_for_week(session, week_start, week_end)
    if not plans:
        raise ValueError("没有待同步的计划")

    now = datetime.now()
    count = 0
    for plan in plans:
        task = Task(
            project_id=plan.project_id,
            description=plan.description,
            hours=None,  # 工时待填写
            status="pending",
            week_start=plan.week_start,
            week_end=plan.week_end,
        )
        session.add(task)
        plan.synced_at = now
        plan.updated_at = now
        count += 1

    session.commit()
    return count


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def get_default_next_week() -> tuple[date, date]:
    """
    计算默认下周日期范围。

    从今天起，找下一个周一作为开始，下周五作为结束。
    如果今天是周一～周五，下周 = 本周一 + 7 天。

    返回:
        (next_week_start: date, next_week_end: date)
    """
    today = date.today()
    # 本周一 = 今天 - (weekday - 0)，weekday() 周一=0 周日=6
    this_monday = today - timedelta(days=today.weekday())
    next_monday = this_monday + timedelta(days=7)
    next_friday = next_monday + timedelta(days=4)
    return next_monday, next_friday
