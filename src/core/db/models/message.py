# -*- coding: utf-8 -*-
from datetime import datetime
from datetime import timedelta

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import relationship

from . import Base
from ._types import Snowflake


class OriginMessage(Base):
    __tablename__ = "origin_messages"

    id = Column(Integer, primary_key=True)

    user_id = Column(ForeignKey("users.id"))
    user = relationship("User", backref="messages")

    message_id = Column(Snowflake, nullable=False)

    node_id = Column(ForeignKey("nodes.id"))
    node = relationship("Node", backref="origin_messages")

    stream_id = Column(ForeignKey("streams.id"))
    stream = relationship("Stream", back_populates="messages")

    content = Column(String, nullable=True)
    sent_at = Column(DateTime, nullable=False, default=datetime.now)

    result_messages = relationship(
        "ResultMessage",
        back_populates="origin",
        cascade="all, delete",
        passive_deletes=True,
    )

    @property
    def channel_id(self):
        return self.node.channel_id

    @property
    def guild_id(self):
        return self.node.guild_id

    @property
    def discord_sent_at(self):
        return datetime.utcfromtimestamp(
            ((self.message_id >> 22) + 1420070400000) / 1000
        )

    def delay(self):
        delays = list(map(lambda m: m.sent_at - self.sent_at, self.result_messages))

        if len(delays) == 0:
            return timedelta(0), timedelta(0), timedelta(0)

        return max(delays), min(delays), sum(delays, timedelta(0)) / len(delays)


class ResultMessage(Base):
    __tablename__ = "result_messages"

    id = Column(Integer, primary_key=True)
    message_id = Column(Snowflake, nullable=False)

    node_id = Column(ForeignKey("nodes.id"))
    node = relationship("Node", backref="result_messages", cascade="all, delete", passive_deletes=True)

    origin_id = Column(ForeignKey("origin_messages.id", ondelete="CASCADE"))
    origin = relationship("OriginMessage", back_populates="result_messages",  cascade="all, delete", passive_deletes=True)

    @property
    def channel_id(self):
        return self.node.channel_id

    @property
    def guild_id(self):
        return self.node.guild_id

    @property
    def user(self):
        return self.origin.user

    @property
    def sent_at(self):
        return datetime.utcfromtimestamp(
            ((self.message_id >> 22) + 1420070400000) / 1000
        )
