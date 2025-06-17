# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import os
import re
import html
import logging
import asyncio
import requests
import markdown2
import time
import sys

from aiogram import Bot
from aiogram import Router, types, F
from aiogram.types import (
	Message,
	CallbackQuery,
	FSInputFile,
	InlineKeyboardButton,
	InlineKeyboardMarkup,
)
from aiogram.filters import Command

# --- Конфігурація ---
MODULES_PER_PAGE = 5
JSON_URL = "https://raw.githubusercontent.com/Magisk-Modules-Alt-Repo/json/main/modules.json"
magic_cache = {}

# --- Ініціалізація magic router ---
magic_router = Router()

logger = logging.getLogger(__name__)

# --- Функція завантаження останнього релізу з GitHub ---
def download_latest_release(repo: str, asset_keyword: str):
	url = f"https://api.github.com/repos/{repo}/releases/latest"
	headers = {"User-Agent": "Mozilla/5.0"}

	try:
		resp = requests.get(url, headers=headers, timeout=10)
		resp.raise_for_status()
		data = resp.json()

		tag_name = data.get('tag_name')
		assets = data.get('assets', [])

		if not assets:
			logging.warning("Реліз знайдено, але немає жодного активу для завантаження.")
			return None, tag_name

		for asset in assets:
			if asset_keyword in asset['name']:
				download_url = asset['browser_download_url']
				filename = asset['name']

				with requests.get(download_url, stream=True, timeout=30) as r:
					r.raise_for_status()
					with open(filename, 'wb') as f:
						for chunk in r.iter_content(8192):
							f.write(chunk)

				return filename, tag_name

		logging.warning("Не знайдено релізу, який відповідає ключовому слову.")
	except requests.exceptions.RequestException as e:
		message = f"⚠️ Помилка HTTP-запиту: {e}"
		sys.stderr.write(message + "\r")
		time.sleep(5)
		sys.stderr.write(" " * len(message) + "\r")
		logging.error(message)
	except (IOError, OSError) as e:
		message = f"⚠️ Помилка запису у файл: {e}"
		sys.stderr.write(message + "\r")
		time.sleep(5)
		sys.stderr.write(" " * len(message) + "\r")
		logging.error(message)
	except Exception as e:
		message = f"⚠️ Невідома помилка: {e}"
		sys.stderr.write(message + "\r")
		time.sleep(5)
		sys.stderr.write(" " * len(message) + "\r")
		logging.error(message)

	return None, None

# --- Команда /magisk — завантаження останнього Magisk ---
@magic_router.message(Command("magisk"))
async def cmd_magisk(message: Message):
	cache = magic_cache.get(message.chat.id)
	if cache and "auto_clear_task" in cache and cache["auto_clear_task"]:
		cache["auto_clear_task"].cancel()
		cache["auto_clear_task"] = None

	try:
		await message.delete()
		logging.info(f"✅ Видалено повідомлення з командою /magisk у чаті {message.chat.id}")
	except Exception as e:
		logging.warning(f"❌ Не вдалося видалити повідомлення /magisk: {e}")

	# Емуляція завантаження
	loading_msg = await message.answer("Завантаження останнього Magisk...")
	await asyncio.sleep(2)

	file_path, version = download_latest_release("topjohnwu/Magisk", ".apk")
	if file_path:
		found_msg = await message.answer(f"Magisk {version} знайдено. Надсилаю файл...")
		await asyncio.sleep(1.5)

		try:
			await message.bot.send_document(
				message.chat.id,
				document=FSInputFile(file_path),
				caption=f"Magisk {version}"
			)
		finally:
			try:
				os.remove(file_path)
			except OSError:
				pass

		for msg in [loading_msg, found_msg]:
			try:
				await msg.delete()
			except Exception as e:
				logging.warning(f"❌ Не вдалося видалити службове повідомлення: {e}")
	else:
		try:
			await loading_msg.delete()
		except:
			pass
		await message.answer("❌ Не знайдено релізу Magisk або сталася помилка.")

