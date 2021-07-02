# -*- coding: utf-8 -*-
import discord.webhook
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import relationship

from . import Base, SharedAttributes
from ._types import Snowflake


class StatusCode:
    NONE = 0
    WEBHOOK_NOT_FOUND = 1
    WEBHOOK_NOT_AUTHORIZED = 2
    WEBHOOK_HTTP_EXCEPTION = 3


class Node(Base, SharedAttributes):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True)

    stream_id = Column(ForeignKey("streams.id", ondelete="CASCADE"), nullable=False)
    stream = relationship("Stream", back_populates="nodes")

    guild_id = Column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    guild = relationship("Guild", back_populates="nodes")
    channel_id = Column(Snowflake, nullable=False)
    webhook_id = Column(Snowflake, nullable=False)
    webhook_token = Column(String, nullable=False)

    status = Column(Integer, nullable=False, default=0)

    def webhook_url(self):
        return (
            f"https://discord.com/api/webhooks/{self.webhook_id}/{self.webhook_token}"
        )

    def webhook(self):
        url = self.webhook_url()
        return discord.webhook.Webhook.from_url(
            url, adapter=discord.RequestsWebhookAdapter()
        )

    @property
    def disabled(self):
        return self.status != 0 or self.guild.disabled

    def mark_not_found(self):
        self.status = StatusCode.WEBHOOK_NOT_FOUND

    def mark_not_authorized(self):
        self.status = StatusCode.WEBHOOK_NOT_AUTHORIZED

    def mark_http_exception(self):
        self.status = StatusCode.WEBHOOK_HTTP_EXCEPTION
