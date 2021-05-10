# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional

from ..db import query
from ..db import session
from ..db.models import Infraction
from ..db.models import User


def add_infraction(
    type_: str,
    moderator: User,
    user: User,
    end_time: Optional[datetime] = None,
    reason: Optional[str] = None,
) -> Infraction:
    """Add an infraction for ``user`` of type ``type_``

    Parameters
    ----------
    type_ : str
        The infraction type. ``mute`` or ``warning``
    moderator : User
        The user that is creating the infraction
    user : User
        The user that is receiving the infraction
    end_time : datetime, optional
        The expiration date of the infraction, or None, by default None
    reason : str, optional
        The reason to add to the infraction, by default None

    Returns
    -------
    Infraction
        The infraction that was created and added to the database

    Raises
    ------
    ValueError
        The ``end_time`` parameter is smaller than the current time, hence
        invalid
    """
    if end_time is not None and end_time < datetime.now():
        raise ValueError("parameter end_time smaller than current time (invalid)")

    infraction = Infraction(
        mod_id=moderator.id,
        user_id=user.id,
        start_time=datetime.now(),
        end_time=end_time,
        _reason=reason,
        _type_=type_,
    )

    session.add(infraction)
    session.commit()

    return infraction


def remove_infraction(id_: int):
    """
    Remove an infraction of ID ``id_``

    Parameters
    ----------
    id_ : int
        The ID to search for

    Raises
    ------
    ValueError
        If the infraction wasn't found
    """
    infraction = query(Infraction).get(id_)
    if infraction is None:
        raise ValueError("infraction {} not found".format(id_))

    session.remove(infraction)
    session.commit()


def add_mute(
    moderator: User,
    user: User,
    end_time: Optional[datetime] = None,
    reason: Optional[str] = None,
) -> Infraction:
    """
    Wraps :func:`add_infraction` to create an infraction of ``mute`` type

    Parameters
    ----------
    moderator : User
        The user that is creating the infraction
    user : User
        The user that is receiving the infraction
    end_time : datetime, optional
        The expiration date of the infraction, or None, by default None
    reason : str, optional
        The reason to add to the infraction, by default None

    Returns
    -------
    Infraction
        The created infraction

    Raises
    ------
    ValueError
        The user is already muted (obtained from :func:`User.is_muted`)
    """
    if user.is_muted():
        raise ValueError("this user is already muted")

    return add_infraction("mute", moderator, user, end_time, reason)


def add_warning(
    moderator: User,
    user: User,
    end_time: Optional[datetime] = None,
    reason: Optional[str] = None,
) -> Infraction:
    """
    Wraps :func:`add_infraction` to create an infraction of ``warning`` type

    Parameters
    ----------
    moderator : User
        The user that is creating the infraction
    user : User
        The user that is receiving the infraction
    end_time : datetime, optional
        The expiration date of the infraction, or None, by default None
    reason : str, optional
        The reason to add to the infraction, by default None

    Returns
    -------
    Infraction
        The created infraction
    """
    return add_infraction("warning", moderator, user, end_time, reason)
