# -*- coding: utf-8 -*-
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import relationship

from . import Base
from .user import user_roles


user_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id")),
    Column("permission_id", Integer, ForeignKey("permissions.id")),
)


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class Permissions:
    """
    Basic permissions list
    """
    INSPECT_CHANNELS = "INSPECT_CHANNELS"
    MANAGE_ROLES = "MANAGE_ROLES"
    MANAGE_MESSAGES = "MANAGE_MESSAGES"
    MANAGE_PERMISSIONS = "MANAGE_PERMISSIONS"
    MANAGE_SNIPPETS = "MANAGE_SNIPPETS"
    MANAGE_FEATURES = "MANAGE_FEATURES"
    MANAGE_MUTES = "MANAGE_MUTES"
    MANAGE_BLACKLISTS = "MANAGE_BLACKLISTS"
    VIEW_ADVANCED_STATS = "VIEW_ADVANCED_STATS"

    def __getattribute__(self, name: str) -> Permission:
        from .. import query

        try:
            raw = object.__getattribute__(self, name)
        except AttributeError as exc:
            raise exc
        else:
            return query(Permission).filter(Permission.name == name).first() or Permission(name=name)

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=True)
    staff = Column(Boolean, nullable=False, default=False)

    perms = relationship("Permission", secondary=user_permissions)
    permissions = association_proxy("perms", "name")

    users = relationship("User", secondary=user_roles)

    def __str__(self):
        return f"{self.name} {self.emoji}"
