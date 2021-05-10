# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from os import getenv

import aio_pika
from dotenv import load_dotenv

from core.db import Database
from core.logs.log import create_general_logger
from core.repeater.rmqclient import RabbitMQClient
from repeater.handlers import Discord

load_dotenv()

database = Database(getenv("DB_URI"))
client = RabbitMQClient(getenv("RABBITMQ_URL"), "default")
logger = create_general_logger("repeater", level=logging.INFO)
loop = asyncio.get_event_loop()


async def main():
    logger.debug("Connecting to RabbitMQ...")
    await client.connect()
    await client.listen(listen)

    logger.info("Listening to RabbitMQ...")
    while True:
        await asyncio.sleep(1)


HANDLERS = {"discord": Discord(loop, logger)}


async def listen(message: aio_pika.IncomingMessage):  # noqa: MC0001
    async with message.process():
        # NOTE: Types are stored with messages, as the original plan was to
        # have handlers across several platforms and to spread Kolumbao.
        # The types are still necessary, for forwards compatibility.
        data = json.loads(message.body)
        if data["type"] not in HANDLERS:
            raise ValueError("no known type {}".format(data["type"]))

        handler = HANDLERS[data["type"]]
        if data.get("edit", False):
            await handler.handle_edit(data)
        else:
            await handler.handle_send(data)


if __name__ == "__main__":
    loop.run_until_complete(main())
