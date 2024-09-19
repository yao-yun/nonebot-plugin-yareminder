from ..service import TaskService, AssigneeService, get_task_service, get_assignee_service
from .alconna import alc

from nonebot import require, logger
from nonebot.params import Depends
from nonebot.adapters import Event
from typing import Annotated
from uuid import UUID 

require("nonebot_plugin_saa")
from nonebot_plugin_saa import SaaTarget, MessageFactory

require("nonebot_plugin_orm")
from sqlalchemy.exc import NoResultFound, MultipleResultsFound

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import on_alconna, Arparma

rmd_app = on_alconna(alc)

@rmd_app.handle()
async def _(result: Arparma):
    if not result.matched:
        await rmd_app.send(f"命令解析失败。用法：\n{alc.get_help()}")
        await rmd_app.finish()


@rmd_app.assign("now")
async def rmd_now(saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)]):
    task_ids = (await task_service.search_task(scope=saa_target)).scalars().all()
    for task_id in task_ids:
        await task_service.send_reminder(task_id)


@rmd_app.assign("add")
async def rmd_add(result: Arparma, saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)]):
    logger.debug("Adding new task...")

    task_id = await task_service.create_task(
        name=result["add.task_name"],
        due_time=result["add.due_time"],
        remind_offset=result["remind_offset"],
        remind_interval=result["remind_interval"],
        recur_interval=result["recur_interval"],
        recur_type=result["recur_type"],
        platform_target=saa_target
    )
    logger.info(f"Task created: {task_id}")
    await (await task_service.describe_task(task_id)).send()
    logger.debug(f"Feedback sent")
    await rmd_app.finish()


@rmd_app.assign("rm")
async def rmd_delete(result: Arparma, saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)]):
    try:
        task_id: UUID = (await task_service.search_task(result["rm.task_name"], saa_target)).scalar_one()
    except NoResultFound or MultipleResultsFound as e:
        logger.error(f"Unable to query task with name {result['rm.task_name']}: {e}")
        await rmd_app.finish(f"查找任务\"{result['rm.task_name']}\"时发生错误")
    else:
        await task_service.delete_task(task_id)
        await rmd_app.finish(f"任务\"{result['rm.task_name']}\"已删除")


@rmd_app.assign("ls")
async def rmd_ls(saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)]):
    task_ids = (await task_service.search_task(scope=saa_target)).scalars().all()
    msg = MessageFactory("当前会话中任务如下: ")
    logger.debug(f"Listing tasks... Task_ids: {task_ids}")
    for i in range(0, len(task_ids)):
        description = await task_service.describe_task(task_ids[i])
        msg += [f'\n{i+1}. '] + description
    await msg.send()
    await rmd_app.finish()


@rmd_app.assign("finish")
async def rmd_finish(result: Arparma, saa_target: SaaTarget, event: Event, task_service: Annotated[TaskService, Depends(get_task_service)]):
    logger.info(f"Finishing ... Lookup task {result['?task_name']}")

    if not result["?task_name"]:
        logger.info(f"Try finish task in current chat for current user if one and only")
        logger.debug(f"current chat: {saa_target}, current user: {event.get_user_id()}")
        task_ids = (await task_service.search_task(scope=saa_target, user_id=event.get_user_id(), include_deleted=False)).scalars().all()
        if not task_ids:
            await rmd_app.finish("你在当前聊天下无任务")
        elif len(task_ids) > 1:
            msg = MessageFactory(["你在当前聊天下有多个任务, 请使用 '... finish <task_name> 指明要完成/跳过的任务'\n"])
            msg_count = 0
            for task_id in task_ids:
                msg_count += 1
                msg += [f"{msg_count}. ", await task_service.describe_task(task_id), " \n"]
            await rmd_app.finish()
        else:
            await task_service.finish_task(task_ids[0])
            await (await task_service.describe_task(task_ids[0])).send()
    else:
        try:
            task_id = (await task_service.search_task(task_name=result["?task_name"], scope=saa_target)).scalar_one()
        except NoResultFound:
            await rmd_app.finish(f"当前聊天下无“{result['?task_name']}”任务")
        else:
            await task_service.finish_task(task_id)
            await ("任务已完成，下一次：" + await task_service.describe_task(task_id)).send()


