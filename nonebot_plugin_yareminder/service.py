import uuid
from datetime import datetime, timedelta
from typing import Union, Set, Iterable

from apscheduler.triggers.interval import IntervalTrigger
from nonebot import require, logger
from collections.abc import AsyncGenerator

from .models import TaskModel, AssigneeModel, AssignmentModel, RecordModel
from .utils import natural_lang_date, RecurType

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler
from apscheduler.jobstores.base import JobLookupError

require("nonebot_plugin_saa")
from nonebot_plugin_saa import SaaTarget, MessageFactory, Mention, Text

require("nonebot_plugin_orm")
from nonebot_plugin_orm import get_session, async_scoped_session, AsyncSession, get_scoped_session
from sqlalchemy.future import select
from sqlalchemy.exc import NoResultFound, IntegrityError


def ensure_provided(ensure_args: list, not_none: int):
    if len([1 for arg in ensure_args if arg is not None]) != not_none:
        raise ValueError(f"Exactly {not_none} in specified range of optional argument(s) must be provided")


class Service:
    session: AsyncSession

    def __init__(self, session: AsyncSession):
        self.session = session

    async def __aenter__(self):
        # Optionally start a transaction if necessary
        # await self.session.begin()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.session.rollback()  # Rollback if an error occurred
        else:
            await self.session.commit()    # Commit if no exception
        await self.session.close()         # Close the session


