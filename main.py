import os
import asyncio
import discord
import json
from discord.ext import commands
import uvicorn
from api_server import app as api_app

config = json.load(open('config.json'))
TOKEN = os.getenv("DISCORD_TOKEN", config.get("token"))
API_HOST = os.getenv("API_HOST", config.get("api_host"))
API_PORT = int(os.getenv("API_PORT", config.get("api_port")))

PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.reactions = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS, help_command=None)

COGS = [
    "cogs.sc",
    "cogs.loans",
    "cogs.blackjack",
    "cogs.betting",
    "cogs.corp",
    "cogs.bureau",
    "cogs.user",
    "cogs.srvl",
    "cogs.directory",
    "cogs.api",
]

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("shiftycoin broker has entered the chatroom.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=config.get("status")))

async def main():
    async with bot:
        for cog in COGS:
            await bot.load_extension(cog)

        api_app.state.bot = bot

        api_config = uvicorn.Config(api_app, host=API_HOST, port=API_PORT, log_level="info")
        api_server = uvicorn.Server(api_config)
        api_server.install_signal_handlers = False  # let discord.py own signal handling

        asyncio.create_task(api_server.serve())
        await bot.start(TOKEN)

asyncio.run(main())
