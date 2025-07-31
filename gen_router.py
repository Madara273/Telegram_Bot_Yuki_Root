# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import tempfile
import os
from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.exceptions import TelegramAPIError
from google import genai
from google.genai import types
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from config import GEMINI_API_KEY, MAX_GENERATIONS, TIME_LIMIT_MINUTES

gen_router = Router()
client = genai.Client(api_key=GEMINI_API_KEY)

user_limits = defaultdict(list)
TIME_LIMIT = timedelta(minutes=TIME_LIMIT_MINUTES)

@gen_router.message(F.text.startswith("/gen "))
async def generate_image(message: Message):
	user_id = message.from_user.id

	now = datetime.now()
	user_limits[user_id] = [t for t in user_limits[user_id] if now - t < TIME_LIMIT]

	if len(user_limits[user_id]) >= MAX_GENERATIONS:
		time_left = (user_limits[user_id][0] + TIME_LIMIT - now).seconds // 60
		await message.reply(
			"✨ Ой-ой... Юкі вже стомилась малювати! ✨\n"
			f"Зараз можна тільки {MAX_GENERATIONS} картинок на {TIME_LIMIT_MINUTES} хвилин.\n"
			f"Давай трохи відпочинемо? Спробуй ще раз через {time_left} хвилинок! 💖\n"
			"А поки можеш погратись з іншими моїми функціями~"
		)
		return

	try:
		user_prompt = message.text[5:].strip()
		if not user_prompt:
			await message.reply("❗ Введіть опис після /gen")
			return

		await message.chat.do("upload_photo")

		response = client.models.generate_images(
			model="imagen-4.0-ultra-generate-preview-06-06",
			prompt=user_prompt,
			config=types.GenerateImagesConfig(
				number_of_images=1
			)
		)

		if not response.generated_images:
			await message.reply("Не вдалося згенерувати зображення")
			return

		user_limits[user_id].append(now)

		generated_image = response.generated_images[0]
		tmp_file_path = None

		try:
			with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
				tmp_file_path = tmp_file.name
				generated_image.image.save(tmp_file_path)

			with open(tmp_file_path, "rb") as file:
				await message.answer_photo(
					photo=BufferedInputFile(file.read(), filename="generated.png"),
					caption=f"{user_prompt}",
					parse_mode="Markdown"
				)

		except Exception as e:
			logging.error(f"Помилка обробки: {e}", exc_info=True)
			await message.reply("Помилка при обробці зображення")

		finally:
			if tmp_file_path and os.path.exists(tmp_file_path):
				try:
					os.remove(tmp_file_path)
				except Exception as e:
					logging.warning(f"Не вдалося видалити тимчасовий файл: {e}")

	except TelegramAPIError as e:
		logging.error(f"Помилка Telegram: {e}")
		await message.reply("Помилка відправки")

	except Exception as e:
		logging.error(f"Помилка генерації: {e}")
		await message.reply("Помилка генерації зображення")
