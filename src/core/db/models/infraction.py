# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.orm import synonym

from . import Base, SharedAttributes


# There are 3 types of infraction:
# - mute: Stops speaking.
# - warn: Verbal warning.
# - ban:  Stops usage of bot and depending on severity, also prevents bot
#         working in servers you're in.

class Mute(Base, SharedAttributes):
    __tablename__ = "mutes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", backref="mutes", foreign_keys=[user_id])

    mod_id = Column(Integer, ForeignKey("users.id"))
    mod = relationship("User", backref="mutes_made", foreign_keys=[mod_id])

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)

    reason = Column("reason", String)

    @classmethod
    def create(cls, user: "User", mod: "User", reason: str, duration: timedelta):
        start_time = datetime.now()
        end_time = None
        if duration is not None:
            end_time = start_time + duration
        
        return cls(
            user_id = user.id,
            mod_id = mod.id,
            start_time = start_time,
            end_time = end_time,
            reason = reason
        )

class Warn(Base, SharedAttributes):
    __tablename__ = "warns"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", backref="warns", foreign_keys=[user_id])

    mod_id = Column(Integer, ForeignKey("users.id"))
    mod = relationship("User", backref="warns_made", foreign_keys=[mod_id])

    reason = Column("reason", String)

    @classmethod
    def create(cls, user: "User", mod: "User", reason: str):
        return cls(
            user_id = user.id,
            mod_id = mod.id,
            reason = reason
        )

class BanSeverity:
    # User can not use bot or commands
    USER = 0

    # Server made by user can not use bot
    SERVER = 1

    # User can not be in server with Kolumbao
    BLANKET = 2


class Ban(Base, SharedAttributes):
    __tablename__ = "bans"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", backref="bans", foreign_keys=[user_id])

    mod_id = Column(Integer, ForeignKey("users.id"))
    mod = relationship("User", backref="bans_made", foreign_keys=[mod_id])

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)

    reason = Column("reason", String)
    severity = Column("severity", Integer, default=BanSeverity.USER)

    @classmethod
    def create(cls, user: "User", mod: "User", reason: str, severity: int, duration: timedelta):
        start_time = datetime.now()
        end_time = None
        if duration is not None:
            end_time = start_time + duration
        
        return cls(
            user_id = user.id,
            mod_id = mod.id,
            start_time = start_time,
            end_time = end_time,
            reason = reason,
            severity = severity
        )
