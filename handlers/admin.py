import logging
from datetime import timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import keys_col, users_col
from utils.helpers import generate_key_string, now_utc, format_expiry, ensure_utc
from keyboards import admin_main_kb, admin_duration_kb, back_kb
from config import ADMIN_ID

router = Router()
logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    waiting_revoke_key = State()


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(
            "mou~ You're not my master~! ◇\n"
            "Only the real master can use this~ ◈ ehehe~"
        )
        return
    await message.answer(
        "✦ ADMIN PANEL ✦\n\n"
        "ara ara~ Welcome, Master~ ◈\n"
        "What shall we do today~? ehehe~",
        reply_markup=admin_main_kb(),
    )


@router.callback_query(F.data == "admin_gen_key")
async def cb_admin_gen_key(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("◇ Not authorized~", show_alert=True)
        return
    await callback.message.edit_text(
        "✦ GENERATE KEY ✦\n\n"
        "◈ How many days should this key last, Master~? ehehe~",
        reply_markup=admin_duration_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_dur:"))
async def cb_admin_duration(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("◇ Not authorized~", show_alert=True)
        return
    days = int(callback.data.split(":")[1])
    key_string = generate_key_string()
    expires_at = now_utc() + timedelta(days=days)

    await keys_col.insert_one({
        "key_string": key_string,
        "created_by": ADMIN_ID,
        "expires_at": expires_at,
        "is_active": True,
    })

    await callback.message.edit_text(
        f"✦ KEY GENERATED ✦\n\n"
        f"kyaa~! New key created, Master~! ◈\n\n"
        f"◇ Key     : <code>{key_string}</code>\n"
        f"○ Expires : <b>{format_expiry(expires_at)}</b>\n"
        f"◈ Valid for {days} days~\n\n"
        f"✦ Share it with your chosen one~ ehehe~",
        reply_markup=admin_main_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_view_keys")
async def cb_admin_view_keys(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("◇ Not authorized~", show_alert=True)
        return

    keys = await keys_col.find({"is_active": True}).sort("expires_at", 1).to_list(length=50)
    if not keys:
        text = "◈ VIEW ALL KEYS ◈\n\nmou~ No active keys found~ ◇"
    else:
        lines = ["◈ VIEW ALL KEYS ◈\n"]
        for k in keys:
            expiry = format_expiry(k["expires_at"]) if k.get("expires_at") else "Never"
            expired = k.get("expires_at") and ensure_utc(k["expires_at"]) < now_utc()
            status = "◇ expired" if expired else "✦ active"
            lines.append(f"{status} | <code>{k['key_string']}</code> | exp: {expiry}")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=admin_main_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_revoke_key")
async def cb_admin_revoke_key(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("◇ Not authorized~", show_alert=True)
        return
    await callback.message.edit_text(
        "△ REVOKE KEY △\n\n"
        "◇ Send me the key string to revoke, Master~\n"
        "Format: <code>SAKURA-XXXX-XXXX</code>",
        reply_markup=admin_main_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.waiting_revoke_key)
    await callback.answer()


@router.message(AdminStates.waiting_revoke_key)
async def process_revoke_key(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    key_string = message.text.strip().upper()
    result = await keys_col.update_one(
        {"key_string": key_string},
        {"$set": {"is_active": False}},
    )
    await state.clear()

    if result.matched_count == 0:
        await message.answer(
            f"mou~ Key <code>{key_string}</code> not found~ ◇\n"
            "Double-check the spelling, Master~ ◈",
            reply_markup=admin_main_kb(),
            parse_mode="HTML",
        )
        return

    affected_user = await users_col.find_one({"key_string": key_string})
    if affected_user:
        try:
            await message.bot.send_message(
                affected_user["telegram_id"],
                "kyaa~! mou~ Your key has been revoked, master~ ◈\n"
                "Please contact the admin to get a new one~ ◇",
            )
        except Exception as e:
            logger.error(f"Failed to notify user about revoked key: {e}")

    await message.answer(
        f"✦ Key <code>{key_string}</code> has been revoked~ ◈\n"
        f"mou~ Bye bye, bad key~ ◇ ehehe~",
        reply_markup=admin_main_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_active_users")
async def cb_admin_active_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("◇ Not authorized~", show_alert=True)
        return

    total = await users_col.count_documents({})
    active = await users_col.count_documents({
        "key_expires_at": {"$gt": now_utc()},
    })

    await callback.message.edit_text(
        f"○ ACTIVE USERS ○\n\n"
        f"✦ total users   : {total}\n"
        f"◈ active keys   : {active}\n"
        f"◇ expired/other : {total - active}\n\n"
        f"ehehe~ Your little kingdom, Master~ ◈",
        reply_markup=admin_main_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def cb_admin_cancel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await state.clear()
    await callback.message.edit_text(
        "✦ ADMIN PANEL ✦\n\n"
        "ara ara~ Welcome, Master~ ◈\n"
        "What shall we do today~? ehehe~",
        reply_markup=admin_main_kb(),
    )
    await callback.answer()
