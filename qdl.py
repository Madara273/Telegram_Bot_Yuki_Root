# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import os
import re
import uuid
import glob
import asyncio
import logging
import traceback
import urllib.parse

from aiogram import Router
from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import (
	Message,
	CallbackQuery,
	InlineKeyboardButton,
	InlineKeyboardMarkup,
	FSInputFile
)

from yt_dlp.utils import DownloadError
import yt_dlp

# --- Ініціалізація ---
qdl_router = Router()
TMP_DIR = "tmp_downloads"
os.makedirs(TMP_DIR, exist_ok=True)

logger = logging.getLogger(__name__)
logging.getLogger("yt_dlp").setLevel(logging.CRITICAL)

# --- Конфігурація ---
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ
prompt_messages = {} # Зберегти message_id для видалення клавіатури
pending_queries = {} # Зберегти запити, пов'язані з query_id для колбеків
pattern_tiktok_photo = re.compile(r"https?://(?:www\.)?tiktok.com/.+/photo/?")

# --- Клас кастомного логера для yt_dlp ---
class MyLogger:
	def debug(self, msg):
		pass

	def warning(self, msg):
		if "Falling back on generic information extractor" in msg or \
		   "yt-dlp is not a command" in msg:
			return
		logging.warning(f"YTDLP Warning: {msg}")

	def error(self, msg):
		if "Unsupported URL" in msg:
			return
		logging.error(f"YTDLP Error: {msg}")

# --- Перевірка підтримки URL ---
def is_unsupported_url(url: str) -> bool:
	try:
		parsed = urllib.parse.urlparse(url)
		if "tiktok.com" in url:
			if "/photo/" in parsed.path:
				return True
			query_params = urllib.parse.parse_qs(parsed.query)
			if query_params.get("aweme_type", [""])[0] == "150":
				return True
		return False
	except Exception as e:
		logging.error(f"Помилка при перевірці URL: {e}")
		return False

# --- Безпечна спроба отримати інформацію через yt_dlp ---
def safe_extract_info(url):
	if is_unsupported_url(url):
		return {"message": "Вибачте, але завантаження TikTok фото/сторіс наразі не підтримується.", "url": url}

	ydl_opts = {
		'logger': MyLogger(),
		'quiet': True,
		'no_warnings': True,
		'force_generic_extractor': True,
	}

	ydl = yt_dlp.YoutubeDL(ydl_opts)
	try:
		return ydl.extract_info(url, download=False)
	except DownloadError as e:
		if "Unsupported URL" in str(e):
			return {"message": "URL не підтримується aбо посилання не дійсне.", "url": url}
		logging.error(f"Yt-dlp DownloadError під час extract_info: {e}")
		return {"message": "Помилка при отриманні інформації про посилання. Перевірте його.", "url": url}
	except Exception as e:
		logging.error(f"Невідома помилка під час extract_info: {e}")
		return {"message": "Невідома помилка при обробці посилання. Спробуйте інше.", "url": url}

# --- Обробка команди /qdl ---
@qdl_router.message(Command("qdl"))
async def cmd_qdl(message: Message, bot: Bot):
	parts = message.text.strip().split(maxsplit=1)
	uid = message.from_user.id
	await message.delete()

	if len(parts) != 2:
		warn_msg = await message.answer(
			"ℹ️    Вкажи посилання або пошуковий запит після команди. Наприклад:\n"
			"`/qdl https://tiktok.com/...` або `/qdl never gonna give you up`",
			parse_mode="Markdown"
		)
		await asyncio.sleep(5)
		await warn_msg.delete()
		return

	query = parts[1].strip()
	query_id = str(uuid.uuid4())
	pending_queries[query_id] = query

	keyboard = InlineKeyboardMarkup(inline_keyboard=[
		[
			InlineKeyboardButton(text="🎥 Відео", callback_data=f"qdl_video|{query_id}"),
			InlineKeyboardButton(text="🎵 Аудіо", callback_data=f"qdl_audio|{query_id}")
		]
	])

	prompt_msg = await message.answer("⬇️ Обери формат завантаження:", reply_markup=keyboard)
	prompt_messages[uid] = prompt_msg.message_id

	# Видалити клавіатуру через 15 секунд
	async def auto_delete_buttons():
		await asyncio.sleep(15)
		if prompt_messages.get(uid) == prompt_msg.message_id:
			try:
				await bot.delete_message(message.chat.id, prompt_msg.message_id)
			except Exception as e:
				logging.warning(f"Не вдалося видалити повідомлення з кнопками ({prompt_msg.message_id}): {e}")
			finally:
				prompt_messages.pop(uid, None)

	asyncio.create_task(auto_delete_buttons())

