# -*- coding: utf-8 -*-
import discord


@classmethod
def invisible(cls: discord.Colour):
    """A factory method that returns a Colour with a value of 0xff6961."""
    return cls(0x2F3136)  # noqa


discord.Colour.invisible = invisible


def raw_resp(
    ctx,
    text: str,
    title: str = None,
    badge: str = None,
    colour: discord.Colour = discord.Colour.invisible(),
    fields: list = None,
):
    """
    Create an embed for a response

    Parameters
    ----------
    ctx : commands.Context
        Command context
    text : str
        Main text for the response that will always be shown
    title : str, optional
        The embed title, by default None
    badge : str, optional
        Badge to use at the start, by default None
    colour : discord.Colour, optional
        The embed colour, by default discord.Colour.invisible()
    fields : list, optional
        Fields for the embed, a list of (name, value), by default None

    Returns
    -------
    discord.Embed
        The embed
    """
    embed = discord.Embed(title=title or discord.Embed.Empty, colour=colour)

    if badge is None:
        if hasattr(ctx, "cog") and ctx.cog is not None:
            if hasattr(ctx.cog, "__badge__"):
                badge = ctx.cog.__badge__

    if badge is None:
        badge = ""

    if text:
        embed.description = badge + " " + text

    if fields:
        for name, value in fields:
            embed.add_field(name=name, value=value)

    return embed


async def resp(  # pylint: disable=too-many-arguments
    ctx,
    text: str,
    title: str = None,
    badge: str = None,
    colour: discord.Colour = discord.Colour.invisible(),
    fields: list = None,
    supplementary_text: str = None,
):
    """
    Try to send a reponse in an embed, and if it fails due to permissions, use
    text instead.

    Parameters
    ----------
    ctx : commands.Context
        Command context
    text : str
        Main text for the response that will always be shown
    title : str, optional
        The embed title, by default None
    badge : str, optional
        Badge to use at the start, by default None
    colour : discord.Colour, optional
        The embed colour, by default discord.Colour.invisible()
    fields : list, optional
        Fields for the embed, a list of (name, value), by default None
    supplementary_text : str, optional
        Text to show if an embed is used in the normal text, by default None
    """
    try:
        await ctx.send(
            supplementary_text, embed=raw_resp(ctx, text, title, badge, colour, fields)
        )
    except discord.Forbidden:
        await ctx.send(f"{badge if badge else ''} {text}")


async def bad(ctx, *args, **kwargs):
    """
    A 'bad' response. Automatically finds the ``__badge_fail__`` attribute
    of the cog in question.

    Parameters
    ----------
    ctx : commands.Context
        The context
    """
    colour = kwargs.pop("colour", discord.Colour.red())
    badge = None
    if hasattr(ctx, "cog") and ctx.cog is not None:
        if hasattr(ctx.cog, "__badge_fail__"):
            badge = ctx.cog.__badge_fail__
    badge = kwargs.pop("badge", badge)
    await resp(ctx, *args, colour=colour, badge=badge, **kwargs)


async def good(ctx, *args, **kwargs):
    """
    A 'good' response. Automatically finds the ``__badge_success__`` attribute
    of the cog in question.

    Parameters
    ----------
    ctx : commands.Context
        The context
    """
    colour = kwargs.pop("colour", discord.Colour.green())
    badge = None
    if hasattr(ctx, "cog") and ctx.cog is not None:
        if hasattr(ctx.cog, "__badge_success__"):
            badge = ctx.cog.__badge_success__
    badge = kwargs.pop("badge", badge)
    await resp(ctx, *args, colour=colour, badge=badge, **kwargs)
