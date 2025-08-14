# MIT License
# Copyright (c) 2025 Madara273 <ravenhoxs@gmail.com>

# --- Імпорти ---
import aiohttp
import asyncio

MAX_RETRIES = 3
RETRY_DELAY = 1

async def fetch_image(url):
	for attempt in range(MAX_RETRIES):
		try:
			async with aiohttp.ClientSession() as session:
				async with session.get(url, timeout=10) as response:
					if response.status != 200:
						await asyncio.sleep(RETRY_DELAY)
						continue
					try:
						data = await response.json()
						return data.get('url')
					except aiohttp.ContentTypeError:
						await asyncio.sleep(RETRY_DELAY)
						continue
		except aiohttp.ClientError:
			await asyncio.sleep(RETRY_DELAY)
			continue
	return None

async def waifu_sfw():
	return await fetch_image('https://api.waifu.pics/sfw/waifu')

async def waifu_nsfw():
	return await fetch_image('https://api.waifu.pics/nsfw/waifu')
