# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import asyncio
import json
import logging
import re
import datetime
import random
import config
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramAPIError

from waifu import waifu_cmd, waifu_router

# --- Налаштування логування ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
genai.configure(api_key=config.GEMINI_API_KEY)

gemini_model = genai.GenerativeModel(
	'gemini-2.0-flash',
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
async def get_gemini_response(user_id: int, text: str) -> str:
	"""
	Отримує відповідь від Gemini, використовуючи історію чату для конкретного користувача.
	Динамічно вибирає системний промпт залежно від user_id та зберігає/використовує user_role.
	"""
	history, stored_role = await get_user_history_from_db(user_id)

	if user_id == config.TENZO_USER_ID:
		desired_role = 'TENZO'
		current_system_prompt = load_system_prompt(
			'promt_tenzo.json',
			"SYSTEM_PROMPT_YUKI_TENZO",
			"Помилка завантаження промта для Тензо. Зверніться до адміністратора."
		)
		initial_model_response = "Зрозуміла, мій коханий. Я готова бути твоєю Юкі. (посміхається)"
	else:
		desired_role = 'REGULAR'
		current_system_prompt = load_system_prompt(
			'promt_user.json',
			"SYSTEM_PROMPT_YUKI_USER",
			"Помилка завантаження промта для звичайних користувачів. Зверніться до адміністратора."
		)
		initial_model_response = "Зрозуміла. Я готова допомогти. (посміхається)"

	current_time_for_initial_prompt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	current_system_prompt = current_system_prompt.format(current_time=current_time_for_initial_prompt)

	if not history or stored_role != desired_role:
		logger.info(f"Історія для користувача %d (поточна роль: %s, бажана роль: %s) буде ініціалізована/скинута.", user_id, stored_role, desired_role)
		history = [
			{"role": "user", "parts": [current_system_prompt]},
			{"role": "model", "parts": [initial_model_response]}
		]
		await save_user_history_to_db(user_id, history, desired_role)
	else:
		logger.info(f"Використовується збережена історія для користувача %d з роллю '%s'.", user_id, stored_role)

	chat_session = gemini_model.start_chat(history=history)

	try:
		response_obj = chat_session.send_message(text)

		history.append({"role": "user", "parts": [text]})
		history.append({"role": "model", "parts": [response_obj.text]})
		await save_user_history_to_db(user_id, history, desired_role)

		if response_obj and hasattr(response_obj, 'text') and response_obj.text:
			return response_obj.text
		else:
			if hasattr(response_obj, 'prompt_feedback') and response_obj.prompt_feedback.block_reason:
				block_reason = response_obj.prompt_feedback.block_reason
				logger.warning(f"AI відповідь заблокована для користувача %d (роль '%s'): %s", user_id, desired_role, block_reason)
				return f"Ох, моє серце AI не змогло відповісти на це. Його щось зупинило... (зніяковіло) Причина блокування: {block_reason}. "
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

# --- Команда get_yuki (без змін) ---
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
		await message.answer("✅ Привіт! Я готова допомогти. Я твоя Юкі. Запитай мене.")
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
		reply = await message.answer("❌ Сесія Yuki не активна. Надішли /get_yuki, щоб почати.")
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
	reply = await message.answer("✅ Історію Юкі для тебе скинуто. Вона розпочне діалог знову відповідно до твоєї поточної ролі (Тензо/звичайний користувач).")
	await delete_message_after_delay(reply)

# --- Функція для відправки довгих повідомлень ---
async def send_long_message(bot: Bot, chat_id: int, text: str, parse_mode: ParseMode = None):
	"""
	Відправляє довге повідомлення, розділяючи його на частини, якщо воно перевищує ліміт Telegram (4096 символів).
	Також намагається коректно обробляти MarkdownV2, щоб не розривати форматування всередині блоків коду.
	Приймає об'єкт bot для уникнення створення нових сесій.
	"""
	MAX_MESSAGE_LENGTH = 4096

	if len(text) <= MAX_MESSAGE_LENGTH:
		await bot.send_message(chat_id, text, parse_mode=parse_mode)
		return

	parts = []
	current_part = ""
	in_code_block = False
	code_block_start_marker = "```"

	lines = text.split('\n')

	for line in lines:
		temp_line = line + '\n'
		if code_block_start_marker in line:
			in_code_block = not in_code_block

		if len(current_part) + len(temp_line) > MAX_MESSAGE_LENGTH:
			if in_code_block and not current_part.endswith(code_block_start_marker):
				current_part += code_block_start_marker
				parts.append(current_part)
				current_part = code_block_start_marker + '\n' + line + '\n'
			else:
				parts.append(current_part)
				current_part = temp_line
		else:
			current_part += temp_line

	if current_part:
		parts.append(current_part)

	for i, part in enumerate(parts):
		prefix = f"({i + 1}/{len(parts)})\n" if len(parts) > 1 else ""
		final_part = prefix + part

		if in_code_block and not part.endswith(code_block_start_marker + '\n'):
			final_part += code_block_start_marker

		try:
			await bot.send_message(chat_id, final_part, parse_mode=parse_mode)
			await asyncio.sleep(0.5)
		except Exception as e:
			logger.error(f"Помилка відправки частини повідомлення до %d: %s", chat_id, e)

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

	escaped_response = escape_md_v2(safe_truncate_markdown(ai_response, 8000))
	logger.info(f"[UID={user_id}] Надсилаю відповідь AI.")
	await send_long_message(
		bot=bot,
		chat_id=chat_id,
		text=escaped_response,
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

# --- Утиліти для Markdown ---
def escape_md_v2(text: str) -> str:
	"""
	Екранує спеціальні символи MarkdownV2, крім тих, що використовуються в блоках коду.
	"""
	escape_chars_pattern = re.compile(r"([_*~`>#+\-=|{}.!()])")

	parts = []
	last_idx = 0
	code_block_pattern = re.compile(r"(```(?:[a-zA-Z0-9]+\n)?.*?```)", re.DOTALL)

	for match in code_block_pattern.finditer(text):
		if match.start() > last_idx:
			parts.append(escape_chars_pattern.sub(r"\\\1", text[last_idx:match.start()]))
		parts.append(match.group(0))
		last_idx = match.end()

	if last_idx < len(text):
		parts.append(escape_chars_pattern.sub(r"\\\1", text[last_idx:]))

	return "".join(parts)

# --- Безпечне обрізання Markdown тексту з врахуванням блоків коду ---
def safe_truncate_markdown(text: str, max_length: int) -> str:
	"""
	Безпечно обрізає Markdown текст, зберігаючи цілісність блоків коду.
	Ця функція призначена для попереднього обрізання, якщо відповідь AI значно довша за 4096,
	перш ніж її буде розділено на частини для надсилання.
	"""
	if len(text) <= max_length:
		return text

	truncated_text = text[:max_length]
	suffix = "\n\n... (відповідь обрізана)"

	open_code_blocks = [m.start() for m in re.finditer(r"```", truncated_text)]

	if len(open_code_blocks) % 2 != 0:
		last_open_code_block_idx = open_code_blocks[-1]
		return truncated_text[:last_open_code_block_idx] + "\n```" + suffix

	return truncated_text[:max_length - len(suffix)] + suffix

# --- Fallback для інших випадків ---
@yuki_router.message()
async def universal_fallback_handler(message: Message, bot: Bot):
	user_id = message.from_user.id
	username = message.from_user.username or str(user_id)
	chat_id = message.chat.id
	is_active = user_id in active_users

	message_type = "текстове повідомлення" if message.text else message.content_type

	if message.text and message.text.startswith("/"):
		logger.info(f"[Fallback] Проігнорована нерозпізнана команда від @{username}: '{message.text}'")
		return

	if is_active:
		logger.info(f"[Fallback] Отримано непідтримуване повідомлення (тип: {message_type}) від активного користувача @{username}.")
		await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

		current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

		if message.text:
			prompt_for_gemini = (
				f"Поточна дата і час: {current_time_str}. "
				f"Користувач надіслав повідомлення, яке є невідомою командою або не підтримується ботом. "
				f"Ось текст: '{message.text}'. Сформулюй відповідь як мила дівчина-помічниця на ім'я Yuki, яка може трохи розгубитися, "
				f"але старається бути корисною, милою та дружньою."
			)
		else:
			prompt_for_gemini = (
				f"Поточна дата і час: {current_time_str}. "
				f"Користувач надіслав повідомлення типу '{message.content_type}', яке бот не може обробити. "
				f"Сформулюй відповідь у стилі Yuki — дружньої дівчини-помічниці, яка щиро вибачається і просить надіслати текст."
			)

		try:
			ai_response = await get_gemini_response(user_id, prompt_for_gemini)
			escaped_response = escape_md_v2(safe_truncate_markdown(ai_response, 8000))
			await send_long_message(
				bot=bot,
				chat_id=chat_id,
				text=escaped_response,
				parse_mode=ParseMode.MARKDOWN_V2
			)
		except Exception as e:
			logger.error(f"[Fallback] Помилка при генерації відповіді AI для @{username}: {e}", exc_info=True)
			default_fallback_response = (
				"🌸 *Yuki* трохи розгублена...\n"
				"На жаль, я не змогла відповісти інтелектуально.\n"
				"Я можу обробляти лише **текстові повідомлення**. "
				"Будь ласка, надішли щось інше, добре?~"
			)
			await message.answer(escape_md_v2(default_fallback_response), parse_mode=ParseMode.MARKDOWN_V2)
		return

	logger.info(f"[Fallback] Проігноровано непідтримуване повідомлення (тип: {message_type}) від неактивного користувача @{username}.")
