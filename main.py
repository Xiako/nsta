from threading import Thread
import discord
from discord.ext import commands
import json
import requests
import random
import os
import asyncio
import logging

class NSTA(commands.Bot):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        @self.tree.command(name='kill')
        async def kill(smth):
            exit()

        @self.event
        async def on_ready():
            print("Bot is ready")
            await self.tree.sync()

        @self.event
        async def on_voice_state_update(member, before, after):
            pass

        @self.event
        async def on_message(msg):
            pass

bot = NSTA(command_prefix='!', intents=discord.Intents.all())
token = os.getenv('DISCORD_TOKEN')
if not token:
    raise ValueError('DISCORD_TOKEN not set in environment variables')

bot.run(token, log_level=logging.WARNING)