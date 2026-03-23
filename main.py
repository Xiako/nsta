import discord
from discord.ext import commands
import os
import asyncio
import logging
import groq
from datetime import datetime, timedelta
from typing import Dict, List

# Конфигурация Groq
MODEL_NAME = os.getenv("MODEL_NAME")  # или "mixtral-8x7b-32768", "llama3-8b-8192"
MAX_HISTORY = int(os.getenv("MAX_HISTORY"))  # количество хранимых сообщений на диалог


class NSTA(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Хранилище истории диалогов [channel_id: [role: __, contentL __]
        self.conversation_memory: Dict[int, List[Dict[str, str]]] = {}

        # Инициализация Groq клиента (будет установлен после запуска)
        self.groq_client = None

        # Регистрация команд
        self.setup_commands()

    def setup_commands(self):
        """Регистрация всех slash-команд"""

        @self.tree.command(name='kill', description='Остановить бота')
        async def kill(interaction: discord.Interaction):
            await interaction.response.send_message("Выключаюсь...")
            await self.close()
            exit()

        @self.tree.command(name='ask', description='Задать вопрос Groq AI')
        async def ask(interaction: discord.Interaction, question: str):
            """Slash-команда /ask <вопрос>"""
            await interaction.response.defer()  # показываем "бот думает"

            response = await self.get_groq_response(
                user_message=question,
                channel_id=interaction.channel_id,
                user_id=interaction.user.id,
                user_name = interaction.user.global_name
            )

            # Если ответ слишком длинный, разбиваем
            if len(response) > 1900:
                chunks = [response[i:i + 1900] for i in range(0, len(response), 1900)]
                for chunk in chunks:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(response)

        @self.tree.command(name='clear', description='Очистить историю диалога')
        async def clear(interaction: discord.Interaction):
            """Slash-команда /clear"""
            self.clear_history(interaction.channel_id, interaction.user.id)
            await interaction.response.send_message("🧹 История нашего диалога очищена.", ephemeral=True)

        @self.tree.command(name='model', description='Показать текущую модель Groq')
        async def show_model(interaction: discord.Interaction):
            """Slash-команда /model"""
            embed = discord.Embed(
                title="🤖 Информация о Groq",
                description=f"**Модель:** {MODEL_NAME}\n**История:** {MAX_HISTORY} сообщений",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)

    # ========== Методы работы с памятью ==========

    def get_history_key(self, channel_id: int, user_id: int) -> int:
        """Возвращает ключ для хранения истории (отдельно для каждого пользователя в канале)"""
        return hash(f"{channel_id}_{user_id}")

    def get_history(self, channel_id: int, user_id: int) -> List[Dict[str, str]]:
        """Возвращает историю сообщений для пользователя"""
        key = self.get_history_key(channel_id, user_id)
        return self.conversation_memory.get(key, [])

    def add_to_history(self, channel_id: int, user_id: int, role: str, content: str):
        """Добавляет сообщение в историю"""
        key = self.get_history_key(channel_id, user_id)

        if key not in self.conversation_memory:
            self.conversation_memory[key] = []

        self.conversation_memory[key].append({"role": role, "content": content})

        # Ограничиваем длину истории (MAX_HISTORY сообщений, но user+assistant)
        max_messages = MAX_HISTORY * 2
        if len(self.conversation_memory[key]) > max_messages:
            self.conversation_memory[key] = self.conversation_memory[key][-max_messages:]

    def clear_history(self, channel_id: int, user_id: int):
        """Очищает историю для пользователя"""
        key = self.get_history_key(channel_id, user_id)
        if key in self.conversation_memory:
            del self.conversation_memory[key]

    # ========== Методы работы с Groq ==========

    async def get_groq_response(
            self,
            user_message: str,
            channel_id: int,
            user_id: int,
            user_name: str,
            temperature: float = 0.7,
            max_tokens: int = 500

    ) -> str:
        """
        Отправляет запрос к Groq API с учётом истории
        """
        if not self.groq_client:
            return "❌ Groq клиент не инициализирован"

        # Получаем историю
        history = self.get_history(channel_id, user_id)

        # Формируем сообщения для Groq
        messages = [
            {"role": "system", "content": os.getenv("SYSTEM_PROMPT")}
        ]
        messages.extend(history)
        user_message = (user_message +
        f"""
        Контекст для нейросети: Пользователя зовут: {user_name}
        """)
        messages.append({"role": "user", "content": user_message})

        try:
            # Асинхронный вызов (запускаем синхронный метод в отдельном потоке)
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

            # Сохраняем в историю
            self.add_to_history(channel_id, user_id, "user", user_message)
            self.add_to_history(channel_id, user_id, "assistant", answer)

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
        print(f"✅ Бот {self.user} готов")
        print(f"📊 Groq модель: {MODEL_NAME}")
        print(f"📝 История: {MAX_HISTORY} сообщений")

        # Синхронизация slash-команд
        await self.tree.sync()
        print("✅ Slash-команды синхронизированы")

    async def on_message(self, message: discord.Message):
        """Обработка всех сообщений"""
        # Игнорируем сообщения от самого бота
        if message.author == self.user:
            return

        # Если бота упомянули — отвечаем
        if self.user in message.mentions:
            # Убираем упоминание из текста
            content = message.content
            for mention in message.mentions:
                content = content.replace(f"<@{mention.id}>", "").strip()

            if content:  # если есть текст после упоминания
                async with message.channel.typing():
                    response = await self.get_groq_response(
                        user_message=content,
                        channel_id=message.channel.id,
                        user_id=message.author.id,
                        user_name=message.author.global_name
                    )

                if len(response) > 1900:
                    chunks = [response[i:i + 1900] for i in range(0, len(response), 1900)]
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response)

        # Обязательно обрабатываем команды (для префиксных команд)
        await self.process_commands(message)

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        """Событие при изменении голосового состояния (пока пустое)"""
        pass


# ========== Запуск бота ==========

if __name__ == '__main__':
    # Получаем токены из переменных окружения
    token = os.getenv('DISCORD_TOKEN')
    groq_api_key = os.getenv('GROQ_API_KEY')

    if not token:
        raise ValueError('DISCORD_TOKEN not set in environment variables')
    if not groq_api_key:
        raise ValueError('GROQ_API_KEY not set in environment variables')

    # Настройка интентов
    intents = discord.Intents.default()
    intents.messages = True
    intents.message_content = True  # обязательно для чтения сообщений
    intents.members = True
    intents.presences = True

    # Создание бота
    bot = NSTA(command_prefix='!', intents=intents)

    # Инициализация Groq клиента
    bot.groq_client = groq.Groq(api_key=groq_api_key)

    # Запуск бота
    bot.run(token, log_level=logging.INFO)