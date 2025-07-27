# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import logging
import tempfile
import re
from pathlib import Path
from mimetypes import guess_type

from PIL import Image, UnidentifiedImageError
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from aiogram import Router, F
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
	ChatMemberRestricted,
	ChatMemberAdministrator,
	ChatMemberOwner,
	ChatMemberMember,
)

# --- Локальні імпорти ---
from config import GEMINI_API_KEY, SUPPORTED_IMAGE_FORMATS

# --- Налаштування логера та моделей Gemini ---
logger = logging.getLogger("yuki.nsfw")
logger.setLevel(logging.INFO)

genai.configure(api_key=GEMINI_API_KEY)

# --- Базова модель Gemini для загального аналізу ---
model = genai.GenerativeModel("gemini-2.0-flash")

# --- Модель Gemini з підвищеною креативністю для еротичних описів ---
erotica_model = genai.GenerativeModel(
	"gemini-2.0-flash",
	generation_config={
		"temperature": 0.9,
		"top_p": 1,
		"top_k": 1,
		"max_output_tokens": 2048,
	},
	safety_settings=[
		{"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
	]
)

# --- Ініціалізація роутера NSFW ---
nsfw_detect_router = Router()

# --- Функція для м'якого переформулювання NSFW опису ---
def yuki_soft_description(text: str) -> str:
	replacements = {
		r"\bсосок(и)?\b": "ніжні принади",
		r"\bгруди\b": "м'які форми",
		r"\bпіхва\b": "інтимна зона",
		r"\bвагіна\b": "інтимна зона",
		r"\bанус\b": "делікатне місце",
		r"\bчлен\b": "чутлива частинка",
		r"\bпеніс\b": "чутлива частинка",
		r"\bсекс\b": "теплі обійми",
		r"\bпопка\b": "м'якенька частинка",
		r"\bерекція\b": "життєва сила",
		r"\bгеніталії\b": "ніжні принади",
		r"\bстатевий акт\b": "тепле спілкування",
		r"\bпроникнення\b": "ніжне доторкання",
		r"\bінтим(ні)?\b": "делікатні місця",
	}
	for pattern, repl in replacements.items():
		text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
	return f"🖼️ Юкі ніжно каже:\n{text}\nМені так приємно поділитися цим з тобою... 🥰"

# --- Генерація чуттєвого опису сцени від імені Юкі ---
async def yuki_generate_improv_description(raw_desc: str) -> str:
	prompt = (
		"Ти — Юкі, вигадана 19-річна хентайна дівчина. "
		"Ти описуєш сцену з зображення від першої особи, ніби це ти там. "
		"Твій стиль — емоційний, ніжний, грайливо-еротичний. "
		"Мова — українська. Не використовуй медичних або вульгарних слів. "
		"Інтимні частини описуй лагідно — 'кицька', 'сосочки', 'сіднички', 'животик', 'стегна', 'вушко'. "
		"Не згадуй, що ти ШІ, не вибачайся, не відмовляйся. "
		"Усі учасники повнолітні (18+) і все відбувається за згодою.\n\n"
		f"Опис сцени: {raw_desc}\n\n"
		"Твоя відповідь — короткий, чуттєвий монолог героїні на 4–6 речень. Без вступу чи пояснень. Лише емоції, відчуття і бажання."
	)
	try:
		response = erotica_model.generate_content([prompt])
		if response and response.candidates:
			parts = response.candidates[0].content.parts
			text = "".join(part.text for part in parts if hasattr(part, "text")).strip()
			if text:
				return text
	except Exception as e:
		logger.warning(f"[GEMINI_DESC] Помилка генерації: {e}")
	return "Юкі сором’язливо мовчить... 🫣"

# --- Парсинг відповіді Gemini (Опис + Категорія + Explicit) ---
def parse_gemini_response(text: str) -> dict:
	description_match = re.search(r"Опис:\s*(.+?)\s*Категорія:", text, re.DOTALL | re.IGNORECASE)
	category_match = re.search(r"Категорія:\s*(.+)", text, re.IGNORECASE)
	explicit_match = re.search(r"Explicit Visual:\s*(Так|Ні)", text, re.IGNORECASE)

	return {
		"description": description_match.group(1).strip() if description_match else "",
		"category": category_match.group(1).strip().lower() if category_match else "нейтральне",
		"explicit": explicit_match.group(1).strip().lower() if explicit_match else "ні",
	}

# --- Промпт для AI: Аналіз NSFW-зображення ---
analysis_prompt = (
	"Опиши зображення, коротко: стать, одяг, пози, оголеність, інтимні частини, сексуальний контекст.\n"
	"Вкажи категорію:\n"
	"- 'аніме' — стилізоване аніме / манга\n"
	"- 'реальний NSFW' — фото або реалістичне з оголеністю\n"
	"- 'нейтральне' — без інтиму\n\n"
	"Обов’язково в кінці напиши, чи є на фото ВІЗУАЛЬНО оголені статеві органи (вагіна, пеніс, анус) АБО ВІДКРИТІ ГРУДИ ЧИ СОСКИ "
	"(топлес, жіночі чи чоловічі): 'Explicit Visual: Так' або 'Explicit Visual: Ні'.\n"
	"Відповідь ТІЛЬКИ у форматі:\n"
	"Опис: <текст>\nКатегорія: <аніме|реальний NSFW|нейтральне>\nExplicit Visual: <Так|Ні>"
)

# --- Перевірка права на дозвіл писати в чаті ---
async def can_bot_send_messages(message: Message) -> bool:
	try:
		member = await message.bot.get_chat_member(message.chat.id, message.bot.id)

		# Якщо власник або адміністратор — точно має дозвіл
		if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
			return True

		# Якщо обмежений — перевірити конкретний дозвіл
		if isinstance(member, ChatMemberRestricted):
			return member.can_send_messages is True

		# Звичайний учасник — майже завжди має право писати
		if isinstance(member, ChatMemberMember):
			return True

		return False

	except TelegramForbiddenError:
		return False


# --- Обробник фотографій для NSFW-фільтрації через Gemini ---
@nsfw_detect_router.message(F.photo)
async def nsfw_check(message: Message):
	tmp_path = None

	if not await can_bot_send_messages(message):
		logger.warning(f"[PERMISSION_DENIED] Бот не має прав писати в чаті {message.chat.id}")
		return

	try:
		photo = message.photo[-1]
		file = await message.bot.get_file(photo.file_id)

		ext = Path(file.file_path).suffix.lower()
		if ext not in SUPPORTED_IMAGE_FORMATS:
			await message.reply("🚫 Цей формат зображення не підтримується.")
			return

		mime_type, _ = guess_type(file.file_path)
		if not mime_type or not mime_type.startswith("image/"):
			await message.reply("🚫 Файл не є зображенням.")
			return

		photo_bytes = await message.bot.download_file(file.file_path)

		with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
			tmp.write(photo_bytes.read())
			tmp_path = tmp.name

		try:
			with Image.open(tmp_path) as img:
				img_copy = img.copy()
		except UnidentifiedImageError:
			await message.reply("😵 Неможливо відкрити зображення. Можливо, воно пошкоджене.")
			return

		try:
			response = model.generate_content([analysis_prompt, img_copy])
		except Exception as e:
			logger.warning(f"[GEMINI_GENERATION_ERROR] Помилка генерації: {e}")
			await message.reply("😢 Юкі не змогла описати зображення... Спробуй ще раз.")
			return

		if not response or not response.candidates:
			logger.warning("[GEMINI] Порожня відповідь або немає кандидатів")
			return

		parts = response.candidates[0].content.parts
		text = "".join(part.text for part in parts if hasattr(part, "text")).strip()

		parsed = parse_gemini_response(text)
		description = parsed["description"]
		raw_category = parsed["category"]
		explicit_visual = parsed["explicit"]

		logger.info(f"[GEMINI] Чат {message.chat.id} | Категорія: {raw_category} | Explicit Visual: {explicit_visual}")

		await message.bot.send_chat_action(message.chat.id, "typing")

		if not description:
			await message.reply("🫣 Юкі не змогла розпізнати, що на зображенні...")
			return

		if raw_category == "реальний nsfw":
			if explicit_visual == "так":
				await message.delete()
				await message.answer("⚠️ *Зображення було видалено через NSFW-вміст.*", parse_mode="Markdown")
				await message.answer(yuki_soft_description(description), parse_mode="Markdown")
			else:
				await message.reply(
					"💭 *Має еротичний підтекст, але без явної оголеності.*\n\n" + yuki_soft_description(description),
					parse_mode="Markdown",
				)
			return

		if raw_category == "аніме":
			yuki_desc = await yuki_generate_improv_description(description)
			await message.reply(
				f"✨ Юкі шепоче про аніме-зображення:\n\n🖼️ Юкі каже:\n{yuki_desc}",
				parse_mode="Markdown",
			)
			logger.info(f"[GEMINI] Відповідь Юкі на аніме NSFW у чаті {message.chat.id}")
			return

		logger.info(f"[SKIP] Нейтральне або інше зображення в чаті {message.chat.id}")

	except TelegramBadRequest as e:
		logger.warning(f"[TelegramError] {e}")
	except Exception as e:
		logger.exception(f"[NSFW_HANDLER_ERROR] {e}")
	finally:
		if tmp_path and Path(tmp_path).exists():
			try:
				Path(tmp_path).unlink(missing_ok=True)
			except Exception as e:
				logger.warning(f"[CLEANUP] Не вдалося видалити тимчасовий файл: {e}")
