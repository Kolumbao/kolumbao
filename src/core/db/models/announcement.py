# -*- coding: utf-8 -*-
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String

from . import Base, SharedAttributes


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True)

    content = Column(String, nullable=False)
    lang = Column(String, nullable=False, server_default="en")
    priority = Column(Integer, nullable=False, server_default="1")
