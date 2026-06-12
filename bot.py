import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ErrorEvent

from config import BOT_TOKEN
from database import setup_indexes
from handlers import auth, menu, upload, queue, nexus_key, admin
from handlers.timeout import SessionTimeoutMiddleware
from utils.queue_manager import queue_processor, set_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    set_bot(bot)

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # ── Global error handler ──────────────────────────────────────────────
    @dp.errors()
    async def global_error_handler(event: ErrorEvent) -> bool:
        exc = event.exception
        if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc):
            # User tapped Refresh / same button twice — content unchanged, harmless
            return True
        logger.error(f"Unhandled exception: {exc}", exc_info=exc)
        return False

    dp.message.middleware(SessionTimeoutMiddleware())
    dp.callback_query.middleware(SessionTimeoutMiddleware())

    dp.include_router(auth.router)
    dp.include_router(admin.router)
    dp.include_router(menu.router)
    dp.include_router(nexus_key.router)
    dp.include_router(upload.router)
    dp.include_router(queue.router)

    await setup_indexes()

    asyncio.create_task(queue_processor())

    logger.info("Sakura bot starting~ ehehe~")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
