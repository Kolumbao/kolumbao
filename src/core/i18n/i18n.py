# -*- coding: utf-8 -*-
import contextvars
from typing import Dict

import discord
from discord.ext import commands
from yaml import load
from yaml import Loader

from ..db.utils import get_user


class LocaleError(Exception):
    pass


class StringError(Exception):
    pass


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


# If during this session there were missing translations, this is set to True
missing_translations = contextvars.ContextVar("locale")


class I18n:
    bot = None
    _locale = contextvars.ContextVar("locale")
    locales = []
    _instance = None

    def __init__(self, locales, default="en", bot: commands.Bot = None):
        if I18n._instance is None:
            self.default = default
            self.locales = list(locales.keys())
            self._translations = {}

            for locale in self.locales:
                try:
                    print(f"Loading {locale} from {locales[locale]}...")
                    self._translations[locale] = load(
                        open(locales[locale], mode="r", encoding="utf-8").read(),
                        Loader=Loader,
                    )
                except Exception:
                    print(f"Failed to load translations for {locale}")

            I18n._instance = self
            I18n.locales = [
                (I18n.get_string("LANGUAGE_NAME", False, locale=locale), locale)
                for locale in locales
            ]

            if bot:
                self.init_bot(bot)

    @classmethod
    def log_missing(cls):
        """
        Use the bot's logger to log missing translations
        """
        if cls.bot:
            for key, missing in cls.check_missing().items():
                if len(missing) == 0:
                    continue
                cls.bot.logger.error(f"Missing translations `{missing}` for {key}")

    @classmethod
    def check_missing(cls) -> Dict[str, set]:
        """
        Check for missing strings, relative to the default locale

        Returns
        -------
        Dict[str, set]
            A dictionary of missing keys, where the key is the language code
        """
        strings = {
            lang: set(cls._instance._translations[lang].keys())
            for lang in list(cls._instance._translations.keys())
        }
        expected = strings[cls._instance.default]

        missing_lang = {}
        for key, value in strings.items():
            missing = expected - value
            missing_lang[key] = missing

        return missing_lang

    @classmethod
    def set_current_locale(cls, locale: str):
        """
        Set the current locale (for this context)

        Parameters
        ----------
        locale : str
            The locale
        """
        cls._locale.set(locale)

    @classmethod
    def get_current_locale(cls) -> str:
        """
        Get the locale for this context, or the default locale if none is set

        Returns
        -------
        str
            The locale
        """
        return cls._locale.get(cls._instance.default)

    @classmethod
    def init_bot(
        cls, bot: commands.Bot, missing_translation_alert: bool = False
    ) -> None:
        """
        Add pre- and post-invoke hooks on the bot to set the current locale and
        send missing translation alerts after invocation

        Parameters
        ----------
        bot : :obj:`commands.Bot`
            The bot that the hooks will be installed on
        missing_translation_alert : bool, optional
            Whether to send missing translation alerts, by default True
        """
        cls.bot = bot

        async def pre(ctx):
            ctx._user = get_user(ctx.author.id)
            cls.set_current_locale(ctx._user.language)
            missing_translations.set(False)

        async def post(ctx):
            if missing_translations.get(False):
                embed = discord.Embed(
                    title=_("MISSING_TRANSLATION_TITLE"),
                    description=_(
                        "MISSING_TRANSLATION_CONTENT", language=_("LANGUAGE_NAME")
                    ),
                    colour=discord.Colour.red(),
                )
                await ctx.send(embed=embed)

        bot.before_invoke(pre)
        if missing_translation_alert:
            bot.after_invoke(post)

        bot.logger.debug("Before/after invoke hooks for i18n added")

    @classmethod
    def get_string(cls, string: str, try_default: bool = True, **kwargs) -> str:
        """
        Get a string in the locale of the current context

        Parameters
        ----------
        string : str
            The name of the string
        try_default : bool, optional
            Whether to try the default locale if the context locale fails, by
            default True

        Returns
        -------
        str
            The string in the context locale, the string in the default locale
            or the string given as string followed by a dict of the given
            **kwargs
        """
        locale = kwargs.pop("locale", None) or cls.get_current_locale()
        try:
            if "." in string:
                parts = string.split(".")
                current = cls._instance._translations[locale][parts[0]]
                for part in parts[1:]:
                    current = current[part]
            else:
                current = cls._instance._translations[locale][string]
                if current == "":
                    raise KeyError
        except KeyError:
            missing_translations.set(True)
            if locale != cls._instance.default and try_default:
                return cls._instance.get_string(
                    string, try_default, locale=cls._instance.default, **kwargs
                )

            return "`" + string + " " + str(kwargs) + "`"
        else:
            return current.format_map(SafeDict(**kwargs))

    @classmethod
    def get_locale(cls, string: str) -> str:
        """
        Find a locale based on a given string

        Parameters
        ----------
        string : str
            The locale name or code

        Returns
        -------
        str
            The locale code
        """
        for name, key in cls.locales:
            if string in [name, key]:
                return key

        return None


class LazyTranslation:
    """
    A translation that isn't executed until either passed via :func:`str` or
    :func:`repr`

    .. warning::
        The implementation of this function uses `__get__` which is not
        intended for this type of situation. Subsequently, it is not advised
        to use this class unless absolutely necessary.

    .. deprecated::
        Use :func:`I18n.get_string` instead
    """

    def __init__(self, docstring: str):
        self._docstring = docstring

    def __get__(self, instance, owner):
        return _(self._docstring)

    def __str__(self):
        return self.__get__(None, None)

    def __repr__(self):
        return self.__get__(None, None)


def doc(docstring: str):
    """
    A decorator which sets the `__doc__` attribute of the function to an
    instance of :obj:`LazyTranslation` with the given docstring.

    Parameters
    ----------
    docstring : str
        The string to use

    .. warning::
        The implementation of this function uses :obj:`LazyTranslation` which
        is not well written and not advised to be used.
    """

    def decorate(fn):
        fn.__doc__ = LazyTranslation(docstring)
        return fn

    return decorate


_ = I18n.get_string
l_ = LazyTranslation
