from .utils import RecurType

from nonebot import require
from datetime import datetime, timedelta
import uuid

require("nonebot_plugin_orm")
from nonebot_plugin_orm import Model
from sqlalchemy import ForeignKey, Column, Integer, String, DateTime, Interval, JSON, Boolean, Enum, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.declarative import declared_attr

require("nonebot_plugin_saa")
from nonebot_plugin_saa import PlatformTarget


class SoftDeleteMixin:
    is_deleted: bool
    deleted_at: datetime | None

    @declared_attr
    def is_deleted(self):
        return Column(Boolean, default=False)

    @declared_attr
    def deleted_at(self):
        return Column(DateTime, default=datetime.min)

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.now()

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None


class TaskModel(Model, SoftDeleteMixin):
    # trival attributes:
    # name, description, recur_type, recur_interval: no hook on change
    # untrival attributes:
    # due_time / remind_offset / remind_interval: delete all remind timers and reschedule
    id: Mapped[uuid.UUID] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                                          nullable=False)
    name: Mapped[str] = mapped_column(String)
    due_time: Mapped[datetime] = mapped_column(DateTime)
    remind_offset: Mapped[timedelta] = mapped_column(Interval)
    remind_interval: Mapped[timedelta] = mapped_column(Interval)
    recur_interval: Mapped[timedelta] = mapped_column(Interval, nullable=True)
    recur_type: Mapped[RecurType] = mapped_column(Enum(RecurType))
    apscheduler_job_id: Mapped[str] = mapped_column(String, nullable=True)
    platform_target_serial: Mapped[str] = mapped_column(String, nullable=True)
    current_assignment_order: Mapped[int] = mapped_column(Integer, nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint(
            'name',
            'platform_target_serial',
            'is_deleted',
            'deleted_at',
            name='unique_name_in_the_same_session_with_undeleted_tasks'
        ),
    )

    @property
    def platform_target(self):
        return PlatformTarget.deserialize(self.platform_target_serial)

    @platform_target.setter
    def platform_target(self, platform_target: PlatformTarget):
        self.platform_target_serial = platform_target.model_dump()

    def __repr__(self) -> str:
        return (
            f"ID: {self.id}, Name: {self.name}, "
            f"Due: {self.due_time}, Current: {self.current_assignment_order}, Remind offset: {self.remind_offset}, "
            f"Remind interval: {self.remind_interval}, Recur interval: {self.recur_interval},"
            f"Recur Type: {self.recur_type},"
            f"Apscheduler ID: {self.apscheduler_job_id}, Deleted time: {self.deleted_at}"
        )


class AssigneeModel(Model):
    id: Mapped[uuid.UUID] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                                          nullable=False)
    user_id: Mapped[str] = mapped_column(String, unique=True)


class AssignmentModel(Model):
    id: Mapped[uuid.UUID] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                                          nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(TaskModel.__tablename__ + ".id"))
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(AssigneeModel.__tablename__ + ".id"))
    order: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint('task_id', 'order', name='different_seq for task'),
        UniqueConstraint('task_id', 'assignee_id', name='can only assign once'),
    )


class RecordModel(Model):
    id: Mapped[uuid.UUID] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                                          nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(TaskModel.__tablename__ + ".id"))
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(TaskModel.__tablename__ + ".id"), nullable=True)
    due_time: Mapped[datetime] = mapped_column(DateTime)
    finish_time: Mapped[datetime] = mapped_column(DateTime)
