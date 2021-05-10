# -*- coding: utf-8 -*-
from typing import Any
from typing import Optional

from . import query
from . import session
from .models import Feature
from .models import Guild
from .models import Stream
from .models import User
from core.db.models.blacklist import Blacklist


def _get_discord_equivalent(
    model, snowflake: int, default_kwargs, make_if_missing: bool = True
) -> Optional[Any]:
    """
    Get an object of type `model` from the database, or create it if it
    doesn't already exist.

    Parameters
    ----------
    model : any
        The database model
    snowflake : int
        The snowflake to use in the query
    default_kwargs : dict
        Default arguments to make the object with if it doesn't exist
    make_if_missing : bool, optional
        Make the object if it doesn't exist already, by default True

    Returns
    -------
    model, or None
        The result of the function
    """

    obj = query(model).filter(model.discord_id == snowflake).first()

    if make_if_missing and obj is None:
        obj = model(discord_id=snowflake, **default_kwargs)
        session.add(obj)
    return obj


_default_user_kwargs = dict(language="en", system=False, points=0)


def get_user(snowflake: int, make_if_missing: bool = True) -> Optional[User]:
    """
    Get a user from the database using :func:`_get_discord_equivalent`

    Parameters
    ----------
    snowflake : int
        The snowflake to use in the query
    make_if_missing : bool, optional
        Make the object if it doesn't exist already, by default True

    Returns
    -------
    User, or None
        The user
    """
    return _get_discord_equivalent(
        User, snowflake, _default_user_kwargs, make_if_missing
    )


_default_guild_kwargs = dict(banned=False)


def get_guild(snowflake: int, make_if_missing: bool = True) -> Optional[Guild]:
    """
    Get a guild from the database using :func:`_get_discord_equivalent`

    Parameters
    ----------
    snowflake : int
        The snowflake to use in the query
    make_if_missing : bool, optional
        Make the object if it doesn't exist already, by default True

    Returns
    -------
    Guild, or None
        The guild
    """
    return _get_discord_equivalent(
        Guild, snowflake, _default_guild_kwargs, make_if_missing
    )


def get_feature(name: str) -> Optional[Feature]:
    """
    Get a feature from the database

    Parameters
    ----------
    name : str
        The name of the feature to search for

    Returns
    -------
    Feature, or None
        The feature
    """
    return query(Feature).filter(Feature.name == name).first()


def get_stream(name: str) -> Optional[Stream]:
    """
    Get a stream from the database

    Parameters
    ----------
    name : str
        The name of the stream to search for

    Returns
    -------
    Stream, or None
        The stream
    """
    return query(Stream).filter(Stream.name == name).first()


def get_blacklist(name: str) -> Optional[Blacklist]:
    """
    Get a blacklist from the database

    Parameters
    ----------
    name : str
        The name of the blacklist to search for

    Returns
    -------
    Blacklist, or None
        The blacklist
    """
    return query(Blacklist).filter(Blacklist.name == name).first()
