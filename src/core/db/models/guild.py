# -*- coding: utf-8 -*-
from typing import Optional
import discord
from sqlalchemy import Boolean, Column, Integer
from sqlalchemy.orm import relationship

from . import Base, SharedAttributes
from ._types import Snowflake


class StatusCode:
    NONE = 0
    DISABLED = 1
    AWAITING_DISABLE = 2
    MANUALLY_DISABLED = 3

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
        return self.status in [StatusCode.DISABLED, StatusCode.MANUALLY_DISABLED]
