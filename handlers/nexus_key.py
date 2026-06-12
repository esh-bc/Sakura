import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import users_col
from utils.helpers import now_utc, format_expiry
from keyboards import main_menu_kb, nexus_back_kb

router = Router()
logger = logging.getLogger(__name__)


class NexusKeyStates(StatesGroup):
    waiting_for_key = State()


@router.callback_query(F.data == "nexus_key")
async def cb_nexus_key(callback: CallbackQuery, state: FSMContext):
    user = await users_col.find_one({"telegram_id": callback.from_user.id})
    if not user:
        await callback.answer("mou~ Auth first, master~ ◈", show_alert=True)
        return

    current = user.get("nexus_api_key")
    if current:
        hint = f"◈ Current key: <code>{current[:8]}...</code>\n\n"
    else:
        hint = ""

    await callback.message.edit_text(
        f"△ NEXUS API KEY △\n\n"
        f"{hint}"
        f"✦ Send me your Nexus API key, master~ ehehe~\n"
        f"◇ I'll keep it safe just for you~ ◈",
        reply_markup=nexus_back_kb(),
        parse_mode="HTML",
    )
    await state.set_state(NexusKeyStates.waiting_for_key)
    await callback.answer()


@router.message(NexusKeyStates.waiting_for_key)
async def process_nexus_key(message: Message, state: FSMContext):
    key = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass

    if len(key) < 8:
        await message.answer(
            "mou~ That doesn't look like a valid key, master~ ◇\n"
            "Please try again with your real Nexus API key~ ◈",
            reply_markup=nexus_back_kb(),
        )
        return

    await users_col.update_one(
        {"telegram_id": message.from_user.id},
        {"$set": {"nexus_api_key": key}},
    )
    await state.clear()

    user = await users_col.find_one({"telegram_id": message.from_user.id})
    expiry = format_expiry(user["key_expires_at"]) if user and user.get("key_expires_at") else "Unknown"

    await message.answer(
        "✦ kyaa~! Nexus API key saved, master~ ehehe~\n"
        "◈ I've got it locked away safely just for you~ ✦\n\n"
        "Now you can upload anime to your heart's content~ ◇",
        reply_markup=main_menu_kb(expiry, True),
        parse_mode="HTML",
    )
