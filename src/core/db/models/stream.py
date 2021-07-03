# -*- coding: utf-8 -*-
import hashlib
import os
from typing import List

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import func
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import relationship
from core.db.models.role import Permissions

from . import Base, SharedAttributes
from core.db.database import query
from core.db.models.message import OriginMessage

stream_features = Table(
    "stream_features",
    Base.metadata,
    Column("stream_id", Integer, ForeignKey("streams.id")),
    Column("feature_id", Integer, ForeignKey("features.id")),
)


stream_staff = Table(
    "stream_staff",
    Base.metadata,
    Column("stream_id", Integer, ForeignKey("streams.id")),
    Column("user_id", Integer, ForeignKey("users.id")),
)
BASIC_PERMISSIONS = [Base]


class Feature(Base):
    __tablename__ = "features"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class Stream(Base, SharedAttributes):
    __tablename__ = "streams"

    @classmethod
    def create(cls, name: str, create_default: bool = False) -> "Stream":
        # Circular import avoiding
        from .. import query, session

        dbobject = query(cls).filter(cls.name == name).first()
        if dbobject is None and create_default:
            dbobject = cls(name=name)
            session.add(dbobject)
        
        return dbobject

    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(String)
    language = Column(String, default="en")
    rules = Column(String)
    lockdown = Column(Integer, server_default="0")
    nsfw = Column(Boolean, server_default="0")
    password = Column(String)

    feats = relationship("Feature", secondary=stream_features)
    features = association_proxy("feats", "name")

    staff = relationship("User", secondary=stream_staff)

    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="streams")

    messages = relationship("OriginMessage", back_populates="stream")
    nodes = relationship(
        "Node", back_populates="stream", cascade="all, delete", passive_deletes=True
    )

    @property
    def official(self):
        return "OFFICIAL" in self.features

    def suppressed_filters(self):
        suppressed_filters = []
        for feature in self.features:
            if feature.startswith("SUPPRESS_"):
                suppressed_filters.append(feature.replace("SUPPRESS_", ""))

        return suppressed_filters

    def suppressed_blacklists(self):
        suppressed_blacklist = []
        for feature in self.features:
            if feature.startswith("WHITELIST_"):
                suppressed_blacklist.append(feature.replace("WHITELIST_", ""))

        return suppressed_blacklist

    def set_password(self, password: str = None):
        if password is None:
            self.password = None
        else:
            salt = os.urandom(32)
            key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)

            self.password = salt + key

    def check_password(self, password: str) -> bool:
        salt = self.password[:32]
        key = self.password[32:]

        new_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)

        return key == new_key

    @property
    def message_count(self):
        return query(func.count(OriginMessage.id)).filter_by(stream_id=self.id).scalar()

    def has_permissions(self, user: "User", *required_perms: List[str]):
        """
        Check if the given user can perform the action in this stream

        :param user: The user to check for
        :type user: User
        """
        # Based on user perms
        if user.has_permissions(*required_perms):
            return True

        # Based on channel staff
        if user in self.staff and required_perms == [Permissions.MANAGE_MESSAGES]:
            return True
        
        return False

