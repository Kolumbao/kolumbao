# -*- coding: utf-8 -*-
__all__ = ["session", "Database", "query"]

import asyncio
import uuid
import warnings

import discord.ext.commands as commands
from sqlalchemy import create_engine, orm, util
from sqlalchemy.orm import scoped_session, sessionmaker
from werkzeug.local import LocalProxy

from .models import Base


class Database:
    _instance = None

    @classmethod
    def _get_task(cls) -> asyncio.Task:
        try:
            return asyncio.current_task()
        except RuntimeError:
            return None

    @classmethod
    def _get_context_unique_id(cls) -> int:
        coro = cls._get_task()
        if coro:
            if hasattr(coro, "_db_unique_id"):
                return coro._db_unique_id

            return id(coro)
        return 1  # dont fail, just treat outside a command as a single session

    def __init__(self, uri: str, bot=None) -> None:
        """
        Database class for handling database connections in a discord.ext.commands bot.

        setup: either pass bot here or call Database.init_bot(bot) later
        """
        if not Database._instance:
            Database._instance = self
        else:
            warnings.warn(
                "multiple database connections established, "
                "discarding current and using first one.",
                RuntimeWarning,
            )
            return
        if bot:
            self.init_bot(bot)

        kwargs = dict(pool_size=20, max_overflow=40)
        if uri.startswith("sqlite"):
            kwargs = dict()
        self.engine = create_engine(uri, **kwargs)
        Base.metadata.create_all(self.engine)
        self._session = scoped_session(
            sessionmaker(expire_on_commit=False, bind=self.engine),
            scopefunc=self._get_context_unique_id,
        )

    @classmethod
    def set_task_uuid(cls):
        cls._get_task()._db_unique_id = uuid.uuid4()

    @classmethod
    def decorate(cls, f):
        async def wrapped(*args, **kwargs):
            cls.set_task_uuid()
            result = await f(*args, **kwargs)
            cls._get_session_class().remove()
            return result

        return wrapped

    @classmethod
    def init_bot(cls, bot: commands.Bot) -> None:
        """Initializes the database to work with this discord bot."""

        bot._run_event = cls.decorate(bot._run_event)

        async def pre(_):
            cls.set_task_uuid()

        async def post(_):
            cls._get_session_class().remove()

        bot.before_invoke(pre)
        bot.after_invoke(post)

    @classmethod
    def _get_session_class(cls) -> None:
        if cls._instance:
            return cls._instance._session

        raise AttributeError(
            f"Database not yet initialized. "
            f"Please instantiate {cls.__module__}.{cls.__name__} first"
        )

    @classmethod
    def _get_session(cls) -> orm.Session:
        return cls._get_session_class()()

    @classmethod
    def sessions_registry(cls) -> util._collections.ScopedRegistry:
        return cls._get_session_class().registry

    @classmethod
    def num_open_sessions(cls) -> int:
        return len(cls.sessions_registry().registry)


session = LocalProxy(Database._get_session)


def query(*args, **kwargs) -> orm.Query:
    return Database._get_session().query(*args, **kwargs)
