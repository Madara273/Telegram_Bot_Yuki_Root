# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import os
import tempfile
import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, MAX_GENERATIONS, TIME_LIMIT_MINUTES

# --- Налаштування логування ---
logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s - %(levelname)s - %(message)s",
	datefmt="%Y-%m-%d %H:%M:%S"
)

# --- Ініціалізація ---
gen_router = Router()
client = genai.Client(api_key=GEMINI_API_KEY)
user_limits = defaultdict(list)
TIME_LIMIT = timedelta(minutes=TIME_LIMIT_MINUTES)

# --- Безпечне видалення з логуванням ---
async def safe_delete(msg: Message, description: str, user_id: int):
	"""
	Видаляє повідомлення та логує дію.
	Якщо немає прав або виникає помилка — логує попередження або помилку.
	"""
	try:
		await msg.delete()
		logging.info(f"Видалено: {description} | user_id={user_id} | msg_id={msg.message_id}")
	except TelegramForbiddenError:
		logging.warning(f"Немає прав для видалення: {description} | user_id={user_id} | msg_id={msg.message_id}")
	except Exception as e:
		logging.error(f"Помилка при видаленні ({description}) | user_id={user_id} | msg_id={msg.message_id} | {e}")

# --- Пояснення команди /gen ---
@gen_router.message(F.text == "/gen")
async def gen_help(message: Message):
	"""
	Видаляє команду миттєво, а інструкцію через 5 секунд.
	"""
	await safe_delete(message, "Команда користувача (/gen) миттєве видалення", message.from_user.id)

	msg = await message.answer(
		"*➟ Генерація зображення*\n"
		"Вкажи опис картинки після команди.\n"
		"Наприклад:\n"
		"`/gen красива аніме дівчина`\n"
		"І я намалюю для тебе зображення за цим описом!",
		parse_mode="Markdown"
	)
	await asyncio.sleep(5)
	await safe_delete(msg, "Повідомлення з інструкцією (/gen)", message.from_user.id)

# --- Генерація зображення за промптом ---
@gen_router.message(F.text.startswith("/gen "))
async def generate_image(message: Message):
	"""
	Генерує зображення за вказаним описом після /gen.
	Перевіряє обмеження на кількість генерацій за час.
	"""
	user_id = message.from_user.id

	# Ініціалізація лімітів
	if user_id not in user_limits:
		user_limits[user_id] = []

	# Видалення старих таймштампів
	now = datetime.now()
	user_limits[user_id] = [t for t in user_limits[user_id] if now - t < TIME_LIMIT]

	# Перевірка ліміту
	if len(user_limits[user_id]) >= MAX_GENERATIONS:
		time_left = TIME_LIMIT_MINUTES
		if user_limits[user_id]:
			time_left = max(0, (user_limits[user_id][0] + TIME_LIMIT - now).seconds // 60)

		msg = await message.answer(
			"✨ Ой-ой... Юкі вже стомилась малювати! ✨\n"
			f"Зараз можна тільки {MAX_GENERATIONS} картинок на {TIME_LIMIT_MINUTES} хвилин.\n"
			f"Давай трохи відпочинемо? Спробуй ще раз через {time_left} хвилинок! 💖\n"
			"А поки можеш погратись з іншими моїми функціями"
		)
		await asyncio.sleep(7)

		# Одночасне видалення повідомлень
		await asyncio.gather(
			safe_delete(msg, "Повідомлення бота (ліміт)", user_id),
			safe_delete(message, "Команда користувача (ліміт)", user_id)
		)
		return

	try:
		# Отримати промпт
		user_prompt = message.text[5:].strip()
		if not user_prompt:
			msg = await message.answer("❗ Введіть опис після /gen")
			await asyncio.sleep(5)
			await asyncio.gather(
				safe_delete(msg, "Повідомлення про помилку (порожній промпт)", user_id),
				safe_delete(message, "Команда користувача (порожній промпт)", user_id)
			)
			return

		# Анімація "завантаження фото"
		await message.chat.do("upload_photo")

		# --- Виклик API Gemini ---
		response = client.models.generate_images(
			model="imagen-4.0-ultra-generate-preview-06-06",
			prompt=user_prompt,
			config=types.GenerateImagesConfig(number_of_images=1)
		)

		if not response.generated_images:
			msg = await message.answer("Не вдалося згенерувати зображення")
			await asyncio.sleep(5)
			await asyncio.gather(
				safe_delete(msg, "Повідомлення про помилку (немає зображень)", user_id),
				safe_delete(message, "Команда користувача (помилка генерації)", user_id)
			)
			return

		user_limits[user_id].append(now)

		# Обробка результату
		generated_image = response.generated_images[0]
		tmp_file_path = None

		try:
			# Зберегти у тимчасовий файл
			with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
				tmp_file_path = tmp_file.name
				generated_image.image.save(tmp_file_path)

			# Відправити користувачу
			with open(tmp_file_path, "rb") as file:
				sent_photo = await message.answer_photo(
					photo=BufferedInputFile(file.read(), filename="generated.png")
				)

			# Видалити лише команду користувача
			await safe_delete(message, "Команда користувача (успішна генерація)", user_id)

		except Exception as e:
			logging.error(f"Помилка обробки: {e}", exc_info=True)
			msg = await message.answer("Помилка при обробці зображення")
			await asyncio.sleep(5)
			await asyncio.gather(
				safe_delete(msg, "Повідомлення про помилку обробки", user_id),
				safe_delete(message, "Команда користувача (помилка обробки)", user_id)
			)

		finally:
			# Видалити тимчасовий файл
			if tmp_file_path and os.path.exists(tmp_file_path):
				try:
					os.remove(tmp_file_path)
				except Exception as e:
					logging.warning(f"Не вдалося видалити тимчасовий файл: {e}")

	except TelegramAPIError as e:
		logging.error(f"Помилка Telegram: {e}")
		msg = await message.answer("Помилка відправки")
		await asyncio.sleep(5)
		await asyncio.gather(
			safe_delete(msg, "Повідомлення про помилку Telegram", user_id),
			safe_delete(message, "Команда користувача (помилка Telegram)", user_id)
		)

	except Exception as e:
		logging.error(f"Помилка генерації: {e}")
		msg = await message.answer("Помилка генерації зображення")
		await asyncio.sleep(5)
		await asyncio.gather(
			safe_delete(msg, "Повідомлення про помилку генерації", user_id),
			safe_delete(message, "Команда користувача (помилка генерації)", user_id)
		)
