import discord
from discord.ext import commands
import os
import sys
import asyncio
import logging
import groq
from typing import Dict, List

logging.basicConfig(level=logging.INFO)

# Конфигурация Groq
MODEL_NAME = os.getenv("MODEL_NAME", "llama3-70b-8192")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 50))

# Режим тех-работ
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "False").lower() == "true"
ALLOWED_GUILD_ID = int(os.getenv("ALLOWED_GUILD_ID", 0)) if os.getenv("ALLOWED_GUILD_ID") else None


class NSTA(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Хранилище истории диалогов [guild_id: [role: __, content: __]]
        self.conversation_memory: Dict[int, List[Dict[str, str]]] = {}

        # Хранилище последнего пользователя для каждого сообщения в истории
        self.message_authors: Dict[int, Dict[int, int]] = {}  # [guild_id][message_index] = user_id

        self.groq_client = None
        self.setup_commands()

    def setup_commands(self):
        """Регистрация всех slash-команд"""

        @self.tree.command(name='kill', description='Остановить бота')
        async def kill(interaction: discord.Interaction):
            logging.debug(
                f"Команда /kill вызвана пользователем {interaction.user.global_name}, id: {interaction.user.id}")
            if interaction.user.id == 308969326764097547:
                await interaction.response.send_message("Выключаюсь...")
                await self.close()
                exit()
            else:
                await interaction.response.send_message("Не лапай меня, дурак!!")

        @self.tree.command(name='ask', description='Задать вопрос Groq AI')
        async def ask(interaction: discord.Interaction, question: str):
            """Slash-команда /ask <вопрос>"""

            if MAINTENANCE_MODE and ALLOWED_GUILD_ID:
                if not interaction.guild or interaction.guild.id != ALLOWED_GUILD_ID:
                    await interaction.response.send_message(
                        "🔧 Бот находится в режиме технического обслуживания. Доступ ограничен.", ephemeral=True)
                    return

            await interaction.response.defer()

            response = await self.get_groq_response(
                user_message=question,
                guild_id=interaction.guild_id if interaction.guild else 0,
                user_name=interaction.user.global_name,
                user_id=interaction.user.id
            )

            if len(response) > 1900:
                chunks = [response[i:i + 1900] for i in range(0, len(response), 1900)]
                for chunk in chunks:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(response)

        @self.tree.command(name='clear', description='Очистить историю диалога на сервере')
        async def clear(interaction: discord.Interaction):
            """Slash-команда /clear"""

            if MAINTENANCE_MODE and ALLOWED_GUILD_ID:
                if not interaction.guild or interaction.guild.id != ALLOWED_GUILD_ID:
                    await interaction.response.send_message(
                        "🔧 Бот находится в режиме технического обслуживания. Доступ ограничен.", ephemeral=True)
                    return

            logging.debug(
                f"Пользователь {interaction.user.global_name} очистил историю диалога на сервере {interaction.guild_id}")
            self.clear_history(interaction.guild_id if interaction.guild else 0)
            await interaction.response.send_message("🧹 История диалога на этом сервере очищена.", ephemeral=True)

        @self.tree.command(name='model', description='Показать текущую модель Groq')
        async def show_model(interaction: discord.Interaction):
            """Slash-команда /model"""
            embed = discord.Embed(
                title="🤖 Информация о Groq",
                description=f"**Модель:** {MODEL_NAME}\n**История:** {MAX_HISTORY} сообщений\n**Режим ТО:** {'Включен' if MAINTENANCE_MODE else 'Выключен'}",
                color=discord.Color.blue()
            )
            if MAINTENANCE_MODE and ALLOWED_GUILD_ID:
                embed.add_field(name="Разрешенный сервер", value=f"ID: {ALLOWED_GUILD_ID}", inline=False)
            await interaction.response.send_message(embed=embed)

    # ========== Методы работы с памятью ==========

    def get_history(self, guild_id: int) -> List[Dict[str, str]]:
        """Возвращает историю сообщений для сервера"""
        return self.conversation_memory.get(guild_id, [])

    def add_to_history(self, guild_id: int, role: str, content: str, user_id: int = None):
        """Добавляет сообщение в историю сервера"""
        if guild_id not in self.conversation_memory:
            self.conversation_memory[guild_id] = []
            self.message_authors[guild_id] = {}

        message_index = len(self.conversation_memory[guild_id])
        self.conversation_memory[guild_id].append({"role": role, "content": content})

        if user_id:
            self.message_authors[guild_id][message_index] = user_id

        # Ограничиваем длину истории
        max_messages = MAX_HISTORY * 2
        if len(self.conversation_memory[guild_id]) > max_messages:
            # Удаляем старые сообщения и их авторов
            excess = len(self.conversation_memory[guild_id]) - max_messages
            for i in range(excess):
                if i in self.message_authors[guild_id]:
                    del self.message_authors[guild_id][i]

            # Сдвигаем индексы
            new_authors = {}
            for old_idx, user in self.message_authors[guild_id].items():
                new_authors[old_idx - excess] = user
            self.message_authors[guild_id] = new_authors

            self.conversation_memory[guild_id] = self.conversation_memory[guild_id][-max_messages:]

    def clear_history(self, guild_id: int):
        """Очищает историю для сервера"""
        if guild_id in self.conversation_memory:
            del self.conversation_memory[guild_id]
        if guild_id in self.message_authors:
            del self.message_authors[guild_id]

    def format_history_with_users(self, guild_id: int) -> List[Dict[str, str]]:
        """Форматирует историю для отправки в API, добавляя имена пользователей"""
        if guild_id not in self.conversation_memory:
            return []

        formatted = []
        for idx, msg in enumerate(self.conversation_memory[guild_id]):
            if msg["role"] == "user" and idx in self.message_authors.get(guild_id, {}):
                # Здесь мы не меняем содержимое, просто возвращаем как есть
                # Информация о пользователе будет добавлена в system prompt
                formatted.append(msg)
            else:
                formatted.append(msg)

        return formatted

    # ========== Методы работы с Groq ==========

    async def get_groq_response(
            self,
            user_message: str,
            guild_id: int,
            user_name: str,
            user_id: int,
            temperature: float = 0.7,
            max_tokens: int = 1000

    ) -> str:
        """
        Отправляет запрос к Groq API с учётом истории
        """
        if not self.groq_client:
            return "❌ Groq клиент не инициализирован"

        # Получаем историю сервера (чистую, без добавленных имен)
        history = self.get_history(guild_id)

        # Создаем контекст с информацией о текущем пользователе
        system_prompt = os.getenv("SYSTEM_PROMPT",
                                  "Ты полезный AI ассистент в Discord сервере. Отвечай естественно и дружелюбно.")
        system_prompt_with_context = f"""{system_prompt}

Важная информация о пользователях:
- Сейчас с тобой общается {user_name} (ID: {user_id})
- В истории диалога могут быть сообщения от разных пользователей сервера
- Отвечай в 3-4 предложения. Можно и больше
- Иногда называй пользователя по имени, но не так часто
- Отвечай так, как будто общаешься с текущим пользователем, учитывая общую историю разговора"""

        messages = [
            {"role": "system", "content": system_prompt_with_context}
        ]

        # Добавляем историю в неизменном виде (без префиксов с именами)
        messages.extend(history)

        # Добавляем текущее сообщение пользователя
        messages.append({"role": "user", "content": user_message})

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.groq_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=0.95,
                    stream=False
                )
            )

            answer = response.choices[0].message.content

            # Сохраняем в историю чистое сообщение (без имени пользователя)
            self.add_to_history(guild_id, "user", user_message, user_id)
            self.add_to_history(guild_id, "assistant", answer)

            return answer

        except groq.APIConnectionError as e:
            return f"❌ Ошибка подключения к Groq API: {e}"
        except groq.RateLimitError as e:
            return f"⚠️ Превышен лимит запросов к Groq. Попробуйте позже."
        except groq.APIStatusError as e:
            return f"❌ Ошибка API Groq: {e.status_code}"
        except Exception as e:
            return f"❌ Непредвиденная ошибка: {e}"

    # ========== События Discord ==========

    async def on_ready(self):
        """Событие при запуске бота"""
        logging.info(f"✅ Бот {self.user} готов")
        logging.info(f"📊 Groq модель: {MODEL_NAME}")
        logging.info(f"📝 История: {MAX_HISTORY} сообщений на сервер")
        logging.info(f"🔧 Режим тех-работ: {'Включен' if MAINTENANCE_MODE else 'Выключен'}")
        if MAINTENANCE_MODE and ALLOWED_GUILD_ID:
            logging.info(f"📌 Разрешенный сервер ID: {ALLOWED_GUILD_ID}")

        await self.tree.sync()
        logging.info("✅ Slash-команды синхронизированы")

    async def on_message(self, message: discord.Message):
        """Обработка всех сообщений"""
        if message.author == self.user:
            return

        # Проверяем упоминание бота
        if self.user in message.mentions:
            # Проверка режима тех-работ
            if MAINTENANCE_MODE and ALLOWED_GUILD_ID:
                if not message.guild or message.guild.id != ALLOWED_GUILD_ID:
                    await message.reply("🔧 Бот находится в режиме технического обслуживания. Доступ ограничен.")
                    return

            logging.debug(f"Бота упомянули на сервере {message.guild.id if message.guild else 'ЛС'}")
            content = message.content
            for mention in message.mentions:
                content = content.replace(f"<@{mention.id}>", "").strip()

            if content:
                async with message.channel.typing():
                    response = await self.get_groq_response(
                        user_message=content,
                        guild_id=message.guild.id if message.guild else 0,
                        user_name=message.author.global_name,
                        user_id=message.author.id
                    )

                if len(response) > 1900:
                    chunks = [response[i:i + 1900] for i in range(0, len(response), 1900)]
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response)
            else:
                # Если просто пинганули без текста
                if MAINTENANCE_MODE and ALLOWED_GUILD_ID:
                    if not message.guild or message.guild.id != ALLOWED_GUILD_ID:
                        await message.reply("🔧 Бот находится в режиме технического обслуживания. Доступ ограничен.")
                else:
                    await message.reply(
                        "👋 Привет! Что хочешь спросить? Используй `/ask` или просто напиши вопрос с моим упоминанием.")

        await self.process_commands(message)

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        pass


# ========== Запуск бота ==========

if __name__ == '__main__':
    logging.debug("Получаю токены из переменных окружения")
    token = os.getenv('DISCORD_TOKEN')
    groq_api_key = os.getenv('GROQ_API_KEY')

    if not token:
        logging.critical("DISCORD_TOKEN не установлен в переменных окружения!")
        sys.exit(1)
    if not groq_api_key:
        logging.critical("GROQ_API_KEY не установлен в переменных окружения!")
        sys.exit(1)

    logging.debug("Токены успешно получены")

    intents = discord.Intents.default()
    intents.messages, intents.members, intents.presences, intents.message_content = True, True, True, True
    logging.debug("Интенты настроены")

    bot = NSTA(command_prefix='!', intents=intents)
    groq_client = groq.Groq(api_key=groq_api_key)
    bot.groq_client = groq_client

    logging.debug("Бот создан, запускаю")
    bot.run(token, log_level=logging.INFO)