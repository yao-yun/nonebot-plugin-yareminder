from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

from .command import rmd_app

require('nonebot_plugin_saa')
require('nonebot_plugin_alconna')

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-yareminder",
    description="Yet another reminder plugin supporting per-task configuration and check-in.",
    usage=":rmd COMMAND [ARGS] [OPTIONS]",
    type="application",
    homepage="https://github.com/yao-yun/nonebot-plugin-yareminder",
    supported_adapters=inherit_supported_adapters('nonebot_plugin_saa', 'nonebot_plugin_alconna')
)

from nonebot_plugin_saa import enable_auto_select_bot
enable_auto_select_bot()

require("nonebot_plugin_localstore")
from nonebot_plugin_localstore import get_data_dir

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
scheduler.add_jobstore(
    SQLAlchemyJobStore(url="sqlite:///" + str(get_data_dir(__plugin_meta__.name) / "apscheduler.sqlite3")),
    alias='nonebot-plugin-yareminder-jobstore'
)
