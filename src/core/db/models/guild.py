# -*- coding: utf-8 -*-
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy.orm import relationship

from . import Base
from ._types import Snowflake


class Guild(Base):
    __tablename__ = "guilds"

    id = Column(Integer, primary_key=True)

    discord_id = Column(Snowflake, nullable=False)
    banned = Column(Boolean, nullable=False, default=False)

    nodes = relationship(
        "Node", back_populates="guild", cascade="all, delete", passive_deletes=True
    )
