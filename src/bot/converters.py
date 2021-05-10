# -*- coding: utf-8 -*-
from datetime import timedelta
from re import findall

from discord.ext import commands


duration_to_seconds = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
    "M": 4 * 7 * 24 * 60 * 60,
}


class DurationConverter(commands.Converter):
    async def convert(self, ctx, argument):
        seconds = 0
        for match in findall(r"(\d+)([a-zA-Z])?", argument):
            match = list(match)
            number_string, unit = match
            number = int(number_string)
            multiplier = duration_to_seconds.get(unit, None)
            if multiplier:
                seconds += multiplier * number
            else:
                raise commands.BadArgument(
                    message=(
                        f"Invalid time unit passed, should be one of: "
                        f"{', '.join(duration_to_seconds.keys())}"
                    )
                )

        if seconds == 0:
            raise commands.BadArgument()

        return timedelta(seconds=seconds)
