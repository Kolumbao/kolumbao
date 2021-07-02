# -*- coding: utf-8 -*-
from typing import Optional
import discord
from sqlalchemy import Boolean, Column, Integer
from sqlalchemy.orm import relationship

from . import Base, SharedAttributes
from ._types import Snowflake


class StatusCode:
    NONE = 0
    MANUALLY_DISABLED = 1
    AUTO_USER_DISABLED = 2
    AWAITING_AUTO_DISABLE = 3

class Guild(Base, SharedAttributes):
    __tablename__ = "guilds"
    
    id = Column(Integer, primary_key=True)

    discord_id = Column(Snowflake, nullable=False)
    status = Column(Integer, nullable=False, default=0)

    nodes = relationship(
        "Node", back_populates="guild", cascade="all, delete", passive_deletes=True
    )

    @property
    def disabled(self):
        return self.status != 0
