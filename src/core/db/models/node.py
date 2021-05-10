# -*- coding: utf-8 -*-
import discord.webhook
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import relationship

from . import Base
from ._types import Snowflake


class Node(Base):
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
        return self.status != 0