@rmd_app.assign("skip")
async def rmd_skip(result: Arparma, saa_target: SaaTarget, event: Event, task_service: Annotated[TaskService, Depends(get_task_service)]):
    offset = result["offset"]
    logger.info(f"Skipping by {offset} ... Lookup task {result['?task_name']}")

    if not result["?task_name"]:
        logger.info(f"Try skip task in current chat for current user if one and only")
        logger.debug(f"current chat: {saa_target}, current user: {event.get_user_id()}")
        task_ids = (await task_service.search_task(scope=saa_target, user_id=event.get_user_id(), include_deleted=False)).scalars().all()

        if not task_ids:
            await rmd_app.finish("你在当前聊天下无任务")
        elif len(task_ids) > 1:
            msg = MessageFactory(["你在当前聊天下有多个任务, 请使用 '... skip <task_name> 指明要完成/跳过的任务'\n"])
            msg_count = 0
            for task_id in task_ids:
                msg_count += 1
                msg += [f"{msg_count}. ", await task_service.describe_task(task_id), " \n"]
            await rmd_app.finish()
        else:
            await task_service.skip_task(task_ids[0], offset)
            await (await task_service.describe_task(task_ids[0])).send()
    else:
        try:
            task_id = (await task_service.search_task(task_name=result["?task_name"], scope=saa_target)).scalar_one()
        except NoResultFound:
            await rmd_app.finish(f"当前聊天下无“{result['?task_name']}”任务")
        else:
            await task_service.skip_task(task_id, offset)
            await ("任务已跳过，下一次：" + await task_service.describe_task(task_id)).send()


@rmd_app.assign("due")
async def rmd_due(result: Arparma, saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)]):
    task_id = (await task_service.search_task(task_name=result["due.task_name"], scope=saa_target)).scalar_one()
    if result["due_shift"]:
        await task_service.set_task(task_id, due_time=result["due_shift"])
    elif result["due_set"]:
        await task_service.set_task(task_id, due_time=result["due_set"])

    msg = await task_service.describe_due_time(task_id)
    await msg.send()


@rmd_app.assign("remind")
async def rmd_remind(result: Arparma, saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)]):
    task_id = (await task_service.search_task(task_name=result["remind.task_name"], scope=saa_target)).scalar_one()

    if result["remind_offset"]:
        await task_service.set_task(task_id, remind_offset=result["remind_offset"])
    if result["remind_interval"]:
        await task_service.set_task(task_id, remind_interval=result["remind_interval"])

    msg = await task_service.describe_remind(task_id)
    await msg.send()


@rmd_app.assign("recur")
async def rmd_recur(result: Arparma, saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)]):
    task_id = (await task_service.search_task(task_name=result["assign.task_name"], scope=saa_target)).scalar_one()

    if result["recur_type"]:
        await task_service.set_task(task_id, recur_type=result["recur_type"])
    if result["recur_interval"]:
        await task_service.set_task(task_id, recur_interval=result["recur_interval"])

    msg = await task_service.describe_recurrence(task_id)
    await msg.send()


@rmd_app.assign("assign")
async def rmd_assign(result: Arparma, saa_target: SaaTarget, task_service: Annotated[TaskService, Depends(get_task_service)], assignee_service: AssigneeService = Depends(get_assignee_service)):
    task_id = (await task_service.search_task(task_name=result["assign.task_name"], scope=saa_target)).scalar_one()
    assignee_ats = result["assign.?assignees"]

    if assignee_ats is not None:
        logger.info(f"Try adding / finding corresponding assignees to {assignee_ats}")
        user_ids = [at.target for at in assignee_ats]
        logger.debug(f"User ids: {user_ids}")
        assignee_ids = [(await assignee_service.add_assignee(user_id)) for user_id in user_ids]
        logger.debug(f"Assignee ids: {assignee_ids}")
        if result['options.rm']:
            await task_service.remove_assignments(task_id, assignee_ids)
        else:
            await task_service.create_assignments(task_id, assignee_ids)

    msg = await task_service.describe_assignee(task_id)
    await msg.send()
