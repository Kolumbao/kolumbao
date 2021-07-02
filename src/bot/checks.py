# -*- coding: utf-8 -*-
from discord.ext import commands

from core.db.database import query
from core.db.database import session
from core.db.models import Permission
from core.db.models.user import User


class InsufficientPermissions(commands.CommandError):
    def __init__(self, permissions, *args, **kwargs):
        self.permissions = permissions
        super().__init__(*args, **kwargs)


class InsufficientLevel(commands.CommandError):
    def __init__(self, level, *args, **kwargs):
        self.level = level
        super().__init__(*args, **kwargs)


def has_permission(*permissions: list):
    """
    Permission check that checks whether the current user has *all* of the given
    permissions on their database profile.
    """
    # Ensure they exist
    names = query(Permission.name).all()
    for permission in permissions:
        if (permission,) not in names:
            session.add(Permission(name=permission))

            session.commit()

    async def predicate(ctx):
        if len(permissions) == 0:
            return True

        user = User.create(ctx.author)
        if user.has_permissions(*permissions, bot=ctx.bot):
            return True

        raise InsufficientPermissions(list(user.missing_permissions(*permissions)))

    return commands.check(predicate)


def requires_level(level: int):
    async def predicate(ctx):
        user = User.create(ctx.author)
        if user.level >= level or await ctx.bot.is_owner(ctx.author):
            return True

        raise InsufficientLevel(level)

    return commands.check(predicate)
