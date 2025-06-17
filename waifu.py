# MIT License
# Copyright (c) 2025 Madara273

# --- Імпорти ---
import os
import random
import logging
import json
from asyncio import sleep
from time import time
from aiogram import Router, Bot, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramForbiddenError
from waifupics import waifu_sfw
import config

logger = logging.getLogger(__name__)
waifu_router = Router()

# --- Папка з зображеннями ---
WAIFU_FOLDER = os.path.join(os.getcwd(), config.WAIFU_FOLDER)
os.makedirs(WAIFU_FOLDER, exist_ok=True)

# --- Кеш авторизованих користувачів ---
authorized_users: dict[int, float] = {}

# --- Шлях до JSON-файлу з історією ---
WAIFU_HISTORY_FILE = os.path.join(WAIFU_FOLDER, "sent_waifus.json")

# --- Завантаження історії надсилань ---
def load_sent_history() -> dict[int, set[str]]:
	if os.path.exists(WAIFU_HISTORY_FILE):
		try:
			with open(WAIFU_HISTORY_FILE, "r", encoding="utf-8") as f:
				raw = json.load(f)
				return {int(k): set(v) for k, v in raw.items()}
		except Exception as e:
			logger.warning(f"Не вдалося завантажити історію waifu: {e}")
	return {}

# --- Збереження історії надсилань ---
def save_sent_history():
	try:
		with open(WAIFU_HISTORY_FILE, "w", encoding="utf-8") as f:
			json.dump({str(k): list(v) for k, v in sent_waifus_per_user.items()}, f, indent=2, ensure_ascii=False)
	except Exception as e:
		logger.warning(f"Не вдалося зберегти історію waifu: {e}")

# --- Історія надсилань ---
sent_waifus_per_user: dict[int, set[str]] = load_sent_history()

# --- Отримати випадкове зображення без повторень ---
def get_random_local_waifu(folder: str, user_id: int) -> str | None:
	try:
		files = [f for f in os.listdir(folder) if f.lower().endswith(config.SUPPORTED_IMAGE_FORMATS)]
		if not files:
			logger.info(f"Немає зображень у папці: {folder}")
			return None

		sent = sent_waifus_per_user.get(user_id, set())
		available = list(set(files) - sent)

		if not available:
			logger.info(f"Користувач {user_id} отримав усі зображення. Скидаємо список.")
			sent_waifus_per_user[user_id] = set()
			available = files

		chosen = random.choice(available)
		sent_waifus_per_user.setdefault(user_id, set()).add(chosen)
		save_sent_history()
		return os.path.join(folder, chosen)
	except Exception as e:
		logger.error(f"Помилка при доступі до папки {folder}: {e}")
		return None

# --- Обробка команди /waifu ---
@waifu_router.message(Command("waifu"))
async def waifu_cmd(message: types.Message, bot: Bot, is_internal_call: bool = False):
	user_id = message.from_user.id
	text = message.text.strip().split(maxsplit=1)
	password = text[1] if len(text) > 1 else ""

	if not is_internal_call:
		try:
			await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
			logger.info(f"Видалили команду /waifu від користувача {user_id} (ID: {message.message_id}).")
		except TelegramForbiddenError:
			logger.warning("Бот не має прав на видалення повідомлень.")
		except Exception as e:
			logger.warning(f"Не вдалося видалити повідомлення {message.message_id}: {e}")

	now = time()
	if user_id in authorized_users and (now - authorized_users[user_id]) < config.WAIFU_TIMEOUT:
		pass
	elif password == config.WAIFU_PASSWORD:
		authorized_users[user_id] = now
	else:
		if not is_internal_call:
			try:
				warn = await message.answer("Введи правильний пароль: `/waifu <пароль>`", parse_mode="MarkdownV2")
				await sleep(4)
				await warn.delete()
			except Exception as e:
				logger.warning(f"Не вдалося надіслати повідомлення про неправильний пароль: {e}")
		else:
			logger.error(f"Внутрішній виклик waifu_cmd для користувача %d не спрацював через невірний пароль.", user_id)
		return

	file_path = get_random_local_waifu(WAIFU_FOLDER, user_id)
	if file_path:
		try:
			await message.answer_photo(FSInputFile(file_path))
			return
		except Exception as e:
			logger.error(f"Помилка при надсиланні локального зображення: {e}")

	try:
		url = await waifu_sfw()
		if url:
			await message.answer(f'<a href="{url}">Дівчина</a>', parse_mode="HTML")
		else:
			raise ValueError("Порожнє посилання з API")
	except Exception as e:
		logger.error(f"Помилка при отриманні з API: {e}")

		if not is_internal_call:
			try:
				error_msg = await message.answer("Не вдалося завантажити зображення.")
				await sleep(2)
				await error_msg.delete()
			except Exception as e:
				logger.warning(f"Помилка при обробці помилки: {e}")
