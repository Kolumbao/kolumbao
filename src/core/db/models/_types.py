# -*- coding: utf-8 -*-
from sqlalchemy.types import BigInteger
from sqlalchemy.types import TypeDecorator


class Snowflake(TypeDecorator):
    """
    Custom type for sqlalchemy that is used for snowflakes.

    .. seealso::
        This now bases itself on `BigInteger`, so it is unnecessary to use this
        type (technically speaking). However to differentiate values, it is not
        catastrophic to use it.

        See `BigInteger`
    """
    impl = BigInteger

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = int(value)

        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = int(value)

        return value