# --- Обробка callback кнопок формату ---
@qdl_router.callback_query(lambda c: c.data and c.data.startswith("qdl_"))
async def process_qdl_callback(query: CallbackQuery, bot: Bot):
	uid = query.from_user.id
	data = query.data
	action, query_id = data.split("|", maxsplit=1)
	input_text = pending_queries.pop(query_id, None)

	prompt_msg_id = prompt_messages.pop(uid, None)
	if prompt_msg_id:
		try:
			await bot.delete_message(query.message.chat.id, prompt_msg_id)
		except Exception as e:
			logging.warning(f"Не вдалося видалити повідомлення з кнопками після callback: {e}")

	if not input_text:
		await query.message.answer("⚠️ Посилання недійсне або застаріле. Спробуй ще раз.")
		await query.answer()
		return

	status_msg = await query.message.answer("⏬ Триває завантаження...")
	await query.answer()

	# Формування пошукового або прямого запиту
	search_query = input_text if re.match(r'https?://', input_text) else f"ytsearch:{input_text}"

	# Перевірка підтримки контенту
	info_check = safe_extract_info(search_query)
	if isinstance(info_check, dict) and "message" in info_check:
		await status_msg.edit_text(f"⚠️ {info_check['message']}")
		await asyncio.sleep(5)
		await status_msg.delete()
		return

	video_id = str(uuid.uuid4())
	output_template = os.path.join(TMP_DIR, f"{video_id}.%(ext)s")

	# Загальні опції
	base_opts = {
		'outtmpl': output_template,
		'default_search': 'ytsearch',
		'nocheckcertificate': True,
		'quiet': True,
		'restrictfilenames': True,
		'noplaylist': True,
	}

	# Формат завантаження
	if action == "qdl_video":
		ydl_opts = {
			**base_opts,
			'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
			'postprocessors': [
				{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
				{'key': 'FFmpegMetadata'}
			]
		}
	else: # qdl_audio
		ydl_opts = {
			**base_opts,
			'format': 'bestaudio/best',
			'postprocessors': [
				{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
				{'key': 'FFmpegMetadata'}
			]
		}

	try:
		# Завантаження
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([search_query]))

		matches = glob.glob(os.path.join(TMP_DIR, f"{video_id}.*"))
		if not matches:
			await status_msg.edit_text("😕 Не вдалося знайти файл. Перевір посилання або запит.")
			await asyncio.sleep(5)
			await status_msg.delete()
			return

		output_file = matches[0]
		if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
			await status_msg.edit_text("😕 Файл не завантажився або пошкоджений. Спробуй інший.")
			await asyncio.sleep(5)
			await status_msg.delete()
			return

		if os.path.getsize(output_file) > MAX_FILE_SIZE:
			await status_msg.edit_text(
				f"📁 Файл завеликий (> {MAX_FILE_SIZE / (1024 * 1024):.0f} МБ). Спробуй інший."
			)
			await asyncio.sleep(3)
			await status_msg.delete()
		else:
			input_file = FSInputFile(output_file)
			await bot.send_document(query.message.chat.id, input_file)
			await status_msg.delete()

	except yt_dlp.utils.DownloadError as e:
		error_text = str(e)
		logging.error(f"Yt-dlp DownloadError: {error_text}", exc_info=True)
		if "Unsupported URL" in error_text:
			await status_msg.edit_text("⚠️ Це посилання не підтримується (можливо, фото/сторіс, прямий ефір, або приватний контент).")
		elif "ERROR: Private video" in error_text:
			await status_msg.edit_text("⚠️ Це приватне відео і його неможливо завантажити.")
		elif "ERROR: This video is unavailable" in error_text:
			await status_msg.edit_text("⚠️ Це відео недоступне.")
		else:
			await status_msg.edit_text("⚠️ Помилка завантаження. Спробуй інше посилання або пізніше.")
		await asyncio.sleep(5)
		await status_msg.delete()

	except Exception as e:
		logging.error(f"Невідома помилка під час завантаження: {e}", exc_info=True)
		await status_msg.edit_text("⚠️ Невідома помилка. Спробуй пізніше або інше посилання.")
		await asyncio.sleep(5)
		await status_msg.delete()

	finally:
		# Очистити тимчасові файли
		for file in glob.glob(os.path.join(TMP_DIR, f"{video_id}.*")):
			try:
				os.remove(file)
			except Exception as e:
				logging.warning(f"Не вдалося видалити тимчасовий файл {file}: {e}")
