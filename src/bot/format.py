# -*- coding: utf-8 -*-
from datetime import datetime

import discord


def format_time(dt: datetime) -> str:
    """Format a given datetime in a standard format.

    Args:
        dt (datetime): The datetime to format.

    Returns:
        str: The formatted string. If dt is None, returns ``"the end of time"``
    """
    if dt is None:
        return "`the end of time`"
    return dt.strftime("`%d-%b-%Y @ %H:%M:%S%Z`")


def format_user(u: discord.User) -> str:
    """Format a given user in a standard format.

    Args:
        u (discord.User): The user to format

    Returns:
        str: The formatted string. If u is None, returns ``"Unknown User"``
    """
    if u is None:
        return "`Unknown User`"

    return f"`@{u.name}#{u.discriminator} ({u.id})`"
