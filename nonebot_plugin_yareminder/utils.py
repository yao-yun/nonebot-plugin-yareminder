from enum import Enum as BuiltinEnum
from datetime import datetime, timedelta
import re
import pendulum


class RecurType(BuiltinEnum):
    Never = 0
    OnFinish = 1
    Regular = 2


def natural_lang_date(target_date: datetime, today=None):
    weekday_name = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    answer = ""

    if today is None:
        today = datetime.today()

    target_date = pendulum.instance(target_date)
    today = pendulum.instance(today)

    # 计算日期差（以天为单位）
    days_diff = (target_date.date() - today.date()).days

    # 如果日期相同
    if days_diff == 0:
        answer += "今天"
    elif days_diff == 1:
        answer += "明天"
    elif days_diff == -1:
        answer += "昨天"
    elif days_diff == 2:
        answer += "后天"
    elif days_diff == -2:
        answer += "前天"

    if answer != "":
        return answer + target_date.strftime("%H:%M")

    # 计算日期差的周数
    weeks_diff = (target_date - today).in_weeks()
    weekday = weekday_name[target_date.weekday()]

    # 处理在三周以内的日期
    if weeks_diff == 0:
        answer += f"本{weekday}"
    elif weeks_diff == 1:
        answer += f"下{weekday}"
    elif weeks_diff == 2:
        answer += f"两周后的{weekday}"
    elif weeks_diff == -1:
        answer += f"上{weekday}"
    elif weeks_diff == -2:
        answer += f"两周前的{weekday}"

    if answer != "":
        return answer + target_date.strftime("%H:%M")

    # 如果日期不在三周内，则返回标准日期格式
    return target_date.to_date_string() + target_date.strftime(" %H:%M")


def to_datetime(s: str) -> datetime:
    return pendulum.parse(s)


# From https://gist.github.com/santiagobasulto/698f0ff660968200f873a2f9d1c4113c

TIMEDELTA_REGEX = (r'((?P<days>-?\d+)d)?'
                   r'((?P<hours>-?\d+)h)?'
                   r'((?P<minutes>-?\d+)m)?'
                   r'((?P<seconds>-?\d+)s)?')
TIMEDELTA_PATTERN = re.compile(TIMEDELTA_REGEX, re.IGNORECASE)


def to_timedelta(s: str) -> timedelta:
    """ Parses a human-readable timedelta (3d5h19m1s) into a datetime.timedelta.
    Delta includes:
    * Xd days
    * Xh hours
    * Xm minutes
    * Xs seconds
    Values can be negative following timedelta's rules. Eg: -5h-30m
    """
    match = TIMEDELTA_PATTERN.match(s)
    if match:
        parts = {k: int(v) for k, v in match.groupdict().items() if v}
        return timedelta(**parts)


def to_recurtype(s: str) -> RecurType:
    return RecurType[s]