# --- Команда /ksu_next — завантаження останнього KernelSU-Next ---
@magic_router.message(Command("ksu_next"))
async def cmd_ksu_next(message: Message):
	cache = magic_cache.get(message.chat.id)
	if cache and "auto_clear_task" in cache and cache["auto_clear_task"]:
		cache["auto_clear_task"].cancel()
		cache["auto_clear_task"] = None

	try:
		await message.delete()
		logging.info(f"✅ Видалено повідомлення з командою /ksu_next у чаті {message.chat.id}")
	except Exception as e:
		logging.warning(f"❌ Не вдалося видалити повідомлення /ksu_next: {e}")

	loading_msg = await message.answer("Завантаження останнього KernelSU-Next...")
	await asyncio.sleep(2)

	file_path, version = download_latest_release("KernelSU-Next/KernelSU-Next", ".apk")
	if file_path:
		found_msg = await message.answer(f"KernelSU-Next {version} знайдено. Надсилаю файл...")
		await asyncio.sleep(1.5)

		try:
			await message.bot.send_document(
				message.chat.id,
				document=FSInputFile(file_path),
				caption=f"KernelSU-Next {version}"
			)
		finally:
			try:
				os.remove(file_path)
			except OSError:
				pass

		for msg in [loading_msg, found_msg]:
			try:
				await msg.delete()
			except Exception as e:
				logging.warning(f"❌ Не вдалося видалити службове повідомлення: {e}")
	else:
		try:
			await loading_msg.delete()
		except:
			pass
		await message.answer("❌ Не знайдено релізу KernelSU-Next або сталася помилка.")

# --- Команда /modules — показ списку модулів ---
@magic_router.message(Command("modules"))
async def cmd_modules(message: Message):
	cache = magic_cache.get(message.chat.id)
	if cache and "auto_clear_task" in cache and cache["auto_clear_task"]:
		cache["auto_clear_task"].cancel()
		cache["auto_clear_task"] = None

	try:
		await message.delete()
		logging.info(f"✅ Видалено повідомлення з командою /modules у чаті {message.chat.id}")
	except Exception as e:
		logging.warning(f"❌ Не вдалося видалити повідомлення /modules у чаті {message.chat.id}: {e}")

	await show_all_modules(message)

# --- Callback: показати всі модулі ---
@magic_router.callback_query(F.data == "show_all")
async def cb_show_all(callback: CallbackQuery):
	await show_all_modules(callback.message)

# --- Функція для автоочистки повідомлення З КЛАВІАТУРОЮ (тобто видалення його) ---
async def auto_remove_keyboard_message_task(chat_id: int, msg_id: int, bot: Bot, delay: int = 15):
	await asyncio.sleep(delay)
	cache = magic_cache.get(chat_id)

	if cache and cache.get("last_keyboard_msg_id") == msg_id:
		try:
			await bot.delete_message(chat_id=chat_id, message_id=msg_id)
			logging.info(f"Автоматично видалено повідомлення з клавіатурою {msg_id} у чаті {chat_id}")
			cache["last_keyboard_msg_id"] = None
			cache["auto_clear_task"] = None
		except Exception as e:
			logging.warning(f"Автовидалення повідомлення з клавіатурою {msg_id} не вдалося у чаті {chat_id}: {e}")

