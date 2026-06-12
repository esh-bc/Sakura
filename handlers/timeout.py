import logging
import asyncio
from datetime import timezone

from aiogram import Router, BaseMiddleware
from aiogram.types import Message, TelegramObject
from aiogram.fsm.context import FSMContext

from utils.helpers import now_utc
from config import SESSION_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class SessionTimeoutMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        state: FSMContext = data.get("state")
        if state:
            current = await state.get_state()
            if current:
                fsm_data = await state.get_data()
                last_activity = fsm_data.get("last_activity")
                if last_activity:
                    now = now_utc().timestamp()
                    if now - last_activity > SESSION_TIMEOUT_SECONDS:
                        await state.clear()
                        if isinstance(event, Message):
                            try:
                                await event.answer(
                                    "mou~ You were gone too long, master~ ◇\n"
                                    "I had to cancel our session~ ehehe~\n"
                                    "◈ Start fresh whenever you're ready~ ✦\n\n"
                                    "Use /start to get back to the menu~"
                                )
                            except Exception as e:
                                logger.error(f"Timeout message error: {e}")
                        return

                await state.update_data(last_activity=now_utc().timestamp())

        return await handler(event, data)
