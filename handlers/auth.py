import logging
from datetime import timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from database import keys_col, users_col
from utils.helpers import now_utc, format_expiry, ensure_utc
from keyboards import main_menu_kb

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("start"))
async def cmd_start(message: Message):
    user = await users_col.find_one({"telegram_id": message.from_user.id})
    if not user:
        await message.answer(
            "kyaa~! A new face~ ◈\n\n"
            "ara ara, master~ You need to authenticate before I let you in ehehe~\n"
            "Use <code>/auth YOUR_KEY</code> to prove you belong here ✦",
            parse_mode="HTML",
        )
        return

    if user.get("key_expires_at") and ensure_utc(user["key_expires_at"]) < now_utc():
        await message.answer(
            "mou~ Your key has expired, master~ ◇\n"
            "Please get a new key and use <code>/auth YOUR_KEY</code> again~ ◈",
            parse_mode="HTML",
        )
        return

    expiry = format_expiry(user["key_expires_at"]) if user.get("key_expires_at") else "Unknown"
    nexus_ok = bool(user.get("nexus_api_key"))
    await message.answer(
        f"✦ Welcome back, master~ ehehe~\n"
        f"◈ Your key expires on <b>{expiry}</b>\n\n"
        f"What shall we do today~ ◇",
        reply_markup=main_menu_kb(expiry, nexus_ok),
        parse_mode="HTML",
    )


@router.message(Command("auth"))
async def cmd_auth(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "ara ara~ You forgot the key, master~ ◈\n"
            "Usage: <code>/auth SAKURA-XXXX-XXXX</code> ✦",
            parse_mode="HTML",
        )
        return

    key_string = parts[1].strip().upper()
    key_doc = await keys_col.find_one({"key_string": key_string, "is_active": True})

    if not key_doc:
        await message.answer(
            "mou~ That key doesn't work~ ◇\n"
            "Are you sure you typed it right, master? ◈ Try again~",
            parse_mode="HTML",
        )
        return

    if key_doc.get("expires_at") and ensure_utc(key_doc["expires_at"]) < now_utc():
        await message.answer(
            "kyaa~ This key has expired~ ◈\n"
            "Please ask for a fresh one, master~ ✦",
            parse_mode="HTML",
        )
        return

    expires_at = key_doc.get("expires_at")
    await users_col.update_one(
        {"telegram_id": message.from_user.id},
        {
            "$set": {
                "telegram_id": message.from_user.id,
                "key_string": key_string,
                "key_expires_at": expires_at,
            },
            "$setOnInsert": {
                "nexus_api_key": None,
                "joined_at": now_utc(),
                "total_uploaded": 0,
                "month_uploaded": 0,
            },
        },
        upsert=True,
    )

    expiry = format_expiry(expires_at) if expires_at else "Never"
    user = await users_col.find_one({"telegram_id": message.from_user.id})
    nexus_ok = bool(user.get("nexus_api_key"))

    await message.answer(
        f"✦ kyaa~! Welcome, master~ ehehe~\n"
        f"◈ Authentication successful~!\n"
        f"◇ Your key expires on <b>{expiry}</b>\n\n"
        f"Now then~ what would you like to do? ◈",
        reply_markup=main_menu_kb(expiry, nexus_ok),
        parse_mode="HTML",
    )