# --- Допоміжна функція для показу всіх модулів ---
async def show_all_modules(message: types.Message, page: int = 0):
	current_keyboard_msg_id = None

	try:
		resp = requests.get(JSON_URL)
		resp.raise_for_status()
		data = resp.json()
		modules = data.get("modules", [])
		if not modules:
			await message.answer("Немає модулів для показу.")
			return None

		modules.sort(key=lambda x: x.get('stars', 0), reverse=True)

		start = page * MODULES_PER_PAGE
		end = start + MODULES_PER_PAGE
		current_page_modules = modules[start:end]

		keyboard = [
			[InlineKeyboardButton(text=f"{mod['id']} ({mod['stars']}★)", callback_data=f"mod_{mod['id']}")]
			for mod in current_page_modules
		]

		nav_buttons = []
		if page > 0:
			nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data="prev_page"))
		if end < len(modules):
			nav_buttons.append(InlineKeyboardButton(text="▶️ Далі", callback_data="next_page"))

		if nav_buttons:
			keyboard.append(nav_buttons)

		page_text = f"Сторінка {page + 1} з {((len(modules) - 1) // MODULES_PER_PAGE) + 1}"

		cache = magic_cache.get(message.chat.id)
		if cache:
			last_keyboard_msg_id_from_cache = cache.get("last_keyboard_msg_id")

			if last_keyboard_msg_id_from_cache:
				try:
					sent_message = await message.bot.edit_message_text(
						chat_id=message.chat.id,
						message_id=last_keyboard_msg_id_from_cache,
						text=page_text,
						reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
					)
					current_keyboard_msg_id = sent_message.message_id
					magic_cache[message.chat.id]["page"] = page
					magic_cache[message.chat.id]["modules"] = modules
					magic_cache[message.chat.id]["last_keyboard_msg_id"] = current_keyboard_msg_id

					# Скасувати попередній таймер і запустити новий для відредагованого повідомлення
					if "auto_clear_task" in cache and cache["auto_clear_task"]:
						cache["auto_clear_task"].cancel()
						logging.debug(f"Скасовано попередній таймер для чату {message.chat.id}")
					cache["auto_clear_task"] = asyncio.create_task(
						auto_remove_keyboard_message_task(message.chat.id, current_keyboard_msg_id, message.bot)
					)
					return current_keyboard_msg_id

				except Exception as e:
					logging.warning(f"Не вдалося відредагувати повідомлення (ID: {last_keyboard_msg_id_from_cache}): {e}")
					# Якщо повідомлення не можна відредагувати, видалити його з кешу і надіслати нове.
					try:
						await message.bot.delete_message(chat_id=message.chat.id, message_id=last_keyboard_msg_id_from_cache)
					except Exception:
						pass
					magic_cache[message.chat.id]["last_keyboard_msg_id"] = None

		sent_message = await message.answer(
			page_text,
			reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
		)
		current_keyboard_msg_id = sent_message.message_id

		magic_cache[message.chat.id] = {
			"modules": modules,
			"page": page,
			"last_keyboard_msg_id": current_keyboard_msg_id
		}

		# Скасувати попередній таймер і запускаємо новий для щойно відправленого повідомлення
		if cache and "auto_clear_task" in cache and cache["auto_clear_task"]:
			cache["auto_clear_task"].cancel()
			logging.debug(f"Скасовано попередній таймер для чату {message.chat.id}")
		magic_cache[message.chat.id]["auto_clear_task"] = asyncio.create_task(
			auto_remove_keyboard_message_task(message.chat.id, current_keyboard_msg_id, message.bot)
		)

		return current_keyboard_msg_id

	except Exception as e:
		logging.error(f"Помилка в show_all_modules: {e}")
		await message.answer(f"Помилка: {e}")
		return None

# --- Команда /modules — показ списку модулів ---
@magic_router.message(Command("modules"))
async def cmd_modules(message: Message):
	cache = magic_cache.get(message.chat.id)
	if cache and "auto_clear_task" in cache and cache["auto_clear_task"]:
		cache["auto_clear_task"].cancel()
		cache["auto_clear_task"] = None

	await show_all_modules(message)

# --- Callback: показати всі модулі ---
@magic_router.callback_query(F.data == "show_all")
async def cb_show_all(callback: CallbackQuery):
	cache = magic_cache.get(callback.message.chat.id)
	if cache and "auto_clear_task" in cache and cache["auto_clear_task"]:
		cache["auto_clear_task"].cancel()
		cache["auto_clear_task"] = None

	await callback.answer()
	await show_all_modules(callback.message)

# --- Callback: пагінація — наступна або попередня сторінка ---
@magic_router.callback_query(F.data.in_({"next_page", "prev_page"}))
async def cb_pagination(callback: CallbackQuery):
	cache = magic_cache.get(callback.message.chat.id)
	if not cache:
		await callback.message.answer("Сесія недоступна або застаріла.")
		return

	if "auto_clear_task" in cache and cache["auto_clear_task"]:
		cache["auto_clear_task"].cancel()
		cache["auto_clear_task"] = None

	page = cache.get("page", 0)
	if callback.data == "next_page":
		page += 1
	elif callback.data == "prev_page" and page > 0:
		page -= 1
	cache["page"] = page

	await show_all_modules(callback.message, page=page)
	await callback.answer()

