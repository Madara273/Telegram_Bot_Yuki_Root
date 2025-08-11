# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import time
import asyncio
import contextlib
import logging
import aiohttp
import config
import signal

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramNetworkError, RestartingTelegram
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile, InputMediaPhoto
from aiogram.exceptions import TelegramRetryAfter

from magic import magic_router
from waifu import waifu_router
from ai_router import yuki_router, init_db, DB_NAME
from qdl import qdl_router
from gen_router import gen_router

# --- Імпортувати з config ---
BOT_TOKEN = config.BOT_TOKEN

bot = Bot(
	token=BOT_TOKEN,
	default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
# --- Диспетчери та підключені роутери ---
dp = Dispatcher(storage=MemoryStorage())
main_router = Router()

dp.include_router(gen_router)
dp.include_router(main_router)
dp.include_router(magic_router)
dp.include_router(qdl_router)
dp.include_router(waifu_router)
dp.include_router(yuki_router)

# --- Логування ---
logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# --- Завантаження банера ---
with open("banner/yuki_banner.png", "rb") as image_file:
	banner = BufferedInputFile(image_file.read(), filename="yuki_banner.png")

# --- Обробник /start ---
@main_router.message(Command("start"))
async def cmd_start(message: Message):
	try:
		await message.delete()
	except (TelegramBadRequest, TelegramForbiddenError) as e:
		logger.debug(f"Не вдалося видалити /start від {message.from_user.id}: {e}")

	text = (
		"🔧 <b>Yuki-інструменти:</b>\n"
		"• /magisk - Остання версія Magisk\n"
		"• /ksu_next - KernelSU-Next\n"
		"• /modules - Magisk-модулі\n\n"
		"🪄 <b>Yuki-помічник:</b>\n"
		"• /get_yuki - Yuki-асистент\n"
		"• /reset_yuki - Скинути історію чату\n"
		"• /gen - Генерувати зображення\n"
		"• /sleep - Завершити сесію Yuki\n\n"
		"🎞️ <b>Yuki-медіа:</b>\n"
		"• /qdl - Завантаження з YouTube, TikTok\n\n"
		"📡 <b>Yuki-стан:</b>\n"
		"• /ping - перевірити зв'язок\n\n"
		"✅ Завжди актуальні версії!"
	)

	try:
		await message.answer_photo(
			photo=banner,
			caption=text,
			parse_mode=ParseMode.HTML
		)
	except TelegramBadRequest as e:
		if "not enough rights" in str(e):
			logger.warning("Боту не вистачає прав для відправки медіа!")
	except Exception as e:
		logger.error(f"Помилка відправки банера: {e}")

		try:
			await message.answer(text, parse_mode=ParseMode.HTML)
		except TelegramBadRequest as e:
			if "not enough rights to send text messages" in str(e):
				logger.warning("Ой, здається, я не маю прав писати в цей чат, звернись до адміна")
		except Exception as ex:
			logger.error(f"Невідома помилка при резервній відправці тексту: {ex}")

# --- Обробка команди Ping ---
@main_router.message(Command("ping"))
async def ping_handler(message: Message):
	try:
		await message.delete()
	except TelegramBadRequest as e:
		if "message can't be deleted" in str(e):
			logger.warning("Ой, не можу видалити повідомлення — воно вже видалене або нема прав")
		else:
			logger.error(f"Помилка при видаленні повідомлення: {e}")
	except TelegramForbiddenError:
		logger.warning("Нема прав на видалення повідомлення")

	start = time.perf_counter()

	try:
		sent_msg = await message.answer("☕ Перевіряю зв'язок…")
	except TelegramRetryAfter as e:
		retry_after = e.retry_after or 10
		logger.warning(f"Flood control 🫣 — чекаю {retry_after} сек...")
		await asyncio.sleep(retry_after)
		sent_msg = await message.answer("☕ Повторна спроба після flood control…")

	end = time.perf_counter()
	ping_ms = round((end - start) * 1000, 2)

	await sent_msg.edit_text(
		f"✅ Я працюю!\n📶 Пінг: <b>{ping_ms} мс</b>",
		parse_mode="HTML"
	)

# --- AIOHTTP TCP/NAT/BBR оптимізована сесія ---
connector: aiohttp.TCPConnector | None = None
session: aiohttp.ClientSession | None = None

# --- Реалізувати захист від нестабільних мереж ---
async def run_polling():
	logger.info(f"Спроба ініціалізації бази даних: {DB_NAME}")
	try:
		await init_db()
		logger.info("База даних ініціалізована/перевірена успішно.")
	except Exception as e:
		logger.critical(f"КРИТИЧНА ПОМИЛКА: Не вдалося ініціалізувати базу даних. Бот не зможе працювати без неї. Деталі: {e}")
		return

	while True:
		try:
			logger.info("Запуск бота…")
			await dp.start_polling(bot)
			logger.info("Polling завершено без помилок.")
			break
		except aiohttp.ServerDisconnectedError as disconn:
			logger.warning(f"[Мережа] Сервер Telegram розірвав з’єднання: {disconn}. Повтор через 10 сек...")
			await asyncio.sleep(10)
		except (aiohttp.ClientConnectorError, TelegramNetworkError, asyncio.TimeoutError) as net_err:
			logger.warning(f"[Мережа] Втрачено з'єднання: {net_err}. Повтор через 10 сек...")
			await asyncio.sleep(10)
		except RestartingTelegram as restart:
			logger.info(f"[Telegram] Перезапуск: {restart}")
			await asyncio.sleep(5)
		except asyncio.CancelledError:
			logger.info("Отримано сигнал скасування. Завершуємо polling.")
			break
		except Exception as e:
			logger.exception(f"[Фатальна помилка] {e}")
			await asyncio.sleep(5)

# --- Реалізувати правильне завершення роботи ---
async def shutdown(polling_task):
	logger.info("Завершення: зупинити polling…")
	polling_task.cancel()
	with contextlib.suppress(asyncio.CancelledError):
		await polling_task

	if session and not session.closed:
		await session.close()
		logger.info("Сесію aiohttp закрито.")

	if connector and not connector.closed:
		connector.close()
		logger.info("Конектор aiohttp закрито.")

	try:
		await bot.session.close()
		logger.info("Сесію бота закрито.")
	except Exception as e:
		logger.warning(f"⚠ Не вдалося закрити сесію бота: {e}")

	logger.info("Завершено коректно.")

# --- Запуск і обробка сигналів завершення ---
async def main():
	global connector, session

	# --- AIOHTTP TCP/NAT/BBR оптимізована сесія (ініціалізація) ---
	connector = aiohttp.TCPConnector(
		limit=100,
		ttl_dns_cache=600,
		force_close=False,
		keepalive_timeout=30
	)
	session = aiohttp.ClientSession(connector=connector)

	loop = asyncio.get_running_loop()
	polling_task = asyncio.create_task(run_polling())

	for sig in (signal.SIGINT, signal.SIGTERM):
		loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(polling_task)))

	try:
		await polling_task
	finally:
		if not polling_task.cancelled():
			await shutdown(polling_task)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		logger.info("KeyboardInterrupt — вихід.")
