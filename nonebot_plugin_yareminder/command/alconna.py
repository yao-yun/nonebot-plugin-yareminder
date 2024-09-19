from ..utils import to_datetime, to_timedelta, to_recurtype, RecurType

from nonebot import require
from datetime import timedelta

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import At
from arclet.alconna import Arg, Alconna, Option, MultiVar, Subcommand

alc = Alconna(
    ":rmd",
    Subcommand("now"),
    Subcommand(
        "add",
        Arg("task_name", str),
        Arg("due_time", to_datetime),
        Option("-i|--remind-interval", Arg("remind_interval", to_timedelta, timedelta(hours=3))),
        Option("-o|--remind-offset", Arg("remind_offset", to_timedelta, timedelta(hours=-24))),
        Option("-t|--recur-type", Arg("recur_type", to_recurtype, RecurType.Regular)),
        Option("-r|--recur-interval", Arg("recur_interval", to_timedelta, timedelta(days=2)))
    ),
    Subcommand("rm", Arg("task_name", str)),
    Subcommand("ls"),
    Subcommand("finish", Arg("?task_name", str)),
    Subcommand("skip", Arg("?task_name", str), Option("--offset", Arg("offset", int, 1))),
    Subcommand(
        "due",
        Arg("task_name", str),
        Option("--shift", Arg("due_shift", to_timedelta)),
        Option("--set", Arg("due_set", to_datetime))
    ),
    Subcommand(
        "remind",
        Arg("task_name", str),
        Option("-o|--offset", Arg("remind_offset", to_timedelta)),
        Option("-i|--interval", Arg("remind_interval", to_timedelta))
    ),
    Subcommand(
        "recur",
        Arg("task_name", str),
        Option("-t|--type", Arg("recur_type", to_recurtype)),
        Option("-i|--interval", Arg("recur_interval", to_timedelta))
    ),
    Subcommand(
        "assign",
        Arg("task_name", str),
        Option("-r|--rm"),
        Arg("?assignees", MultiVar(At))
    )
)