# --- Callback: показ детальної інформації про модуль ---
@magic_router.callback_query(lambda c: c.data.startswith("mod_"))
async def cb_module_detail(callback: CallbackQuery):
	cache = magic_cache.get(callback.message.chat.id)
	if not cache:
		await callback.message.answer("Сесія недоступна або застаріла.")
		await callback.answer()
		return

	# Скасувати таймер для повідомлення зі сторінками, оскільки ми збираємося його видалити
	if "auto_clear_task" in cache and cache["auto_clear_task"]:
		cache["auto_clear_task"].cancel()
		cache["auto_clear_task"] = None
		logging.debug(f"Скасовано таймер для повідомлення зі сторінками у чаті {callback.message.chat.id}")

	modules = cache.get("modules", [])
	mod_id = callback.data.replace("mod_", "")
	mod = next((m for m in modules if m['id'] == mod_id), None)
	if not mod:
		await callback.message.answer("Модуль не знайдено.")
		await callback.answer()
		return

	readme_summary = ""
	if "notes_url" in mod:
		try:
			readme_resp = requests.get(mod["notes_url"])
			readme_resp.raise_for_status()
			readme_text = readme_resp.text.strip()
			readme_text = re.sub(r'!.*?.*?', '', readme_text)
			readme_text = re.sub(r'^#+\s*.*$', '', readme_text, flags=re.MULTILINE)
			readme_text = re.sub(r'(`{1,3})(.*?)\1', r'\2', readme_text, flags=re.DOTALL)
			readme_text = re.sub(r'\*\*(.*?)\*\*', r'\1', readme_text)
			readme_text = re.sub(r'\*(.*?)\*', r'\1', readme_text)

			html_text = markdown2.markdown(readme_text)
			clean_text = re.sub(r'<[^>]+>', '', html_text)
			clean_text = html.unescape(clean_text)

			blocks = [b.strip() for b in clean_text.split('\n') if b.strip()]
			for block in blocks:
				if len(block) > 30 and not block.startswith('http'):
					readme_summary = block
					break

			if not readme_summary:
				readme_summary = "Опис README відсутній або нечитабельний."
			elif len(readme_summary) > 1000:
				readme_summary = readme_summary[:1000] + "..."
		except Exception as e:
			logging.warning(f"Помилка при отриманні README для {mod['id']}: {e}")
			readme_summary = "Опис README відсутній або сталася помилка."

	await callback.message.answer(
		f"<b>{mod['id']}</b>\n\n{html.escape(readme_summary)}",
		parse_mode="HTML"
	)

	# Очистка inline-клавіатури (одразу) - це клавіатура, на яку натиснув користувач
	try:
		await callback.bot.edit_message_reply_markup(
			chat_id=callback.message.chat.id,
			message_id=callback.message.message_id,
			reply_markup=None
		)
		logging.info(f"Клавіатуру повідомлення {callback.message.message_id} очищено негайно.")
	except Exception as e:
		logging.warning(f"Не вдалося очистити inline-клавіатуру: {e}")

	# Видалення попереднього повідомлення "Сторінка N з M" разом із клавіатурою
	last_keyboard_msg_id = cache.get("last_keyboard_msg_id")
	if last_keyboard_msg_id:
		try:
			await callback.bot.delete_message(chat_id=callback.message.chat.id, message_id=last_keyboard_msg_id)
			logging.info(f"Видалено попереднє повідомлення 'Сторінка N з M': {last_keyboard_msg_id}")
		except Exception as e:
			logging.warning(f"Не вдалося видалити попереднє повідомлення 'Сторінка N з M': {e}")
	cache["last_keyboard_msg_id"] = None # Скинути, оскільки повідомлення вже видалено

	# Завантаження ZIP
	try:
		zip_resp = requests.get(mod['zip_url'], stream=True)
		zip_resp.raise_for_status()
		MAX_SIZE = 50 * 1024 * 1024
		zip_name = f"{mod['id']}.zip"
		total_size = 0

		if 'content-length' in zip_resp.headers:
			total_size = int(zip_resp.headers['content-length'])
			if total_size > MAX_SIZE:
				await callback.message.answer(
					f"Файл модуля {mod['id']} перевищує ліміт (50 МБ).\nЗавантажити вручну: {mod['zip_url']}"
				)
				await callback.answer()
				return

		with open(zip_name, "wb") as f:
			for chunk in zip_resp.iter_content(8192):
				if chunk:
					f.write(chunk)
					total_size += len(chunk)
					if total_size > MAX_SIZE:
						f.close()
						os.remove(zip_name)
						await callback.message.answer(
							f"Файл модуля {mod['id']} перевищує ліміт (50 МБ).\nЗавантажити вручну: {mod['zip_url']}"
						)
						await callback.answer()
						return

		# ЦЕ ПОВІДОМЛЕННЯ З ZIP-ФАЙЛОМ НЕ БУДЕ АВТОМАТИЧНО ВИДАЛЯТИСЯ З ЦІЄЮ ЛОГІКОЮ
		await callback.bot.send_document(
			callback.message.chat.id,
			FSInputFile(zip_name),
			caption=f"Модуль: {mod['id']}"
		)
		os.remove(zip_name)

	except Exception as e:
		logging.error(f"Помилка при завантаженні модуля {mod['id']}: {e}")
		await callback.message.answer(f"Не вдалося завантажити модуль {mod['id']}: {e}")

	await callback.answer()
