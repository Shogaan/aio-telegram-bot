import asyncio
import logging
from typing import Callable, Union

import aiohttp
import aiojobs

from aiotelegrambot.client import Client
from aiotelegrambot.errors import BotError, TelegramApiError
from aiotelegrambot.handler import Handlers
from aiotelegrambot.message import Message
from aiotelegrambot.middleware import Middlewares
from aiotelegrambot.rules import Command, Rule
from aiotelegrambot.types import Chat, Content, Incoming, recognize_type

logger = logging.getLogger(__name__)


class BotBase:
    def __init__(self, handlers: Handlers = None):
        self.handlers = handlers or Handlers()
        self.middlewares = Middlewares()
        self._scheduler = None
        self._closed = True
        self._update_id = 0
        self.ctx = {}

    async def initialize(self, *, webhook: bool = False, interval: float = 0.1, **scheduler_options):
        if self._closed is False:
            return

        if not self.handlers:
            raise BotError("Can't initialize with no one handler")

        self._closed = False
        self._scheduler = await aiojobs.create_scheduler(**scheduler_options)
        if webhook is False:
            await self._scheduler.spawn(self._get_updates(interval))

    async def close(self):
        if self._closed:
            return

        self._closed = True

        for job in self._scheduler:
            await job.wait()

        await self._scheduler.close()
        self._scheduler = None

        self._update_id = 0

    def add_handler(self, handler: Callable, *args, **kwargs):
        self.handlers.add(*args, **kwargs)(handler)

    async def _process_updates(self, data: Union[None, dict]):
        if data:
            for raw in data["result"]:
                await self.process_update(raw)
                self._update_id = max(raw["update_id"], self._update_id)
            self._update_id += 1 if data["result"] else 0


class Bot(BotBase):
    def __init__(self, *, loop=None):
        super().__init__()
        self.loop = asyncio.get_event_loop() if loop is None else loop
        self.client = None
        self.webhook = None

    def command(self):
        """
        Decorator for creating bot's command.

        ```
        bot = Bot()

        @bot.command()
        def name_of_command(message: Message):
            # useful stuff here
            pass
        ```
        """

        def decorator(func):
            return self.add_handler(func,
                                    content_type=Content.COMMAND,
                                    rule=Command())
        return decorator

    def trigger_message(self,
                        message_type: Union[Chat, Incoming, Content] = None,
                        rule: Rule = None):
        """
        Decorator for creating a handler for any type of message,
        specifized in `message_type`.
        """

        if not message_type:
            raise BotError("message_type Union[Chat, Incoming, Content] must be specifized")

        def decorator(func):
            return self.add_handler(func,
                                    content_type=message_type,
                                    rule=rule)
        return decorator

    async def process_update(self, data: dict):
        if self._closed is True:
            raise RuntimeError("The bot isn't initialized")

        chat_type, incoming, content_type = recognize_type(data)
        handler = self.handlers.get(chat_type, incoming, content_type, data)
        await self._scheduler.spawn(
            self.middlewares(Message(self.client, data, self.ctx, chat_type, incoming, content_type), handler)
        )

    def run(self, token, webhook = False):
        self.client = Client(token)
        self.webhook = webhook

        try:
            self.loop.run_until_complete(self._start())

        except KeyboardInterrupt:
            self.loop.run_until_complete(self.close())
            self.loop.run_until_complete(self.client.close())

        finally:
            self.loop.close()

    async def _get_updates(self, interval: float):
        while self._closed is False:
            try:
                data = await self.client.get_updates(self._update_id)
                await self._process_updates(data)
                await asyncio.sleep(interval)
            except TelegramApiError as e:
                self.client.process_error(str(e), e.response, e.data, False)
                if e.response.status >= 500:
                    await asyncio.sleep(30)
                else:
                    await asyncio.sleep(10)
            except asyncio.TimeoutError as e:
                logger.exception(str(e))
            except aiohttp.ClientError as e:
                logger.exception(str(e))
                await asyncio.sleep(10)

    async def _start(self):
        await self.initialize(webhook=self.webhook)
        while True:
            await asyncio.sleep(100)

