"""
数据模型定义 —— SQLAlchemy ORM

包含六个表：
  - projects: 项目（含进行中/已完成状态）
  - tasks: 任务（含软删除）
  - next_week_plans: 下周计划（目标周语义）
  - goals: 目标看板事项（永久存在，不受周约束）
  - reports: 周报（含任务快照）
  - settings: 全局配置键值对
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime, Text,
    ForeignKey, CheckConstraint, UniqueConstraint, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, Session

logger = logging.getLogger(__name__)

Base = declarative_base()

# 项目状态常量
PROJECT_ACTIVE = "active"
PROJECT_COMPLETED = "completed"
PROJECT_STATUSES = (PROJECT_ACTIVE, PROJECT_COMPLETED)


# ──────────────────────────────────────────────
# 1. 项目表
# ──────────────────────────────────────────────
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="项目名称（trim 后存储）")
    status = Column(
        String(20), nullable=False, default=PROJECT_ACTIVE, server_default=PROJECT_ACTIVE,
        comment="项目状态：active（进行中）/ completed（已完成）"
    )
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="最后修改时间")

    # 关联
    tasks = relationship("Task", back_populates="project", lazy="dynamic")
    plans = relationship("NextWeekPlan", back_populates="project", lazy="dynamic")
    goals = relationship("Goal", back_populates="project", lazy="dynamic")

    @property
    def is_active(self) -> bool:
        """项目是否进行中（已完成项目不出现在新增任务/目标的项目下拉中）"""
        return self.status != PROJECT_COMPLETED

    def __repr__(self):
        return f"<Project(id={self.id}, name='{self.name}', status='{self.status}')>"


# ──────────────────────────────────────────────
# 2. 任务表
# ──────────────────────────────────────────────
class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("hours >= 0", name="ck_tasks_hours_positive"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目")
    description = Column(Text, nullable=False, comment="任务描述")
    hours = Column(Float, nullable=True, comment="工时（0.5h 精度，pending 时可为 NULL）")
    status = Column(
        String(20), nullable=False, default="pending",
        comment="任务状态：pending / completed"
    )
    parent_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, comment="父任务 ID（NULL = 顶层任务）")
    week_start = Column(Date, nullable=False, comment="所属周开始日期")
    week_end = Column(Date, nullable=False, comment="所属周结束日期")
    is_deleted = Column(Boolean, nullable=False, default=False, comment="软删除标记")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="最后修改时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间（pending 时为 NULL）")

    # 关联
    project = relationship("Project", back_populates="tasks")
    parent = relationship("Task", remote_side="Task.id", backref="children")

    def __repr__(self):
        return f"<Task(id={self.id}, project_id={self.project_id}, status='{self.status}')>"


# ──────────────────────────────────────────────
# 3. 下周计划表
# ──────────────────────────────────────────────
class NextWeekPlan(Base):
    __tablename__ = "next_week_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目")
    description = Column(Text, nullable=False, comment="任务描述")
    week_start = Column(Date, nullable=False, comment="目标周开始日期（计划所属的周）")
    week_end = Column(Date, nullable=False, comment="目标周结束日期")
    synced_at = Column(DateTime, nullable=True, comment="同步时间（NULL = 未同步）")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="最后修改时间")

    # 关联
    project = relationship("Project", back_populates="plans")

    @property
    def is_synced(self) -> bool:
        """是否已同步"""
        return self.synced_at is not None

    def __repr__(self):
        return f"<NextWeekPlan(id={self.id}, project_id={self.project_id}, synced={self.is_synced})>"


# ──────────────────────────────────────────────
# 4. 目标看板表
# ──────────────────────────────────────────────
GOAL_NOT_STARTED = "not_started"
GOAL_IN_PROGRESS = "in_progress"
GOAL_COMPLETED = "completed"
GOAL_STATUSES = (GOAL_NOT_STARTED, GOAL_IN_PROGRESS, GOAL_COMPLETED)


class Goal(Base):
    """
    目标看板事项。

    永久存在，不受周约束；状态只能手动流转：
      not_started → in_progress → completed（可撤销回 in_progress）
    """

    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, comment="关联项目")
    title = Column(Text, nullable=False, comment="目标名称")
    note = Column(Text, nullable=True, comment="备注（可记录卡点等信息）")
    status = Column(
        String(20), nullable=False, default=GOAL_NOT_STARTED,
        comment="目标状态：not_started / in_progress / completed"
    )
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="最后修改时间")

    # 关联
    project = relationship("Project", back_populates="goals")

    @property
    def status_label(self) -> str:
        """状态的中文展示文本"""
        return {
            GOAL_NOT_STARTED: "未开始",
            GOAL_IN_PROGRESS: "进行中",
            GOAL_COMPLETED: "已完成",
        }.get(self.status, self.status)

    def __repr__(self):
        return f"<Goal(id={self.id}, project_id={self.project_id}, status='{self.status}')>"


# ──────────────────────────────────────────────
# 5. 周报表
# ──────────────────────────────────────────────
class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False, comment="周开始日期")
    week_end = Column(Date, nullable=False, comment="周结束日期")
    content = Column(Text, nullable=False, comment="LLM 生成的周报内容")
    task_ids = Column(Text, nullable=False, comment="JSON 数组，生成时使用的任务 ID 快照")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="生成时间")

    def __repr__(self):
        return f"<Report(id={self.id}, week_start={self.week_start})>"


# ──────────────────────────────────────────────
# 6. 设置表（键值对）
# ──────────────────────────────────────────────
class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True, comment="配置键")
    value = Column(Text, nullable=False, comment="配置值")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="最后修改时间")

    def __repr__(self):
        return f"<Setting(key='{self.key}', value='{self.value}')>"


# ──────────────────────────────────────────────
# 数据库初始化
# ──────────────────────────────────────────────
DATABASE_URL = "sqlite:///data/todo.db"
DB_PATH = Path("data/todo.db")
BACKUP_DIR = Path("data/backups")
BACKUP_KEEP = 10  # 自动备份保留最近 N 份

_engine = None


def get_engine():
    """获取数据库引擎（单例）"""
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, echo=False)
    return _engine


def _sqlite_has_table(engine, table: str) -> bool:
    """SQLite：判断表是否存在"""
    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).first()
    return row is not None


def _sqlite_has_column(engine, table: str, column: str) -> bool:
    """SQLite：判断列是否存在"""
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _needs_migration(engine) -> bool:
    """
    判断旧库是否需要结构升级：
      - projects 表缺少 status 列（项目状态功能）
      - goals 表不存在（目标看板）
    """
    if not _sqlite_has_table(engine, "projects"):
        return False  # 全新的空库，create_all 会建全
    return (
        not _sqlite_has_column(engine, "projects", "status")
        or not _sqlite_has_table(engine, "goals")
    )


def backup_db(reason: str = "manual") -> Path | None:
    """
    备份当前数据库到 data/backups/，并只保留最近 BACKUP_KEEP 份。

    参数:
        reason: 备份原因（写入日志）

    返回:
        备份文件路径；数据库不存在时返回 None
    """
    if not DB_PATH.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dst = BACKUP_DIR / f"todo-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    shutil.copy2(DB_PATH, dst)
    logger.info(f"数据库已备份（{reason}）：{dst}")

    backups = sorted(BACKUP_DIR.glob("todo-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[BACKUP_KEEP:]:
        try:
            old.unlink()
        except OSError as e:
            logger.warning(f"清理旧备份失败 {old}: {e}")
    return dst


def _migrate_schema(engine):
    """
    SQLite 增量迁移（幂等）：
      - projects.status：旧库补列，默认 active，历史项目视为进行中
    """
    if _sqlite_has_table(engine, "projects") and not _sqlite_has_column(engine, "projects", "status"):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"
            )
        logger.info("迁移完成：projects.status 列已添加（历史项目默认 active）")


def init_db():
    """
    初始化数据库：建表 + 增量迁移 + 写入默认配置。

    每次应用启动时调用，幂等。
    若检测到需要结构升级，会先把旧库备份到 data/backups/，避免历史数据丢失。
    """
    # 确保 data 目录存在
    os.makedirs("data", exist_ok=True)

    engine = get_engine()

    # 结构变更前先备份（仅旧库需要升级时触发，正常启动不产生冗余备份）
    if _needs_migration(engine):
        backup_db("升级表结构前自动备份")

    Base.metadata.create_all(engine)
    _migrate_schema(engine)

    # 写入默认配置（仅当 settings 表为空时）
    with Session(engine) as session:
        if session.query(Setting).count() == 0:
            defaults = [
                Setting(key="total_hours_per_week", value="40"),
                Setting(key="llm_model", value="qwen-plus"),
                Setting(key="llm_base_url", value="https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ]
            session.add_all(defaults)
            session.commit()


def get_session() -> Session:
    """获取一个新的数据库会话"""
    return Session(get_engine())