class TaskService(Service):
    # Task related CRUD

    # TODO: a more general search function
    async def search_task(
            self,
            task_name: str | None = None,
            scope: SaaTarget | None = None,
            user_id: str | None = None,
            include_deleted: bool = False
    ):
        """Search for tasks with `task_name` in a scope of SaaTarget"""
        logger.debug(f"Searching tasks with the following filters: task_name={task_name}, scope={scope.model_dump_json()}, user_id={user_id}, include_deleted={include_deleted}")
        stmt = select(TaskModel.id)
        if task_name is not None:
            stmt = stmt.where(TaskModel.name == task_name)
        if scope is not None:
            stmt = stmt.where(TaskModel.platform_target_serial == scope.model_dump_json())
        if not include_deleted:
            stmt = stmt.where(TaskModel.is_deleted == False)
        if user_id is not None:
            stmt = (
                stmt
                .join(AssignmentModel, AssignmentModel.task_id == TaskModel.id)
                .join(AssigneeModel, AssigneeModel.id == AssignmentModel.assignee_id)
                .where(AssigneeModel.user_id == user_id)
            )
        logger.debug(f"Querying with statement: \n{stmt}")
        results = await self.session.execute(stmt)
        return results

    async def __get_task(
            self,
            task_id: Union[uuid.UUID, None] = None,
            include_deleted: bool = False
    ):
        """Fetch a task by ID, """
        stmt = select(TaskModel)
        if task_id:
            stmt = stmt.where(TaskModel.id == task_id)
        if not include_deleted:
            stmt = stmt.where(TaskModel.is_deleted == False)

        try:
            result = await self.session.execute(stmt)
            return result.scalar_one()
        except NoResultFound:
            logger.error(f"Task with ID {task_id} not found.")
            raise NoResultFound(f"No {'undeleted ' if not include_deleted else ''}task has id {task_id}")

    async def create_task(
            self,
            name: str,
            due_time: datetime,
            remind_offset: timedelta,
            remind_interval: timedelta,
            recur_interval: timedelta,
            recur_type: RecurType,
            platform_target: SaaTarget
    ) -> uuid.UUID:
        """Create task"""
        created_task = TaskModel(
            name=name,
            due_time=due_time,
            remind_offset=remind_offset,
            remind_interval=remind_interval,
            recur_interval=recur_interval,
            recur_type=recur_type,
            platform_target_serial=platform_target.model_dump_json(),
            current_assignment_order=None
        )
        self.session.add(created_task)
        await self.session.commit()
        await self.session.refresh(created_task)
        await self.refresh_reminder(created_task.id)
        task_id = created_task.id

        return task_id

    async def delete_task(self, task_id: uuid.UUID) -> None:
        """Delete given task or task with given id"""
        await self.remove_reminder(task_id)
        task = await self.__get_task(task_id=task_id)
        task.soft_delete()
        await self.session.commit()

    async def set_task(
            self,
            task_id: Union[uuid.UUID, None] = None,
            **kwargs
    ) -> None:
        """Set attributes of a task"""
        logger.debug(f"Setting values: {kwargs}")
        task = await self.__get_task(task_id)
        for attr_name, attr_value in kwargs.items():
            if not hasattr(task, attr_name):
                logger.error(f"Setting non-existing attr {attr_name} of task {task.id} to {attr_value}")
                raise ValueError(f"None existing attr: {attr_name}")

            match attr_name:
                case "due_time":
                    if isinstance(attr_value, timedelta):
                        setattr(task, "due_time", getattr(task, "due_time") + attr_value)
                    elif isinstance(attr_value, datetime):
                        setattr(task, attr_name, attr_value)
                    else:
                        raise ValueError("Incorrect value type for due_time")
                    await self.refresh_reminder(task.id)
                case "remind_offset" | "remind_interval":
                    setattr(task, attr_name, attr_value)
                    await self.refresh_reminder(task.id)
                case _:
                    setattr(task, attr_name, attr_value)

        await self.session.commit()
        await self.session.refresh(task)

    # Assignee lookup & assignment CRUD
    async def get_assignee_user_ids(self, task_id: uuid.UUID):
        """Get all assignees for a task."""
        assignees = (
            await self.session.execute(
                select(AssigneeModel.user_id)
                .join(AssignmentModel, AssignmentModel.assignee_id == AssigneeModel.id)
                .join(TaskModel, TaskModel.id == AssignmentModel.task_id)
                .where(TaskModel.id == task_id)
                .order_by(AssignmentModel.order)
            )
        ).scalars().all()
        if not assignees:
            logger.info(f"No assignee for task {task_id}")
            return []
        logger.debug(f"Assignees for task {task_id}: {assignees}")
        return assignees

    async def shift_current_assignee_order(self, task_id: uuid.UUID, offset: int):
        """Shift by offset to another from current assignee"""
        logger.info(f"Shifting task current by {offset}")
        assignee_count = len(await self.get_assignee_user_ids(task_id))
        if assignee_count == 0:
            logger.warning("Shifting task current with no assignee")
        task = await self.__get_task(task_id)
        logger.debug(f"Previous order: {task.current_assignment_order}")
        task.current_assignment_order = (task.current_assignment_order + offset) % assignee_count
        logger.debug(f"Assignee count: {assignee_count}, current order: {task.current_assignment_order}")

        await self.session.commit()

    async def create_assignments(self, task_id: uuid.UUID, assignee_ids: Iterable[uuid.UUID]) -> None:
        """Create assignments."""
        logger.info(f"Assigning task {task_id} to assinees {assignee_ids}")
        task = await self.__get_task(task_id)

        assignee_count = len(await self.get_assignee_user_ids(task_id))
        if not task.current_assignment_order:
            logger.debug(f"Initialize task's current assignment order to 0")
            task.current_assignment_order = 0
        await self.session.commit()
        await self.session.refresh(task)
        logger.debug(f"Existing assignee count is {assignee_count} for task {task_id}")

        for assignee_id in assignee_ids:
            new_assignment = AssignmentModel(
                task_id=task_id,
                assignee_id=assignee_id,
                order=assignee_count
            )
            self.session.add(new_assignment)
            try:
                await self.session.commit()
            except IntegrityError as e:
                await self.session.rollback()
                logger.warning(f"Assignee {assignee_id} already assigned to task {task_id}")
            else:
                logger.debug(f"Assignees added for task {task_id}: {assignee_id} [{assignee_count}]")
                assignee_count += 1

    async def remove_assignments(self, task_id: uuid.UUID, assignee_ids: Iterable[uuid.UUID]):
        """Try remove assignment from given task"""
        task = await self.__get_task(task_id)

        assignments = (
            await self.session.execute(
                select(AssignmentModel)
                .where(AssignmentModel.id.in_(assignee_ids))
                .order_by(AssignmentModel.order)
            )
        ).scalars().all()

        logger.debug(f"Assignments for task {task.name}: {assignments}")

        offset = 0
        assignee_ids = list(assignee_ids)

        for i in range(0, len(assignments)):
            if assignments[i].assignee_id in assignee_ids:
                assignee_ids.remove(assignments[i].assignee_id)
                self.session.delete(assignments[i])
                offset += 1
                if task.current_assignment_order >= i: task.current_assignment_order -= 1
            else:
                assignments[i].order -= offset

        if assignee_ids:
            logger.warning(f"These assignees is not assigned to task {task.id}: {assignee_ids} ")

    # APScheduler wakeup timer related

    # Note: as apscheduler handles its own persist database, this operation is not atomic: 
    # a partial fail could lead to wild wakeup jobs waking up a task more frequently than 
    # expected, or trying to wake up a task no longer exist. The purge method in utils could
    # fix all such errors but is relatively expensive.

    @staticmethod
    async def send_reminder(task_id: uuid.UUID):
        """Send a reminder notification for the task."""
        async with TaskService(get_session()) as task_service:
            logger.info(f"Sending notification for task {task_id}")
            try:
                task = await task_service.__get_task(task_id)
            except NoResultFound:
                logger.error(f"No active task with id {task_id}. Possibly unmanaged jobs exist, please purge.")
                return
            msg = await task_service.get_notification_message(task_id)
            try:
                await msg.send_to(target=task.platform_target)
                logger.debug(f"Sent reminder for task {task.id}")
            except Exception as e:
                logger.error(f"Failed to send reminder for task {task.id}: {e}")
                return

    @staticmethod
    async def send_reminder_for_all(scope: Set[SaaTarget]):
        """Send a reminder notification for all ongoing task."""
        session = get_session()
        scope_serialized = {saa_target.model_dump_json() for saa_target in scope}
        task_ids = (
            await session.execute(
                select(TaskModel.id)
                .where(
                    TaskModel.is_deleted == False,
                    TaskModel.platform_target_serial.in_(scope_serialized)
                )
            )
        ).scalars().all()
        for task_id in task_ids:
            await TaskService.send_reminder(task_id)

    async def schedule_reminder(self, task_id: uuid.UUID):
        """Schedule the APScheduler reminder job for the task."""
        task = await self.__get_task(task_id)
        trigger = IntervalTrigger(
            seconds=int(task.remind_interval.total_seconds()),
            jitter=int(task.remind_interval.total_seconds() * 0.02),
            start_date=task.due_time + task.remind_offset
        )
        job = scheduler.add_job(
            TaskService.send_reminder,
            jobstore='nonebot-plugin-yareminder-jobstore',
            trigger=trigger,
            args=[task.id],
            name=f"Reminder wakeup timer for task {task.name} ({task.id})"
        )
        task.apscheduler_job_id = job.id
        await self.session.commit()
        await self.session.refresh(task)
        logger.debug(f"Scheduled reminder for task {task.id}: {job.id}")

    async def remove_reminder(self, task_id: uuid.UUID):
        """Remove the APScheduler reminder job."""
        task = await self.__get_task(task_id)
        if task.apscheduler_job_id:
            try:
                scheduler.remove_job(task.apscheduler_job_id, 'nonebot-plugin-yareminder-jobstore')
                logger.debug(f"Removed reminder for task {task.id}")
            except JobLookupError:
                logger.warning(f"Job {task.apscheduler_job_id} not found for task {task.id}")
            task.apscheduler_job_id = None
            await self.session.commit()
            await self.session.refresh(task)
        else:
            logger.warning(f"Task {task_id} has no job")

    async def refresh_reminder(self, task_id: uuid.UUID):
        """Refresh the reminder by removing and rescheduling the APScheduler job."""
        logger.debug(f"Refreshing reminder for task {task_id}")

        await self.remove_reminder(task_id)
        await self.schedule_reminder(task_id)

    # All human-readable related message generation

    async def get_notification_message(self, task_id: uuid.UUID) -> MessageFactory:
        """Generate the notification message for the task."""
        msg = MessageFactory()
        task: TaskModel = await self.__get_task(task_id)

        assignee_user_ids = await self.get_assignee_user_ids(task_id)
        if assignee_user_ids:
            msg += [Mention(user_id=assignee_user_ids[task.current_assignment_order]), " "]
        now = datetime.now()
        if now < task.due_time:
            msg += ["请记得", await self.describe_due_time(task_id), str(task.name)]
        else:
            msg += [f"{task.name}应", await self.describe_due_time(task_id), "哦"]

        return msg

    async def describe_recurrence(self, task_id: uuid.UUID) -> Text:
        """Return a Text that describes the recurrence """
        task = await self.__get_task(task_id)
        match task.recur_type:
            case RecurType.Never:
                return Text("不重复")
            case RecurType.OnFinish:
                return Text(f"完成{task.recur_interval}后重复")
            case RecurType.Regular:
                return Text(f"每{task.recur_interval}重复")

    async def describe_due_time(self, task_id: uuid.UUID) -> Text:
        """Return a Text that describes the recurrence """
        task = await self.__get_task(task_id)
        return Text(f"在{natural_lang_date(task.due_time)}前完成")

    async def describe_remind(self, task_id: uuid.UUID) -> Text:
        """Returns a Text that describes the reminder offset"""
        task = await self.__get_task(task_id)
        return Text(f"提前{task.remind_offset}提醒，提醒间隔{task.remind_interval}")

    async def describe_assignee(self, task_id: uuid.UUID) -> MessageFactory:
        """Returns a MessageFactory that describes the assignees and current one"""
        msg = MessageFactory()
        task = await self.__get_task(task_id)
        user_ids = await self.get_assignee_user_ids(task.id)
        if user_ids:
            logger.debug(f"Exist assignees for task {task_id}")
            msg += "依次由 "
            for user_id in user_ids:
                msg += Mention(user_id)
                msg += " "
            msg += " 完成，当前轮到 "
            msg += Mention(user_ids[task.current_assignment_order])
        else:
            logger.debug(f"No assignees for task {task_id}")
            msg += "无指派"
        return msg

    async def describe_task(
            self,
            task_id: uuid.UUID
    ):
        logger.debug(f"Generating description of task: {task_id}")
        task: TaskModel = await self.__get_task(task_id, include_deleted=True)
        msg = MessageFactory()
        if task.is_deleted:
            msg += f"[{task.name}] 已被删除"
        else:
            msg += f"[{task.name}] "
            msg += (await self.describe_due_time(task_id)) + "，"
            msg += (await self.describe_remind(task_id))+ "，"
            msg += (await self.describe_recurrence(task_id))+ "，"
            msg += (await self.describe_assignee(task_id))

        return msg

    # Task Normal behaviour related
    # include: 
    # - finish (change due time and current assignee, and reschedule remind job)
    # - skip (finish without due time change or rescheduler)

    async def finish_task(self, task_id: uuid.UUID):
        """Mark a task as finished and reschedule if it has recurring intervals."""
        task = await self.__get_task(task_id)
        try:
            assignment = (
                await self.session.execute(
                    select(AssignmentModel)
                    .where(
                        AssignmentModel.task_id == task.id,
                        AssignmentModel.order == task.current_assignment_order
                    )
                )
            ).scalar_one()
        except NoResultFound:
            logger.info(f"No assignment for task {task_id}")
            assignee_id = None
        else:
            assignee_id = assignment.assignee_id

        new_record = RecordModel(
            task_id=task_id,
            assignee_id=assignee_id,
            due_time=task.due_time,
            finish_time=datetime.now()
        )

        self.session.add(new_record)

        match task.recur_type:
            case RecurType.Never:
                await self.remove_reminder(task_id)
                task.due_time = None
                await self.delete_task(task)
            case RecurType.OnFinish:
                task.due_time = datetime.now() + task.recur_interval
                await self.refresh_reminder(task_id)
                if assignee_id is not None:
                    await self.shift_current_assignee_order(task_id, 1)
            case RecurType.Regular:
                task.due_time = task.due_time + task.recur_interval
                await self.refresh_reminder(task_id)
                if assignee_id is not None:
                    await self.shift_current_assignee_order(task_id, 1)

        await self.session.commit()
        await self.session.refresh(task)
        logger.debug(
            f"Finished task {task.id}, next due: {task.due_time}, next assignee: {task.current_assignment_order}")

    async def skip_task(self, task_id: uuid.UUID, offset: int):
        """Mark a task as finished and reschedule if it has recurring intervals."""
        task = await self.__get_task(task_id)

        if len(await self.get_assignee_user_ids(task_id)) <= 1:
            logger.warning(f"Task {task_id} with one or none assignee cannot be skipped")
            return

        await self.shift_current_assignee_order(task_id, offset)

        await self.session.commit()
        await self.session.refresh(task)
        logger.debug(
            f"Skipped task {task.id}, next due: {task.due_time}, next assignee: {task.current_assignment_order}")

    async def purge_wild_jobs(self) -> int:
        # obtain all job id from job store
        apscheduler_job_ids = [job.id for job in scheduler.get_jobs()]
        count = 0

        controlled_job_ids = (
            await self.session.execute(
                select(TaskModel.apscheduler_job_id)
                .where(TaskModel.is_deleted == False)
            )
        ).scalars().all()

        for job_id in apscheduler_job_ids:
            if job_id not in controlled_job_ids:
                scheduler.remove_job(job_id)
                count += 1

        return count


class AssigneeService(Service):
    async def add_assignee(self, user_id: str):
        """Add an assignee"""
        logger.debug(f"Adding assignee {user_id}")
        new_assignee = AssigneeModel(user_id=user_id)
        self.session.add(new_assignee)

        try:
            await self.session.commit()
        except IntegrityError as e:
            logger.debug(f"Duplication detected: {e}, try locating existing assignee id")
            await self.session.rollback()

            return (
                await self.session.execute(
                    select(AssigneeModel.id)
                    .where(AssigneeModel.user_id == user_id)
                )
            ).scalar_one()

        await self.session.refresh(new_assignee)
        return new_assignee.id


async def get_task_service() -> AsyncGenerator[TaskService, None]:
    session = get_scoped_session()
    async with TaskService(session) as task_service:
        yield task_service


async def get_assignee_service() -> AsyncGenerator[TaskService, None]:
    session = get_scoped_session()
    async with AssigneeService(session) as assignee_service:
        yield assignee_service
