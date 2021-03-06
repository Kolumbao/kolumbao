# -*- coding: utf-8 -*-
import math
from datetime import datetime
from typing import Optional, Tuple
import discord

from discord.ext import commands
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import relationship

from core.db.models.infraction import Ban, Mute

from . import Base, SharedAttributes
from ._types import Snowflake

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("role_id", Integer, ForeignKey("roles.id")),
)


class User(Base, SharedAttributes):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    discord_id = Column(Snowflake, unique=True)

    roles = relationship("Role", secondary=user_roles)
    emojis = association_proxy("roles", "emoji")

    language = Column(String)
    system = Column(Boolean, server_default="false")
    system_name = Column(String)
    system_avatar = Column(String)

    points = Column(Integer, nullable=False, default=0, server_default="0")

    streams = relationship("Stream", back_populates="user")
    staff_in = relationship("Stream", secondary="stream_staff")

    def missing_permissions(self, *required_perms):
        permissions = self.permissions
        missing = set(required_perms) - set(permissions)
        return missing

    def has_permissions(self, *required_perms) -> bool:
        if self._bot and self.is_owner(self.bot):
            return True

        if len(self.missing_permissions(*required_perms)) == 0:
            return True

        return False

    @property
    def permissions(self):
        permissions = []
        for role in self.roles:
            permissions.extend(role.permissions)

        return list(set(permissions))

    @property
    def staff(self):
        return any(role.staff for role in self.roles)

    @property
    def level(self):
        return self._points_to_level(self.points)

    @property
    def points_to_next_level(self):
        return self._points_to_next_level(self.points)

    def is_muted(self):
        last = self.last_mute()

        if last is None:
            return False

        return last.end_time is None or last.end_time > datetime.now()

    def last_mute(self) -> Mute:
        mutes = sorted(self.mutes, key=lambda i: i.start_time, reverse=True)

        if len(mutes) == 0:
            return None

        return mutes[0]
    
    def is_banned(self):
        last = self.last_ban()

        if last is None:
            return False

        return last.end_time is None or last.end_time > datetime.now()

    def last_ban(self) -> Ban:
        bans = sorted(self.bans, key=lambda i: i.start_time, reverse=True)

        if len(bans) == 0:
            return None

        return bans[0]

    def last_seen(self):
        messages = sorted(self.messages, key=lambda m: m.sent_at)
        if len(messages) == 0:
            return None

        return messages[-1].node

    def is_owner(self, bot: commands.Bot):
        return bot.owner_id == self.discord_id

    @staticmethod
    def _points_to_level(points: int) -> int:
        return math.floor((math.sqrt(625 + 100 * points) - 25) / 50)

    @staticmethod
    def _level_to_points(level: int) -> int:
        return 25 * level * (1 + level)

    @staticmethod
    def _points_to_next_level(points: int) -> Tuple[int, int]:
        level = User._points_to_level(points)
        base_points = User._level_to_points(level)
        next_points = User._level_to_points(level + 1)
        gap_points = next_points - base_points
        return gap_points - (next_points - points), gap_points