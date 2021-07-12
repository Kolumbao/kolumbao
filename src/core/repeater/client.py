# -*- coding: utf-8 -*-
import asyncio
import json
import re
import typing as t
from dataclasses import dataclass
import discord

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

    async def all_factories(self, message_body: dict) -> callable:
        """
        Handle both reference factory (for replies) and mention factory

        Parameters
        ----------
        message_body : dict
            Raw message data

        Returns
        -------
        callable
            The wrapper
        """
        referenced = await self._get_reference_factory(
            message_body.pop("reference", None)
        )
        mentioned = await self._get_mention_factory(message_body["content"])

        async def _format(target: Node):
            return await mentioned(await referenced(message_body, target), target)

        return _format

    async def _get_mention_factory(self, content: str) -> callable:
        """
        Create a function that takes the raw message data and target node to
        correctly format mentions.

        .. seealso::
            You should use `all_factories` to handle both these correctly.

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

    async def _get_reference_factory(self, reference: MessageReference) -> callable:
        """
        Create a function that takes the raw message data and target node to
        correctly targeted message replies.

        .. seealso::
            You should use `all_factories` to handle both these correctly.

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

        # If there is no message reference
        if reference is None:
            return _ret

        # Find the message quoted
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

        # If the quoted message wasn't found...
        if quoted_message is None:
            return _ret

        # Add the quotation pointing to the target node
        async def _add_quotation(message_body: dict, target: Node):
            if quoted_message.node == target:
                # tq is target quoted message
                tq = quoted_message
            else:
                tq = get(quoted_message.result_messages, node=target)

            user = quoted_message.user.discord or await self.bot.fetch_user(
                quoted_message.user.discord_id
            )
            
            if tq is None:
                # Not found locally
                return message_body
            else:
                # Show reply tooltip
                content = self._message_reply_content(tq)

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

    def _get_target_urls(self, target: t.Union[Node, Stream]) -> t.List[str]:
        """
        Get all URLs for the target

        Parameters
        ----------
        target : t.Union[Node, Stream]
            The target, either a node or a stream

        Returns
        -------
        List[str]
            List of URLs
        """
        targets = []
        if isinstance(target, Node):
            # Get single node target
            targets.append(target.webhook_url())
        else:
            # Get targets for all nodes in this stream
            targets.extend(node.webhook_url() for node in target.nodes)

        return targets

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

        origin_id = None  # ID of origin
        original_id = None  # Original message ID
        if origin:
            origin_id = origin.node_id
            original_id = origin.id

        # Get all target, regardless of Node/Stream
        targets = self._get_target_urls(target)

        # Create tasks and set up event loops
        tasks = []
        loop = asyncio.get_event_loop()

        # Get the reference and mentions factories together
        all_factories = await self.all_factories(message_body)
        for result_message in origin.result_messages:
            if result_message.node.disabled:
                continue

            # If the node isn't disabled, and the target node still exists as
            # a target on the network
            target_url = result_message.node.webhook_url()
            if target_url in targets:
                task = loop.create_task(
                    self._send_one(
                        Message(
                            message_body=await all_factories(result_message.node),
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
    ):  # pylint: disable=too-many-branches
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

        origin_id = None  # ID of origin
        original_id = None  # Original message ID
        if origin:
            origin_id = origin.node_id
            original_id = origin.id

        # Get all target, regardless of Node/Stream
        # This can't be done with _get_target_urls as we must know whether the
        # node is disabled when selecting targets.
        targets = []
        if isinstance(target, Node):
            targets.append(target)
        else:
            targets.extend(
                node
                for node in target.nodes
                if not exclude_origin or node != origin.node
            )

        # Create tasks and set up event loops
        tasks = []
        loop = asyncio.get_event_loop()

        # Create the factory
        all_factories = await self.all_factories(message_body)
        for targ in targets:
            if targ.disabled:
                continue

            # Create the task
            task = loop.create_task(
                self._send_one(
                    Message(
                        message_body=await all_factories(targ),
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
        **fields : dict
            Extra fields that should be considered, such as:
             - username: The username to use, otherwise ``Client._default_username``
             - avatar_url: The avatar URL to use, otherwise ``Client._default_avatar_url``
             - original: The original message in the database, otherwise one is created
        """
        # Get username and avatar URL
        username = fields.pop("username", self._default_username)
        avatar_url = fields.pop("avatar_url", self._default_avatar_url)
         
        # Whether to make an 'original' message or if one exists
        original = fields.pop("original", None)
        if original is None:
            original = OriginMessage(
                user=user or User.create(discord.Object(self._default_user)),
                message_id=0,
                content=content,
                stream_id=target.stream_id if isinstance(target, Node) else target.id
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
