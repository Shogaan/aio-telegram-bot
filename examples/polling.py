import asyncio
import os

from aiotelegrambot import Bot, Content, Message
from aiotelegrambot.rules import Contains

bot = Bot()


@bot.trigger_message(Content.TEXT, Contains("hi"))
async def hi(message: Message):
    await message.send_message("Hello!", True)


if __name__ == "__main__":
    bot.run(os.environ["TELEGRAM_BOT_TOKEN"])
