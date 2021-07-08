# -*- coding: utf-8 -*-
from discord.ext import commands


class ItemNotFound(commands.CommandError):
    def __init__(self, model, *args):
        super().__init__(*args)
        self.model_name = model.__tablename__.upper()

        # Generic error message
        self.message = self.model_name + "_NOT_FOUND"


class NotManaging(commands.CommandError):
    pass


class BannedUser(commands.CommandError):
    def __init__(self, level, *args):
        super().__init__(*args)
        self.level = level
