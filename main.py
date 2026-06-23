import os
import asyncio
import discord
import json
from discord.ext import commands

config = json.load(open('config.json'))
TOKEN = os.getenv("DISCORD_TOKEN", config.get("token"))
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
        await bot.start(TOKEN)

asyncio.run(main())
