# -*- coding: utf-8 -*-
import asyncio
import json
import re
import typing as t
from dataclasses import dataclass

from discord.ext import commands
from discord.message import MessageReference
from discord.utils import escape_mentions
from discord.utils import get

from ..db import session
from ..db.models import Node
from ..db.models import OriginMessage
from ..db.models import Stream
from ..db.utils import get_user
from ..i18n.i18n import _
from .rmqclient import RabbitMQClient
from core.db.database import query
from core.db.models.message import ResultMessage
from core.db.models.user import User


@dataclass
class Message:
    message_body: dict
    target_url: str
    target_id: int
    type_: str = "discord"
    origin_id: int = None
    original_id: int = None
    message_id: int = None
    reference: MessageReference = None


class Client(RabbitMQClient):
    bot = None
    _default_username = "Thibault"
    _default_avatar_url = "https://i.discord.fr/kdE.png"
    _default_user = 705422266649018398

    def __init__(self, rabbitmq_url, rabbitmq_routing, logger=None, bot=None):
        super().__init__(rabbitmq_url, rabbitmq_routing, logger=logger)
        if bot:
            self.init_bot(bot)

    def init_bot(self, bot: commands.Bot):
        self.bot = bot

    def _message_reply_content(self, tq: t.Union[OriginMessage, ResultMessage]) -> str:
        """
        Get the appropriate content for the reply header, whether it be a
        text message, attachment or other.

        Parameters
        ----------
        tq : t.Union[OriginMessage, ResultMessage]
            The target query

        Returns
        -------
        str
            Reply header
        """
        if tq:
            if isinstance(tq, OriginMessage):
                content = tq.content
            else:
                content = tq.origin.content

            if content == "":
                content = _("CLICK_TO_SEE")
        else:
            content = None

        content = (
            content[:30] + ("..." if len(content) > 30 else "")
            if content
            else _("UNKNOWN_MESSAGE")
        )

        return content

    async def formatted_stasis(self, message_body: dict) -> callable:
        """
        Handle both reference stasis (for replies) and mention stasis

        Parameters
        ----------
        message_body : dict
            Raw message data

        Returns
        -------
        callable
            The wrapper
        """
        referenced = await self._get_reference_stasis(
            message_body.pop("reference", None)
        )
        mentioned = await self._get_mention_stasis(message_body["content"])

        async def _format(target: Node):
            return await mentioned(await referenced(message_body, target), target)

        return _format

    async def _get_mention_stasis(self, content: str) -> callable:
        """
        Create a function that takes the raw message data and target node to
        correctly format mentions.

        .. seealso::
            You should use `formatted_statis` to handle both these correctly.

        Parameters
        ----------
        content : str
            The message content

        Returns
        -------
        callable
            The function
        """
        mentions = []
        for (match, default, snowflake, target_node_id) in re.findall(
            r"(<(`.+?#\d{4}`):(\d+?)=(\d+?)>)", content
        ):
            mentions.append((match, default, snowflake, int(target_node_id)))

        if len(mentions) == 0:

            async def _ret(message_body: dict, _: Node):
                return message_body

            return _ret

        async def _format_mentions(message_body: dict, target: Node):
            this_body = message_body.copy()
            for (match, default, snowflake, target_node_id) in mentions:
                if target.id == target_node_id:
                    this_body["content"] = this_body["content"].replace(
                        match, "<@{}>".format(snowflake), 1
                    )
                else:
                    this_body["content"] = this_body["content"].replace(
                        match, default, 1
                    )
            return this_body

        return _format_mentions

    async def _get_reference_stasis(self, reference: MessageReference) -> callable:
        """
        Create a function that takes the raw message data and target node to
        correctly targeted message replies.

        .. seealso::
            You should use `formatted_statis` to handle both these correctly.

        Parameters
        ----------
        reference : MessageReference
            The message reference

        Returns
        -------
        callable
            The function
        """
        async def _ret(message_body: dict, _: Node):
            return message_body

        if reference is None:
            return _ret

        quoted_message = await self.bot.loop.run_in_executor(
            None,
            (
                query(OriginMessage)
                .filter(
                    (OriginMessage.message_id == reference.message_id)
                    | (
                        OriginMessage.result_messages.any(
                            ResultMessage.message_id == reference.message_id
                        )
                    )
                )
                .first
            ),
        )

        if quoted_message is None:
            return _ret

        async def _add_quotation(message_body: dict, target: Node):
            if quoted_message.node == target:
                # tq is target quoted message
                tq = quoted_message
            else:
                tq = get(quoted_message.result_messages, node=target)
            content = self._message_reply_content(tq)
            user = self.bot.get_user(
                quoted_message.user.discord_id
            ) or await self.bot.fetch_user(quoted_message.user.discord_id)

            this_body = message_body.copy()
            this_body["content"] = (
                _(
                    "REPLYING_TO",
                    username=f"@{user}",
                    link=f"https://discord.com/channels/{tq.node.guild.discord_id}"
                    f"/{tq.node.channel_id}/{tq.message_id}",
                    content=escape_mentions(content),
                    locale=target.stream.language,
                )
                + "\n"
            ) + this_body["content"]
            return this_body

        return _add_quotation

    def _build_body(
        self,
        message: Message,
    ) -> dict:
        """
        Build a body to be sent via RabbitMQ

        Parameters
        ----------
        message : Message
            The message to create the body for

        Returns
        -------
        dict
            The body
        """
        body = {
            "edit": message.message_id is not None,
            "message_id": message.message_id,
            "type": message.type_,
            "target": {
                "id": message.target_id,
                "url": message.target_url,
            },
            "body": message.message_body,
            "origin": {"node": message.origin_id, "message": message.original_id},
        }

        return body

    async def _send_one(
        self,
        message: Message,
    ):
        """
        Send a message to an individual target. Shouldn't be used by anything
        other than :func:`Client.send` or :func:`Client.update`

        Parameters
        ----------
        message : Message
            The message to send on RabbitMQ
        """
        body = json.dumps(self._build_body(message))
        await self.send_raw(body)

    def _get_target_urls(self, target: t.Union[Node, Stream]):
        targets = []
        if isinstance(target, Node):
            targets.append(target.webhook_url())
        else:
            targets.extend(node.webhook_url() for node in target.nodes)

        return targets

    async def _prepare_message_body_reply(self, message_body: dict, target: Node):
        ref = message_body.pop("reference", None)
        if ref is not None:
            message_body["content"] = (
                await self._reply_pretext(ref, target) + message_body["content"]
            )

    async def update(
        self,
        message_body: dict,
        origin: OriginMessage,
        target: t.Union[Node, Stream],
    ):
        """
        Updates a pre-existing message via RabbitMQ

        Parameters
        ----------
        message_body : dict
            The body created by :func:`Client._build_body`
        origin : OriginMessage
            The original message
        target : Node or Stream
            The target for the update

        Raises
        ------
        TypeError
            ``target`` is neither a Node or Stream
        """
        if not isinstance(target, (Node, Stream)):
            raise TypeError("Target is not of type Node or Stream")

        origin_id = None
        original_id = None
        if origin:
            origin_id = origin.node_id
            original_id = origin.id

        targets = self._get_target_urls(target)
        tasks = []
        loop = asyncio.get_event_loop()

        formatted = await self.formatted_stasis(message_body)
        for result_message in origin.result_messages:
            if result_message.node.disabled:
                continue
            target_url = result_message.node.webhook_url()
            if target_url in targets:
                task = loop.create_task(
                    self._send_one(
                        Message(
                            message_body=await formatted(result_message.node),
                            target_url=target_url,
                            target_id=result_message.node.id,
                            origin_id=origin_id,
                            original_id=original_id,
                            message_id=result_message.message_id,
                        ),
                    )
                )
                tasks.append(task)

        await asyncio.gather(*tasks)

    async def send(
        self,
        message_body: dict,
        origin: OriginMessage = None,
        target: t.Union[Node, Stream] = None,
        exclude_origin: bool = True,
    ):  # TODO: laundmo # pylint: disable=too-many-branches
        """
        Send a message via RabbitMQ

        Parameters
        ----------
        message_body : dict
            The body created by :func:`Client._build_body`
        origin : OriginMessage, optional
            The original message, by default None
        target : Node or Stream, optional
            The target to send to, by default None
        exclude_origin : bool, optional
            Whether to not send to the node of ``origin`` if it exists, by
            default True

        Raises
        ------
        TypeError
            ``target`` is neither a Node or Stream
        """
        if not isinstance(target, (Node, Stream)):
            raise TypeError("Target is not of type Node or Stream")

        origin_id = None
        original_id = None
        if origin:
            origin_id = origin.node_id
            original_id = origin.id

        targets = []
        if isinstance(target, Node):
            targets.append(target)
        else:
            targets.extend(
                node
                for node in target.nodes
                if not exclude_origin or node != origin.node
            )

        tasks = []
        loop = asyncio.get_event_loop()
        formatted = await self.formatted_stasis(message_body)
        for targ in targets:
            if targ.disabled:
                continue

            task = loop.create_task(
                self._send_one(
                    Message(
                        message_body=await formatted(targ),
                        target_url=targ.webhook_url(),
                        target_id=targ.id,
                        origin_id=origin_id,
                        original_id=original_id,
                    )
                )
            )
            tasks.append(task)
        await asyncio.gather(*tasks)

    async def send_art(
        self,
        content: str,
        target: t.Union[Node, Stream],
        user: t.Optional[User] = None,
        **fields,
    ):
        """
        Send a message via RabbitMQ artificially

        Parameters
        ----------
        content : str
            The content of the message
        target : Node | Stream
            The target of the message
        user : User, optional
            The user to send this message as, by default None.
            If no user is specified, this is sent as ``Client._default_user``
            but displayed with the username ``Client._default_username``.
        """
        username = fields.pop("username", self._default_username)
        avatar_url = fields.pop("avatar_url", self._default_avatar_url)

        original = fields.pop("original", None)
        if original is None:
            original = OriginMessage(
                user=user or get_user(self._default_user), message_id=0, content=content
            )
            session.add(original)
            session.commit()

        body = {
            "content": content,
            "username": username,
            "avatar_url": avatar_url,
            **fields,
        }

        await self.send(body, target=target, origin=original, exclude_origin=False)
