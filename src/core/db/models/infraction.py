# -*- coding: utf-8 -*-
from datetime import timedelta

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.orm import synonym

from . import Base


class Infraction(Base):
    __tablename__ = "infs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", backref="infs", foreign_keys=[user_id])

    mod_id = Column(Integer, ForeignKey("users.id"))
    mod = relationship("User", backref="infs_made", foreign_keys=[mod_id])

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)

    _reason = Column("reason", String)
    _type_ = Column("type_", String)

    @hybrid_property
    def duration(self):
        return self.end_time - self.start_time

    @duration.setter
    def duration(self, value: timedelta):
        if isinstance(value, timedelta):
            self.end_time = self.start_time + value
        elif value is None:
            self.end_time = None
        else:
            raise TypeError("EDIT_INF__INVALID_TYPE")

    # https://gist.github.com/luhn/4170996
    # info on why property is used and not hybrid_property
    @property
    def type_(self):
        return self._type_

    @type_.setter
    def type_(self, value):
        if isinstance(value, str) or value is None:
            self._type_ = value
        else:
            raise TypeError("EDIT_INF__INVALID_TYPE")

    type_ = synonym("_type_", descriptor=type_)

    @property
    def reason(self):
        return self._reason

    @reason.setter
    def reason(self, value):
        if isinstance(value, str) or value is None:
            self._reason_ = value
        else:
            raise TypeError("EDIT_INF__INVALID_TYPE")

    reason = synonym("_reason", descriptor=reason)
