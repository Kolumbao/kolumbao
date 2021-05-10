# -*- coding: utf-8 -*-
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String

from . import Base


class Snippet(Base):
    __tablename__ = "snippets"

    id = Column(Integer, primary_key=True)

    name = Column(String, nullable=False)
    content = Column(String, nullable=False)
