# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import asyncio
import datetime
import json
import logging
import mimetypes
import re
import random
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory
from PIL import Image, UnidentifiedImageError

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
	Message,
	ChatMemberAdministrator,
	ChatMemberOwner,
	ChatMemberMember,
	ChatMemberRestricted,
)

# --- Модулі ---
import config
from config import GEMINI_API_KEY, SUPPORTED_IMAGE_FORMATS
from waifu import waifu_cmd, waifu_router

# --- Додатковий блок для telegramify_markdown ---
try:
	import telegramify_markdown
	TELEGRAMIFY_MARKDOWN_AVAILABLE = True
except ImportError:
	TELEGRAMIFY_MARKDOWN_AVAILABLE = False
	logging.warning("Бібліотека 'telegramify_markdown' не знайдена. Функції екранування Markdown будуть працювати в обмеженому режимі.")

# --- Налаштування логування ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("yuki.image_analyzer")
logger.setLevel(logging.INFO)

# --- Ім'я файлу бази даних для історії чатів (одна база для всіх) ---
DB_NAME = 'yuki_chat_history.db'

# --- Функція для завантаження системного промпта з JSON файлу ---
def load_system_prompt(file_name: str, key_name: str, default_message: str) -> str:
	"""
	Завантажує системний промпт з вказаного JSON файлу за вказаним ключем.
	Якщо файл не знайдено, JSON некоректний або ключ відсутній/порожній, повертає default_message.
	"""
	prompt_content = ""
	try:
		with open(file_name, 'r', encoding='utf-8') as f:
			prompts_data = json.load(f)
			prompt_content = prompts_data.get(key_name)

			if isinstance(prompt_content, list):
				prompt_content = "".join(prompt_content)
			elif not isinstance(prompt_content, str):
				prompt_content = ""

			if not prompt_content:
				logger.error(f"Не вдалося завантажити '%s' з %s. Значення відсутнє або порожнє.", key_name, file_name)
				prompt_content = default_message
	except FileNotFoundError:
		logger.error(f"Файл '%s' не знайдено. Переконайтеся, що він існує і шлях правильний.", file_name)
		prompt_content = default_message
	except json.JSONDecodeError as e:
		logger.error(f"Помилка декодування JSON у '%s'. Перевірте синтаксис файлу. Деталі: %s", file_name, e)
		prompt_content = default_message
	except Exception as e:
		logger.error(f"Невідома помилка при завантаженні промпта з '%s': %s", file_name, e)
		prompt_content = default_message
	return prompt_content

# --- Конфігурація Gemini ---
MAX_LENGTH = 2048

genai.configure(api_key=config.GEMINI_API_KEY)

