# -*- coding: utf-8 -*-
import logging

import aio_pika
import aiormq


class RabbitMQClient:
    _connection = None
    _channel = None
    _exchange = None
    _url = None
    _routing_key = None
    _logger = logging
    _listeners_registered = None

    def __init__(
        self, rabbitmq_url: str, rabbitmq_routing: str, logger: logging.Logger = None
    ):
        self._url = rabbitmq_url
        self._routing_key = rabbitmq_routing
        self._listeners_registered = []
        if logger:
            self.set_logger(logger)

    def set_logger(self, logger: logging.Logger):
        """
        Set the logger for this client

        Parameters
        ----------
        logger : logging.Logger
            The logger
        """
        self._logger = logger

    async def connect(self) -> aio_pika.RobustConnection:
        """
        Connect to the RabbitMQ exchange.

        Returns
        -------
        aio_pika.RobustConnection
            The robust connection created by `aio_pika`

        Raises
        ------
        Exception
            Any exception raised by `aio_pika.connect_robust` or
            `aio_pika.RobustConnection`.channel
        """
        if self._connection is None:
            self._logger.debug("Attempting to initialize robust connection to RabbitMQ")
            try:
                self._connection = await aio_pika.connect_robust(self._url)
                self._channel = await self._connection.channel()
                self._exchange = self._channel.default_exchange
            except Exception as exc:
                self._logger.critical("Failed to connect to RabbitMQ, error following")
                self._logger.exception("Error connecting to RabbitMQ")
                raise exc
            else:
                self._logger.info("Successfully connected to RabbitMQ")

        return self._connection

    async def reconnect(self) -> aio_pika.RobustConnection:
        """
        Reconnect to the exchange if an error occurs. Also reconfigures
        listeners.

        Returns
        -------
        aio_pika.RobustConnection
            The connection created
        """
        self._logger.debug("Reconnect initiated. Terminating old connection and recreating")
        if self._connection:
            await self._connection.close()
            self._connection = None

        await self.connect()
        
        # Re-register listeners
        self._logger.debug("Re-registering old listeners")
        for listener in self._listeners_registered:
            await self.listen(**listener)

        self._logger.info("Reconnect complete")

    async def send_raw(self, content: str, target: str = None):
        """
        Send a message with this client. `RabbitMQClient.connect` must have
        already been called!

        Parameters
        ----------
        content : str
            The content of the message, will be encoded
        target : str, optional
            The routing key, by default None
        """
        target = target or self._routing_key
        body = content.encode()
        await self.__exchange_publish(aio_pika.Message(body=body), routing_key=target)

    async def __exchange_publish(self, *args, retry_times: int = 5, **kwargs) -> None:
        """
        Attempt to publish to the exchange, and reconnect when there is a
        channel invalid state error (usually after a channel being closed
        due to an internal error).

        Parameters
        ----------
        *args
            Args to pass to ``self._exchange.publish``
        retry_times : int, optional
            The number of times to retry, by default 5
        **kwargs
            Kwargs to pass to ``self._exchange.publish``
        """
        success = False
        tries = 0
        while not success:
            tries += 1
            try:
                await self._exchange.publish(*args, **kwargs)
            except aiormq.exceptions.ChannelInvalidStateError:
                self._logger.critical(
                    f"Channel invalid state error... reconnecting ({tries}/{retry_times})"
                )
                await self.reconnect()
            else:
                success = True

    async def listen(
        self,
        func: callable,
        target: str = None,
        prefetch_count: int = 100,
        auto_delete: bool = True,
        register_listener: bool = True,
    ):
        """
        Listen to messages from RabbitMQ using a function

        Parameters
        ----------
        func : callable
            The function to call when a message is received
        target : str, optional
            The routing key, by default None
        prefetch_count : int, optional
            How many messages to fetch in advance, by default 100
        auto_delete : bool, optional
            Whether to delete messages once finished with them, by default True
        register_listener : bool, optional
            Whether to save the register for reconnect, by default True
        """
        await self._channel.set_qos(prefetch_count=prefetch_count)

        target = target or self._routing_key
        queue = await self._channel.declare_queue(target, auto_delete=auto_delete)

        await queue.consume(func)

        if register_listener:
            # Add the kwargs for the listen function
            self._listeners_registered.append(
                dict(
                    func=func,
                    target=target,
                    prefetch_count=prefetch_count,
                    auto_delete=auto_delete,
                    register_listener=False,
                )
            )
