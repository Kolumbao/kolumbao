# -*- coding: utf-8 -*-
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String

from . import Base, SharedAttributes


class Blacklist(Base, SharedAttributes):
    __tablename__ = "blacklists"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    value = Column(String, nullable=False)
