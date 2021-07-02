# -*- coding: utf-8 -*-
import asyncio
from io import BytesIO
from typing import Optional

import aiohttp
import discord
import sqlalchemy
from discord.webhook import AsyncWebhookAdapter
from discord.webhook import Webhook
from expiring_dict.expiringdict import ExpiringDict

from core.db.database import query
from core.db.database import session
from core.db.models.message import ResultMessage
from core.db.models.node import Node, StatusCode
from core.webhook_ext import edit_webhook_message


def diagnose(node: Node, err: Optional[Exception] = None):
    """
    Set the `status` property of `node` to the correct value based on the
    exception raised

    Parameters
    ----------
    node : Node
        The node to modify
    err : Exception, optional
        The exception raised, by default None
    """
    if err is None:
        return

    if isinstance(err, discord.errors.NotFound):
        node.mark_not_found()
    elif isinstance(err, discord.errors.Forbidden):
        node.mark_not_authorized()
    elif isinstance(err, discord.errors.HTTPException):
        node.mark_http_exception()

class Discord:
    max_retries = 5

    def __init__(
        self, loop, logger, edit_handlers=25, send_handlers=50, save_handlers=10
    ):
        """
        Sets up loop, logger and the specified number of handlers for each
        event.

        Parameters
        ----------
        loop : any
            Asyncio event loop
        logger : Logger
            Logger to use
        edit_handlers : int, optional
            Number of handlers for edits, by default 25
        send_handlers : int, optional
            Number of handlers for sent messages, by default 50
        save_handlers : int, optional
            Number of handlers for saving data to the database, by default 10
        """
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.logger = logger
        self.logger.info("Setting up edit queue and tasks")
        self._edit_queue = asyncio.Queue()
        self._edit_queue_tasks = [
            loop.create_task(self._handle_sensibly(self._edit_queue, self.edit))
            for _ in range(edit_handlers)
        ]
        self.logger.info("Setting up send queue and tasks")
        self._send_queue = asyncio.Queue()
        self._send_queue_tasks = [
            loop.create_task(self._handle_sensibly(self._send_queue, self.send))
            for _ in range(send_handlers)
        ]

        self.logger.info("Setting up save queue and tasks")
        self._save_queue = asyncio.Queue()
        self._save_queue_task = [
            loop.create_task(self._saver()) for _ in range(save_handlers)
        ]

        self.error_expiry = ExpiringDict(60)

        self.logger.info("Ready to accept messages!")

    def _handle_error(self, data, exc):
        self.logger.warning(
            "Disactivated node {} due to NotFound/Forbidden".format(
                data["target"]["id"]
            )
        )
        node = query(Node).get(data["target"]["id"])
        if node is not None:
            diagnose(node, exc)
        session.commit()

    async def _handle_sensibly(  # noqa MC0001
        self, queue: asyncio.Queue, handler: callable
    ):
        """
        Sensibly handle messages from a queue using a given handler

        .. note::
            This handles all errors and queue locking. It also handles retries
            and back off attempts

        .. note::
            This function will mark certain messages as successful, despite
            failing. This is to prevent ratelimiting or non-sensical repeated
            attempts

        Parameters
        ----------
        queue : asyncio.Queue
            The queue to wait for
        handler : callable
            The handler to use
        """
        while True:
            data = await queue.get()
            success = False
            retries = 0
            while not success or retries >= self.max_retries:
                try:
                    retries += 1
                    await handler(data)
                except (discord.Forbidden, discord.NotFound) as exc:
                    self._handle_error(data, exc)
                    success = True
                except discord.HTTPException as exc:
                    if exc.status == 429:
                        resp = await exc.response.json()
                        delay = resp.get("retry_after", 5.0) * 1.1
                        await asyncio.sleep(delay)
                    elif exc.status == 413:
                        # Request entity too large. Do not continue.
                        success = True
                    elif exc.status == 400:
                        # Bad request. Do not continue.
                        success = True
                    else:
                        if data["origin"]["message"] not in self.error_expiry:
                            self.error_expiry[data["origin"]["message"]] = 0
                            self.logger.warning(
                                (
                                    "Node {} returned unknown error {}. "
                                    "This may be one of many similar errors."
                                ).format(data["target"]["id"], exc)
                            )
                            success = True
                except TypeError:
                    success = True
                except Exception:
                    if data["origin"]["message"] not in self.error_expiry:
                        self.error_expiry[data["origin"]["message"]] = 0
                        self.logger.exception("Unknown error handling message...")
                else:
                    success = True

            queue.task_done()

            if not success:
                self.logger.warning(
                    "Exceeded max retries ({}) for message {} to {}".format(
                        self.max_retries,
                        data["origin"]["message"],
                        data["target"]["id"],
                    )
                )

    async def edit(self, data: dict):
        async with aiohttp.ClientSession() as csession:
            webhook = Webhook.from_url(
                data["target"]["url"], adapter=AsyncWebhookAdapter(csession)
            )
            message_id = data["message_id"]

            files = [
                discord.File(
                    BytesIO(file["body"].encode("latin-1")), filename=file["name"]
                )
                for file in data["body"].get("files", [])
            ]
            embeds = [
                discord.Embed.from_dict(d) for d in data["body"].get("embeds", [])
            ]

            await edit_webhook_message(
                webhook=webhook,
                original_id=message_id,
                session=csession,
                content=data["body"]["content"],
                username=data["body"]["username"],
                avatar_url=data["body"]["avatar_url"],
                files=files,
                embeds=embeds,
                wait=True,
                allowed_mentions=discord.AllowedMentions(everyone=False).to_dict(),
            )

    async def send(self, data: dict):
        async with aiohttp.ClientSession() as csession:
            webhook = Webhook.from_url(
                data["target"]["url"], adapter=AsyncWebhookAdapter(csession)
            )
            files = [
                discord.File(
                    BytesIO(file["body"].encode("latin-1")), filename=file["name"]
                )
                for file in data["body"].get("files", [])
            ]
            embeds = [
                discord.Embed.from_dict(d) for d in data["body"].get("embeds", [])
            ]

            result: discord.Message = await webhook.send(
                content=data["body"]["content"],
                username=data["body"]["username"],
                avatar_url=data["body"]["avatar_url"],
                files=files,
                embeds=embeds,
                wait=True,
                allowed_mentions=discord.AllowedMentions(everyone=False),
            )

            self._save_queue.put_nowait(
                (result.id, data["target"]["id"], data["origin"]["message"])
            )

    async def handle_edit(self, data):
        await self._edit_queue.put(data)

    async def handle_send(self, data):
        await self._send_queue.put(data)

    async def _saver(self):
        """
        Listens for messages from save queue and sends to database.

        .. warning::
            This function will rollback any sessions that cause a failure,
            without necessarily trying to continue with that request.
        """
        while True:
            try:
                message_id, node_id, origin_id = await self._save_queue.get()
                message = ResultMessage(
                    message_id=message_id,
                    node_id=node_id,
                    origin_id=origin_id,
                )
                session.add(message)
                await self.loop.run_in_executor(None, session.commit)
            except sqlalchemy.exc.InvalidRequestError:
                self.logger.exception("Error in previous session...performing rollback")
                session.rollback()
            except Exception:
                self.logger.exception("Error storing message")

            self._save_queue.task_done()

    def get_size(self):
        return self._send_queue.qsize()
