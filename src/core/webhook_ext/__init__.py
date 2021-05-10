# -*- coding: utf-8 -*-
import aiohttp
import discord
from aiohttp.client import ClientSession
from discord.http import Route


async def edit_webhook_message(
    webhook: discord.Webhook, original_id: int, session: ClientSession, **fields
):
    """
    Use a ``PATCH`` request to update a webhook message

    Parameters
    ----------
    webhook : discord.Webhook
        The webhook that this message belongs to
    original_id : int
        The ID of the original message on Discord
    session : ClientSession
        The session to use
    """
    r = Route(
        "PATCH",
        "/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}",
        webhook_id=webhook.id,
        webhook_token=webhook.token,
        message_id=original_id,
    )
    res = await session.request(r.method, r.url, json=fields)
    try:
        res.raise_for_status()
    except aiohttp.client_exceptions.ClientResponseError as exc:
        if exc.status == 429:
            raise discord.HTTPException(res, "Ratelimit exceeded")
        raise exc