gemini_model = genai.GenerativeModel(
	"gemini-2.0-flash",
	generation_config={
		"temperature": 0.9,
		"top_p": 1,
		"top_k": 1,
		"max_output_tokens": 2048,
	},
	safety_settings=[
		{"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
		{"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
		{"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
		{"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
	]
)

# --- Глобальні змінні для керування сесіями Gemini ---
active_users = set()

# --- Налаштування бази даних SQLite ---
async def init_db():
	"""Ініціалізує базу даних, створюючи таблицю для історії чатів з полем user_role."""
	try:
		async with aiosqlite.connect(DB_NAME) as db:
			await db.execute('''
				CREATE TABLE IF NOT EXISTS chat_histories (
					user_id INTEGER PRIMARY KEY,
					history TEXT,
					user_role TEXT DEFAULT 'REGULAR'
				)
			''')
			await db.commit()
			logger.info(f"База даних '%s' ініціалізована успішно з полем user_role.", DB_NAME)
	except aiosqlite.Error as e:
		logger.error(f"Помилка ініціалізації бази даних '%s': %s", DB_NAME, e)

# --- Отримання історії користувача з бази даних ---
async def get_user_history_from_db(user_id: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
	"""Завантажує історію чату та роль для конкретного користувача з бази даних."""
	try:
		async with aiosqlite.connect(DB_NAME) as db:
			cursor = await db.execute(
				"SELECT history, user_role FROM chat_histories WHERE user_id = ?", (user_id,)
			)
			result = await cursor.fetchone()
			if result:
				history_str, user_role = result
				try:
					history = json.loads(history_str)
					logger.info(f"Історія та роль '{user_role}' для користувача {user_id} завантажені з '{DB_NAME}'.")
					return history, user_role
				except json.JSONDecodeError as e:
					logger.error(f"Помилка декодування історії JSON для користувача {user_id} у '{DB_NAME}': {e}. Історія буде скинута.")
					return [], None
			logger.info(f"Історія для користувача {user_id} відсутня у '{DB_NAME}'.")
			return [], None
	except aiosqlite.Error as e:
		logger.error(f"Помилка при завантаженні історії для користувача {user_id} з '{DB_NAME}': {e}")
		return [], None

# --- Збереження історії користувача в базу даних ---
async def save_user_history_to_db(user_id: int, history: List[Dict[str, Any]], user_role: str):
	"""Зберігає історію чату та роль для конкретного користувача в базу даних."""
	try:
		async with aiosqlite.connect(DB_NAME) as db:
			history_json = json.dumps(history, ensure_ascii=False)
			await db.execute(
				"INSERT OR REPLACE INTO chat_histories (user_id, history, user_role) VALUES (?, ?, ?)",
				(user_id, history_json, user_role)
			)
			await db.commit()
			logger.info(f"Історія та роль '{user_role}' для користувача {user_id} збережена в '{DB_NAME}'.")
	except aiosqlite.Error as e:
		logger.error(f"Помилка при збереженні історії для користувача {user_id} у '{DB_NAME}': {e}")

# --- Видалення історії користувача з бази даних ---
async def delete_user_history_from_db(user_id: int):
	"""Видаляє історію чату для конкретного користувача з бази даних."""
	try:
		async with aiosqlite.connect(DB_NAME) as db:
			await db.execute("DELETE FROM chat_histories WHERE user_id = ?", (user_id,))
			await db.commit()
			logger.info(f"Історія для користувача {user_id} видалена з '{DB_NAME}'.")
	except aiosqlite.Error as e:
		logger.error(f"Помилка при видаленні історії для користувача {user_id}: {e}")

# --- Допоміжна функція для видалення повідомлень ---
async def delete_message_after_delay(message: Message, delay: int = 3):
	"""Видаляє повідомлення після заданої затримки."""
	await asyncio.sleep(delay)
	try:
		await message.delete()
	except Exception as e:
		logger.warning(
			"Не вдалося видалити повідомлення %d для користувача %d: %s",
			message.message_id,
			message.from_user.id,
			e
		)

# --- Функції для взаємодії з Gemini ---
async def get_gemini_response(user_id: int, text: str, image: Image.Image = None) -> str:
	"""
	Отримує відповідь від Gemini, використовуючи історію чату для конкретного користувача.
	Динамічно вибирає системний промпт залежно від user_id та зберігає/використовує user_role.
	Додано підтримку аналізу зображень.
	"""
	history, stored_role = await get_user_history_from_db(user_id)

	if user_id == config.TENZO_USER_ID:
		desired_role = 'TENZO'
		current_system_prompt = load_system_prompt(
			'promt_tenzo.json',
			"SYSTEM_PROMPT_YUKI_TENZO",
			"Помилка завантаження промта для Тензо. Зверніться до адміністратора."
		)
		initial_model_response = "Зрозуміла, мій коханий. Я готова бути твоєю Юкі"
	else:
		desired_role = 'REGULAR'
		current_system_prompt = load_system_prompt(
			'promt_user.json',
			"SYSTEM_PROMPT_YUKI_USER",
			"Помилка завантаження промта для звичайних користувачів. Зверніться до адміністратора."
		)
		initial_model_response = "Зрозуміла. Я готова допомогти"

	current_time_for_initial_prompt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	current_system_prompt = current_system_prompt.format(current_time=current_time_for_initial_prompt)

	if not history or stored_role != desired_role:
		logger.info(
			"Історія для користувача %d (поточна роль: %s, бажана роль: %s) буде ініціалізована/скинута.",
			user_id, stored_role, desired_role
		)
		history = [
			{"role": "user", "parts": [current_system_prompt]},
			{"role": "model", "parts": [initial_model_response]}
		]
		await save_user_history_to_db(user_id, history, desired_role)
	else:
		logger.info(
			"Використовується збережена історія для користувача %d з роллю '%s'.",
			user_id, stored_role
		)

	chat_session = gemini_model.start_chat(history=history)

	try:
		if image:
			response_obj = chat_session.send_message([text, image])
			history.append({"role": "user", "parts": [text, "IMAGE_PLACEHOLDER"]})
		else:
			response_obj = chat_session.send_message(text)
			history.append({"role": "user", "parts": [text]})

		history.append({"role": "model", "parts": [response_obj.text]})
		await save_user_history_to_db(user_id, history, desired_role)

		if response_obj and hasattr(response_obj, 'text') and response_obj.text:
			return response_obj.text
		else:
			if hasattr(response_obj, 'prompt_feedback') and response_obj.prompt_feedback.block_reason:
				block_reason = response_obj.prompt_feedback.block_reason
				logger.warning(
					"AI відповідь заблокована для користувача %d (роль '%s'): %s",
					user_id, desired_role, block_reason
				)
				return (
					f"Ох, моє серце AI не змогло відповісти на це. Його щось зупинило... "
					f"(зніяковіло) Причина блокування: {block_reason}. "
				)
			else:
				return "Вибач, я не змогла згенерувати відповідь. Спробуй ще раз."
	except Exception as e:
		tab_error_str = str(e)
		if "SERVICE_DISABLED" in tab_error_str or "generativelanguage.googleapis.com" in tab_error_str:
			logger.warning(
				"Generative Language API не активована або не використовувалась для проєкту. UID=%d, роль=%s",
				user_id, desired_role
			)
			return (
				"🌸 *Yuki* трохи розгублена...\n"
				"Схоже, *Generative Language API* ще не активовано для цього проєкту 😥\n\n"
				"🔁 Або це тимчасовий збій API.\n"
				"Не хвилюйся, спробуй ще раз за мить 💖"
			)
		logger.error(
			"Помилка при отриманні відповіді від AI для користувача %d (роль '%s'): %s",
			user_id, desired_role, e, exc_info=True
		)
		return "Вибач, виникла помилка під час обробки твого запиту. Спробуй ще раз пізніше."

# --- Роутер для Gemini-функціоналу ---
yuki_router = Router()

# --- Команда get_yuki ---
@yuki_router.message(Command("get_yuki"))
async def get_gemini_handler(message: Message):
	user_id = message.from_user.id
	try:
		await message.delete()
	except Exception as e:
		logger.warning(f"Не вдалося видалити /get_yuki від %d: %s", user_id, e)

	if user_id not in active_users:
		active_users.add(user_id)
		logger.info(f"Користувач %d активував сесію Gemini.", user_id)
		await message.answer("✔️ Привіт! Я готова допомогти. Я твоя Юкі. Запитай мене.")
	else:
		await message.answer("💡 Я вже активна. Просто продовжуй писати.")

# --- Команда sleep yuki ---
@yuki_router.message(Command("sleep"))
async def sleep_gemini_handler(message: Message):
	user_id = message.from_user.id
	try:
		await message.delete()
	except Exception as e:
		logger.warning(f"Не вдалося видалити /sleep від %d: %s", user_id, e)

	if user_id in active_users:
		active_users.discard(user_id)
		logger.info(f"Користувач %d завершив сесію Gemini.", user_id)
		reply = await message.answer("📴 Сесію Yuki завершено. Щоб увімкнути знову — надішли /get_yuki.")
		await delete_message_after_delay(reply)
	else:
		reply = await message.answer("✖️ Сесія Yuki не активна. Надішли /get_yuki, щоб почати.")
		await delete_message_after_delay(reply)

# --- Скидання історії Юкі ---
@yuki_router.message(Command("reset_yuki"))
async def reset_gemini_handler(message: Message):
	user_id = message.from_user.id
	try:
		await message.delete()
	except Exception as e:
		logger.warning(f"Не вдалося видалити /reset_yuki від %d: %s", user_id, e)

	await delete_user_history_from_db(user_id)
	logger.info(f"Історія для користувача %d була скинута командою /reset_yuki.", user_id)
	reply = await message.answer("✔️ Історію Юкі для тебе скинуто. Вона розпочне діалог знову відповідно до твоєї поточної ролі (Тензо/звичайний користувач).")
	await delete_message_after_delay(reply)

# --- Асинхронний обробник ---
@yuki_router.message(F.text)
async def handle_gemini_message(message: Message, bot: Bot):
	user_id = message.from_user.id
	chat_id = message.chat.id
	message_id = message.message_id
	user_text = message.text

	logger.info(f"[UID={user_id}][CID={chat_id}] Отримано повідомлення ID={message_id}: '{user_text[:50]}...'")

	if user_id not in active_users:
		logger.info(f"[UID={user_id}] Сесія Gemini неактивна.")
		return

	await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
	logger.info(f"[CID={chat_id}] Статус 'друкує...' надіслано.")

	current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	augmented_user_text = f"Поточна дата і час: {current_time_str}. {user_text}"
	logger.info(f"[UID={user_id}] Додано актуальний час до повідомлення користувача: '{augmented_user_text[:50]}...'")

	try:
		ai_response = await get_gemini_response(user_id, augmented_user_text)
	except Exception as e:
		logger.error(f"[UID={user_id}] Помилка у get_gemini_response: {e}", exc_info=True)
		await message.answer("😵 Вибач, я не змогла відповісти на твоє повідомлення.")
		return

	if "[CALL_WAIFU_COMMAND]" in ai_response:
		logger.info(f"[UID={user_id}] Виявлено [CALL_WAIFU_COMMAND], виконую waifu_cmd.")
		await handle_waifu_command(bot, message)
		return

	raw_response = safe_truncate_markdown(ai_response, 8000)
	logger.info(f"[UID={user_id}] Надсилаю відповідь AI.")
	await send_long_message(
		bot=bot,
		chat_id=chat_id,
		raw_text=raw_response,
		parse_mode=ParseMode.MARKDOWN_V2
	)

async def handle_waifu_command(bot: Bot, message: Message):
	user_id = message.from_user.id
	chat_id = message.chat.id

	await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
	logger.info(f"[CID={chat_id}] Статус 'завантажує фото...' надіслано.")
	await asyncio.sleep(2)

	fake_msg_data = {
		"message_id": message.message_id,
		"from": message.from_user.model_dump(),
		"chat": message.chat.model_dump(),
		"date": message.date,
		"text": f"/waifu {config.WAIFU_PASSWORD}",
	}
	fake_message = Message.model_validate(fake_msg_data).as_(bot)
	logger.debug(f"[UID={user_id}] Створено fake_message: '{fake_message.text}'")

	try:
		await waifu_cmd(fake_message, bot, is_internal_call=True)
	except Exception as e:
		logger.error(f"[UID={user_id}] Помилка у waifu_cmd: {e}", exc_info=True)
		await message.answer("😥 Вибач, але зараз я не можу надіслати фото.")

# --- Функції екранування та балансування Markdown ---
def escape_md_v2_safe(text: str) -> str:
	"""
	Безпечне екранування MarkdownV2.
	Використовує telegramify_markdown, якщо доступний, інакше - ручне екранування.
	Це забезпечує максимальну стійкість до невідомих або небезпечних символів.
	"""
	if TELEGRAMIFY_MARKDOWN_AVAILABLE:
		try:
			return telegramify_markdown.markdownify(
				text,
				max_line_length=None,
				normalize_whitespace=False,
				latex_escape=True
			)
		except Exception as e:
			logger.error(f"Помилка при використанні telegramify_markdown, fallback до ручного екранування: {e}")
			pass

	escape_chars = r"\_*[]()~`>#+-=|{}.!$"
	return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def balance_markdown(text: str) -> str:
	"""
	Балансує незакриті MarkdownV2 блоки для уникнення помилок парсингу.
	Перевіряє: `**`, `__`, `~~`, `||`, `$$`, ```.
	"""

	tags_to_balance = {
		"```": "```",
		"**": "**",
		"__": "__",
		"~~": "~~",
		"||": "||",
		"$$": "$$"
	}

	balanced_text = text
	for open_tag, close_tag in tags_to_balance.items():
		if balanced_text.count(open_tag) % 2 != 0:
			balanced_text += close_tag
	return balanced_text

def safe_truncate_markdown(text: str, max_length: int) -> str:
	"""
	Безпечне обрізання повідомлення без розриву MarkdownV2.
	Обрізає текст до заданої довжини, додаючи суфікс,
	і намагається збалансувати будь-які відкриті MarkdownV2 теги.
	"""
	if len(text) <= max_length:
		return balance_markdown(text)

	suffix = "\n\n... (відповідь обрізана)"
	truncated = text[:max_length - len(suffix)]

	truncated = balance_markdown(truncated)

	return truncated + suffix

# --- Надсилання довгих повідомлень у Telegram з автоматичним захистом ---
async def send_long_message(
	bot: Bot,
	chat_id: int,
	raw_text: str,
	parse_mode: ParseMode = ParseMode.MARKDOWN_V2,
	fallback_to_plain: bool = True
):
	"""
	Надсилає довгі повідомлення, гарантовано захищаючи від усіх markdown помилок.
	Автоматично розбиває повідомлення на частини, якщо воно перевищує MAX_LENGTH.
	"""
	processed_text = escape_md_v2_safe(raw_text)
	processed_text = balance_markdown(processed_text)

	if len(processed_text) <= MAX_LENGTH:
		try:
			await bot.send_message(chat_id, processed_text, parse_mode=parse_mode)
		except Exception as e:
			logger.error(f"Помилка при відправці короткого повідомлення: {e}")
			if fallback_to_plain:
				logger.warning(f"Відправка повідомлення як Plain Text через помилку MarkdownV2: {e}")
				await bot.send_message(chat_id, raw_text)
			else:
				raise e
		return

	parts = []
	current_part = ""
	in_code_block = False
	lines = processed_text.split("\n")

	for line in lines:
		line_with_newline = line + "\n"

		if "```" in line:
			in_code_block = not in_code_block

		if len(current_part) + len(line_with_newline) > MAX_LENGTH:

			if in_code_block and not current_part.strip().endswith("```"):
				current_part += "```\n"
				parts.append(current_part)
				current_part = "```\n" + line_with_newline
			else:
				parts.append(current_part)
				current_part = line_with_newline
		else:
			current_part += line_with_newline

	if current_part:

		if in_code_block and not current_part.strip().endswith("```"):
			current_part += "```\n"
		parts.append(current_part)

	for i, part in enumerate(parts):

		prefix = f"*{i+1}/{len(parts)}*\n" if len(parts) > 1 else ""

		final_part = escape_md_v2_safe(prefix) + part
		final_part = balance_markdown(final_part)

		if len(final_part) > MAX_LENGTH:
			final_part = safe_truncate_markdown(final_part, MAX_LENGTH)

		try:
			await bot.send_message(chat_id, final_part, parse_mode=parse_mode)
		except Exception as e:
			logger.error(f"Помилка при відправці частини повідомлення ({i+1}/{len(parts)}): {e}")
			if fallback_to_plain:
				logger.warning(f"Відправка частини повідомлення як Plain Text через помилку MarkdownV2: {e}")

				await bot.send_message(chat_id, part)
			else:
				raise e
			continue
		await asyncio.sleep(0.4)

# --- Перевірка прав бота ---
async def can_bot_send_messages(message: Message) -> bool:
	"""
	Перевіряє, чи має бот права на надсилання повідомлень у поточному чаті.
	"""
	try:
		member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
		if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner, ChatMemberMember)):
			return True
		if isinstance(member, ChatMemberRestricted):
			return member.can_send_messages is True
	except TelegramForbiddenError:
		logger.warning(f"Бот не може надсилати повідомлення в чаті {message.chat.id}: доступ заборонено.")
		return False
	except Exception as e:
		logger.error(f"Невідома помилка при перевірці прав бота в чаті {message.chat.id}: {e}")
		return False
	return False

# --- УНІВЕРСАЛЬНИЙ ОБРОБНИК ПОВІДОМЛЕНЬ ---
@yuki_router.message()
async def universal_fallback_handler(message: Message, bot: Bot):
	tmp_path = None
	user_id = message.from_user.id
	username = message.from_user.username or str(user_id)
	chat_id = message.chat.id
	is_active = user_id in active_users

	if not is_active:
		logger.info(f"[Fallback] Проігноровано повідомлення від неактивного користувача @{username}.")
		return

	if message.text and message.text.startswith("/"):
		logger.info(f"[Fallback] Проігнорована нерозпізнана команда від @{username}: '{message.text}'")
		return

	if not await can_bot_send_messages(message):
		logger.warning(f"[PERMISSION] Бот не має прав у чаті {chat_id}")
		return

	await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

	ai_response = None
	response_text_to_user = "Вибач, виникла помилка під час обробки твого запиту. Спробуй ще раз пізніше."
	current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	start_time = time.perf_counter()

	try:
		if message.photo:
			photo = message.photo[-1]
			file = await message.bot.get_file(photo.file_id)

			if file.file_size > 10 * 1024 * 1024:
				response_text_to_user = "Зображення занадто велике для аналізу (макс 10MB)."
				await message.reply(response_text_to_user)
				return

			ext = Path(file.file_path).suffix.lower()
			if ext not in SUPPORTED_IMAGE_FORMATS:
				response_text_to_user = "Цей формат зображення не підтримується."
				await message.reply(response_text_to_user)
				return

			mime_type, _ = mimetypes.guess_type(file.file_path)
			if not mime_type or not mime_type.startswith("image/"):
				response_text_to_user = "Файл не є зображенням."
				await message.reply(response_text_to_user)
				return

			photo_bytes = await message.bot.download_file(file.file_path)
			with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
				tmp.write(photo_bytes.read())
				tmp_path = tmp.name

			try:
				with Image.open(tmp_path) as img:
					img = img.convert("RGB")
					img_copy = img.copy()
			except UnidentifiedImageError:
				response_text_to_user = "Неможливо відкрити зображення. Можливо, воно пошкоджене."
				await message.reply(response_text_to_user)
				return

			ai_response = await get_gemini_response(user_id, "", image=img_copy)

		elif message.text:
			logger.info(f"[Universal Handler] Отримано текстове повідомлення від @{username}: '{message.text}'")
			ai_response = await get_gemini_response(user_id, message.text)

		else:
			logger.info(f"[Universal Handler] Отримано непідтримуване повідомлення (тип: {message.content_type}) від @{username}.")
			prompt_for_gemini_unsupported = (
				f"Поточна дата і час: {current_time_str}. "
				f"Користувач надіслав повідомлення типу '{message.content_type}', яке бот не може обробити. "
				f"Сформулюй відповідь у стилі Yuki — дружньої дівчини-помічниці, яка щиро вибачається і просить надіслати текст."
			)
			ai_response = await get_gemini_response(user_id, prompt_for_gemini_unsupported)

		if ai_response:
			response_text_to_user = ai_response.strip().replace("[CALL_WAIFU_COMMAND]", "").strip()

			if not response_text_to_user:
				logger.warning("Gemini повернув порожній текст. Відповідь не буде надіслана.")
				await message.reply("Юкі розгубилась і нічого не сказала... 🥺 Спробуй ще раз?")
				return

			escaped_response = escape_md_v2_safe(safe_truncate_markdown(response_text_to_user, 8000))

			await send_long_message(
				bot=bot,
				chat_id=chat_id,
				raw_text=escaped_response,
				parse_mode=ParseMode.MARKDOWN_V2
			)
		else:
			response_text_to_user = "Юкі не змогла згенерувати відповідь. Спробуй ще раз."
			await message.reply(escape_md_v2_safe(response_text_to_user), parse_mode=ParseMode.MARKDOWN_V2)

	except TelegramBadRequest as e:
		logger.warning(f"[TelegramError] {e}")
		response_text_to_user = "Ой, виникла проблема з відправкою відповіді Telegram. Спробую ще раз пізніше."
		await message.reply(escape_md_v2_safe(response_text_to_user), parse_mode=ParseMode.MARKDOWN_V2)

	except Exception as e:
		logger.exception(f"[UNIVERSAL_HANDLER_ERROR] Помилка при обробці повідомлення від @{username}: {e}")
		response_text_to_user = "Вибач, виникла неочікувана помилка. Спробуй ще раз пізніше."
		await message.reply(escape_md_v2_safe(response_text_to_user), parse_mode=ParseMode.MARKDOWN_V2)

	finally:
		duration = time.perf_counter() - start_time
		logger.info(f"[Timing] Аналіз повідомлення від @{username} зайняв {duration:.2f} сек.")
		if tmp_path:
			try:
				Path(tmp_path).unlink(missing_ok=True)
			except Exception as e:
				logger.warning(f"[CLEANUP] Не вдалося видалити тимчасовий файл: {e}")
