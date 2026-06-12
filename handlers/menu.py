import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from database import users_col, queue_col
from utils.helpers import format_expiry, now_utc, ensure_utc
from utils.nexus_client import ping_nexus
from keyboards import main_menu_kb, back_kb

router = Router()
logger = logging.getLogger(__name__)


async def _get_authed_user(user_id: int):
    user = await users_col.find_one({"telegram_id": user_id})
    if not user:
        return None
    if user.get("key_expires_at") and ensure_utc(user["key_expires_at"]) < now_utc():
        return None
    return user


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    user = await _get_authed_user(callback.from_user.id)
    if not user:
        await callback.answer("mou~ Your session expired, master~ Use /auth again ◈", show_alert=True)
        return
    expiry = format_expiry(user["key_expires_at"]) if user.get("key_expires_at") else "Unknown"
    nexus_ok = bool(user.get("nexus_api_key"))
    await callback.message.edit_text(
        f"✦ Welcome back, master~ ehehe~\n"
        f"◈ Your key expires on <b>{expiry}</b>\n\n"
        f"What shall we do today~ ◇",
        reply_markup=main_menu_kb(expiry, nexus_ok),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "my_stats")
async def cb_my_stats(callback: CallbackQuery):
    user = await _get_authed_user(callback.from_user.id)
    if not user:
        await callback.answer("mou~ Your session expired~ Use /auth ◈", show_alert=True)
        return

    in_queue = await queue_col.count_documents({"user_id": callback.from_user.id})
    total = user.get("total_uploaded", 0)
    month = user.get("month_uploaded", 0)
    expiry = format_expiry(user["key_expires_at"]) if user.get("key_expires_at") else "Unknown"

    text = (
        "○ MY STATS ○\n\n"
        f"✦ total uploaded : {total}\n"
        f"◈ this month     : {month}\n"
        f"◇ in queue now   : {in_queue}\n"
        f"○ key expires    : {expiry}"
    )
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "status_check")
async def cb_status_check(callback: CallbackQuery):
    user = await _get_authed_user(callback.from_user.id)
    if not user:
        await callback.answer("mou~ Auth first, master~ ◈", show_alert=True)
        return

    await callback.answer("◈ Checking Nexus API status~", show_alert=False)

    api_key = user.get("nexus_api_key")
    if not api_key:
        await callback.message.edit_text(
            "◈ STATUS ◈\n\n"
            "mou~ You haven't configured your Nexus API key yet, master~ ◇\n"
            "I can't check the status without it ehehe~\n\n"
            "Please set your key first using the △ Nexus API Key button~",
            reply_markup=back_kb(),
            parse_mode="HTML",
        )
        return

    reachable = await ping_nexus(api_key)

    if reachable:
        status_text = (
            "◈ STATUS ◈\n\n"
            "✦ Nexus API is online and responding, master~ kyaa~!\n"
            "◈ Everything looks good~ Ready to upload whenever you are~ ehehe~"
        )
    else:
        status_text = (
            "◈ STATUS ◈\n\n"
            "mou~ The Nexus API isn't responding right now~ ◇\n"
            "Maybe it's taking a nap~ Check back in a bit, master~ ◈"
        )

    await callback.message.edit_text(status_text, reply_markup=back_kb(), parse_mode="HTML")
