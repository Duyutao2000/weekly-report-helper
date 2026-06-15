"""
数据模型定义 —— SQLAlchemy ORM

包含五个表：
  - projects: 项目
  - tasks: 任务（含软删除）
  - next_week_plans: 下周计划（目标周语义）
  - reports: 周报（含任务快照）
  - settings: 全局配置键值对
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime, Text,
    ForeignKey, CheckConstraint, UniqueConstraint, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, Session

Base = declarative_base()


# ──────────────────────────────────────────────
# 1. 项目表
# ──────────────────────────────────────────────
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="项目名称（trim 后存储）")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="最后修改时间")

    # 关联
    tasks = relationship("Task", back_populates="project", lazy="dynamic")
    plans = relationship("NextWeekPlan", back_populates="project", lazy="dynamic")

    def __repr__(self):
        return f"<Project(id={self.id}, name='{self.name}')>"


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
    week_start = Column(Date, nullable=False, comment="所属周开始日期")
    week_end = Column(Date, nullable=False, comment="所属周结束日期")
    is_deleted = Column(Boolean, nullable=False, default=False, comment="软删除标记")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="最后修改时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间（pending 时为 NULL）")

    # 关联
    project = relationship("Project", back_populates="tasks")

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
# 4. 周报表
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
# 5. 设置表（键值对）
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

_engine = None


def get_engine():
    """获取数据库引擎（单例）"""
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, echo=False)
    return _engine


def init_db():
    """
    初始化数据库：建表 + 写入默认配置。

    每次应用启动时调用，幂等（CREATE TABLE IF NOT EXISTS）。
    """
    import os

    # 确保 data 目录存在
    os.makedirs("data", exist_ok=True)

    engine = get_engine()
    Base.metadata.create_all(engine)

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
