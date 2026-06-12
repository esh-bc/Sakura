import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import users_col
from utils.helpers import now_utc, parse_links, is_drive_link, ensure_utc
from utils.queue_manager import add_to_queue, check_duplicate
from keyboards import (
    cancel_kb, anime_type_kb, profile_select_kb,
    links_done_kb, links_done_skip_kb,
    confirm_upload_kb, duplicate_kb, main_menu_kb,
)

router = Router()
logger = logging.getLogger(__name__)


class UploadStates(StatesGroup):
    anime_name     = State()
    season         = State()
    anime_type     = State()   # series / movie
    profile        = State()   # SUB / DUB
    ep_range       = State()   # series only
    links_sub      = State()   # SUB profile
    links_480      = State()   # DUB phase 1
    links_720      = State()   # DUB phase 2
    links_1080     = State()   # DUB phase 3
    confirm        = State()
    duplicate_check = State()


# ── helpers ─────────────────────────────────────────────────────────────

def _link_bar(collected: int, skipped: bool = False) -> str:
    if skipped:
        return "○○○○○○○○○○○○  [ skip ]"
    width = 12
    filled = min(collected, width)
    return "⬢" * filled + "⬡" * (width - filled) + f"  [ {collected} ]"


def _build_preview(data: dict) -> str:
    name      = data.get("anime_name", "—")
    season    = data.get("season", "—")
    atype     = data.get("anime_type", "—")
    profile   = data.get("profile", "—")
    ep_from   = data.get("ep_from", "—")
    ep_to     = data.get("ep_to", "—")

    lines = [
        "◈ ANIME UPLOAD ◈\n",
        f"✦ name    : {name}",
        f"◈ type    : {atype}",
        f"◈ season  : {season}",
        f"◇ profile : {profile}",
        f"○ eps     : {ep_from} → {ep_to}",
    ]

    if profile == "SUB":
        links_sub = data.get("links_sub", [])
        lines.append(f"\nSUB    {_link_bar(len(links_sub))}")
    elif profile == "DUB":
        lines.append("")
        lines.append(f"480p   {_link_bar(len(data.get('links_480', [])), data.get('skip_480', False))}")
        lines.append(f"720p   {_link_bar(len(data.get('links_720', [])), data.get('skip_720', False))}")
        lines.append(f"1080p  {_link_bar(len(data.get('links_1080', [])), data.get('skip_1080', False))}")

    return "\n".join(lines)


async def _safe_delete(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


async def _edit_preview(bot, chat_id: int, msg_id: int, text: str, kb):
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=msg_id,
            reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        pass


async def _get_menu_kb(user_id: int) -> tuple:
    user = await users_col.find_one({"telegram_id": user_id})
    from utils.helpers import format_expiry
    expiry = format_expiry(user["key_expires_at"]) if user and user.get("key_expires_at") else "Unknown"
    nexus_ok = bool(user.get("nexus_api_key")) if user else False
    return main_menu_kb(expiry, nexus_ok)


# ── entry point ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "anime_upload")
async def cb_anime_upload(callback: CallbackQuery, state: FSMContext):
    user = await users_col.find_one({"telegram_id": callback.from_user.id})
    if not user or (user.get("key_expires_at") and ensure_utc(user["key_expires_at"]) < now_utc()):
        await callback.answer("mou~ Auth first, master~ ◈", show_alert=True)
        return
    if not user.get("nexus_api_key"):
        await callback.answer(
            "kyaa~ Configure your Nexus API key first, master~! △ Nexus API Key button~ ◈",
            show_alert=True,
        )
        return

    await state.clear()
    await state.update_data(
        anime_name=None, season=None, anime_type=None, profile=None,
        ep_from=None, ep_to=None,
        links_sub=[], links_480=[], links_720=[], links_1080=[],
        skip_480=False, skip_720=False, skip_1080=False,
        preview_msg_id=callback.message.message_id,
    )
    await state.set_state(UploadStates.anime_name)
    await callback.message.edit_text(
        "◈ ANIME UPLOAD ◈\n\n"
        "✦ ara ara~ Let's get started, master~\n"
        "◇ What's the anime name? Send it to me~ ehehe~",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


# ── step 1 : name ─────────────────────────────────────────────────────────

@router.message(UploadStates.anime_name)
async def process_anime_name(message: Message, state: FSMContext):
    await _safe_delete(message)
    name = message.text.strip()
    await state.update_data(anime_name=name)
    data = await state.get_data()

    text = (
        "◈ ANIME UPLOAD ◈\n\n"
        f"✦ name    : {name}\n\n"
        "mou~ Now tell me the season number, master~ ◈\n"
        "◇ For movies just send <code>1</code>~"
    )
    await _edit_preview(message.bot, message.chat.id, data["preview_msg_id"], text, cancel_kb())
    await state.set_state(UploadStates.season)


# ── step 2 : season ───────────────────────────────────────────────────────

@router.message(UploadStates.season)
async def process_season(message: Message, state: FSMContext):
    await _safe_delete(message)
    try:
        season = int(message.text.strip())
        if season < 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "mou~ Send a number, master~ like <code>1</code> or <code>2</code>~ ◈",
            parse_mode="HTML",
        )
        return

    await state.update_data(season=season)
    data = await state.get_data()

    text = (
        "◈ ANIME UPLOAD ◈\n\n"
        f"✦ name    : {data['anime_name']}\n"
        f"◈ season  : {season}\n\n"
        "✦ Is this a Series or a Movie, master~? ◇"
    )
    await _edit_preview(message.bot, message.chat.id, data["preview_msg_id"], text, anime_type_kb())
    await state.set_state(UploadStates.anime_type)


# ── step 3 : type (series / movie) ────────────────────────────────────────

@router.callback_query(F.data.in_({"type_series", "type_movie"}), UploadStates.anime_type)
async def process_anime_type(callback: CallbackQuery, state: FSMContext):
    atype = "series" if callback.data == "type_series" else "movie"
    await state.update_data(anime_type=atype)
    data = await state.get_data()

    text = (
        f"◈ ANIME UPLOAD ◈\n\n"
        f"✦ name    : {data['anime_name']}\n"
        f"◈ type    : {atype}\n"
        f"◈ season  : {data['season']}\n\n"
        f"✦ Profile, master~? ◇ SUB or DUB~ ehehe~"
    )
    await callback.message.edit_text(text, reply_markup=profile_select_kb(), parse_mode="HTML")
    await state.set_state(UploadStates.profile)
    await callback.answer()


# ── step 4 : profile (SUB / DUB) ──────────────────────────────────────────

@router.callback_query(F.data.in_({"profile_sub", "profile_dub"}), UploadStates.profile)
async def process_profile(callback: CallbackQuery, state: FSMContext):
    profile = "SUB" if callback.data == "profile_sub" else "DUB"
    await state.update_data(profile=profile)
    data = await state.get_data()

    # Movies skip episode range → auto 1-1
    if data["anime_type"] == "movie":
        await state.update_data(ep_from=1, ep_to=1)
        await _go_to_links(callback, state, profile)
        return

    # Series → ask ep range
    text = (
        f"◈ ANIME UPLOAD ◈\n\n"
        f"✦ name    : {data['anime_name']}\n"
        f"◈ type    : {data['anime_type']}\n"
        f"◈ season  : {data['season']}\n"
        f"◇ profile : {profile}\n\n"
        f"○ Episode range, master~? Format: <code>1-12</code> ehehe~"
    )
    await callback.message.edit_text(text, reply_markup=cancel_kb(), parse_mode="HTML")
    await state.set_state(UploadStates.ep_range)
    await callback.answer()


async def _go_to_links(callback: CallbackQuery, state: FSMContext, profile: str):
    data = await state.get_data()
    if profile == "SUB":
        await state.set_state(UploadStates.links_sub)
        text = _build_preview(data) + "\n\n✦ Send me the <b>SUB</b> Drive links, master~!\nOne per line or all at once~ ◈"
        await callback.message.edit_text(text, reply_markup=links_done_kb("finish"), parse_mode="HTML")
    else:
        await state.set_state(UploadStates.links_480)
        text = _build_preview(data) + "\n\n✦ Send <b>480p</b> Drive links — or skip if you don't have them~ ◈"
        await callback.message.edit_text(text, reply_markup=links_done_skip_kb("480p", "720p"), parse_mode="HTML")
    await callback.answer()


# ── step 5 : episode range (series only) ─────────────────────────────────

@router.message(UploadStates.ep_range)
async def process_ep_range(message: Message, state: FSMContext):
    await _safe_delete(message)
    try:
        parts = message.text.strip().split("-")
        ep_from = int(parts[0].strip())
        ep_to   = int(parts[1].strip())
        if ep_from > ep_to or ep_from < 1:
            raise ValueError
    except (ValueError, IndexError):
        data = await state.get_data()
        await _edit_preview(
            message.bot, message.chat.id, data["preview_msg_id"],
            "mou~ Wrong format, master~ ◇\nSend like <code>1-12</code>~ ehehe~",
            cancel_kb(),
        )
        return

    await state.update_data(ep_from=ep_from, ep_to=ep_to)
    data = await state.get_data()
    profile = data["profile"]

    if profile == "SUB":
        await state.set_state(UploadStates.links_sub)
        text = _build_preview(data) + "\n\n✦ Send me the <b>SUB</b> Drive links, master~!\nOne per line or all at once~ ◈"
        await _edit_preview(message.bot, message.chat.id, data["preview_msg_id"], text, links_done_kb("finish"))
    else:
        await state.set_state(UploadStates.links_480)
        text = _build_preview(data) + "\n\n✦ Send <b>480p</b> Drive links — or skip if you don't have them~ ◈"
        await _edit_preview(message.bot, message.chat.id, data["preview_msg_id"], text, links_done_skip_kb("480p", "720p"))


# ── link collection helpers ───────────────────────────────────────────────

async def _collect_links(message: Message, state: FSMContext, key: str, done_kb):
    await _safe_delete(message)
    raw = parse_links(message.text)
    bad  = [l for l in raw if not is_drive_link(l)]
    good = [l for l in raw if is_drive_link(l)]

    data = await state.get_data()
    existing = data.get(key, [])
    existing.extend(good)
    await state.update_data(**{key: existing})

    warn = f"\n\nmou~ {len(bad)} link(s) rejected — Drive links only, master~ ◇" if bad else ""
    updated = await state.get_data()
    text = _build_preview(updated) + warn

    await _edit_preview(message.bot, message.chat.id, data["preview_msg_id"], text, done_kb)


@router.message(UploadStates.links_sub)
async def msg_links_sub(message: Message, state: FSMContext):
    await _collect_links(message, state, "links_sub", links_done_kb("finish"))


@router.message(UploadStates.links_480)
async def msg_links_480(message: Message, state: FSMContext):
    await _collect_links(message, state, "links_480", links_done_skip_kb("480p", "720p"))


@router.message(UploadStates.links_720)
async def msg_links_720(message: Message, state: FSMContext):
    await _collect_links(message, state, "links_720", links_done_skip_kb("720p", "1080p"))


@router.message(UploadStates.links_1080)
async def msg_links_1080(message: Message, state: FSMContext):
    await _collect_links(message, state, "links_1080", links_done_skip_kb("1080p", "finish"))


# ── skip buttons ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("links_skip:"))
async def cb_links_skip(callback: CallbackQuery, state: FSMContext):
    quality = callback.data.split(":")[1]   # "480p" / "720p" / "1080p"
    current = await state.get_state()

    skip_key_map = {"480p": "skip_480", "720p": "skip_720", "1080p": "skip_1080"}
    skip_key = skip_key_map.get(quality)
    if skip_key:
        await state.update_data(**{skip_key: True})

    data = await state.get_data()
    text = _build_preview(data)

    if quality == "480p":
        await state.set_state(UploadStates.links_720)
        prompt = "\n\n✦ Send <b>720p</b> Drive links — or skip~ ◈"
        await callback.message.edit_text(text + prompt, reply_markup=links_done_skip_kb("720p", "1080p"), parse_mode="HTML")

    elif quality == "720p":
        await state.set_state(UploadStates.links_1080)
        prompt = "\n\n✦ Send <b>1080p</b> Drive links — or skip~ ◈"
        await callback.message.edit_text(text + prompt, reply_markup=links_done_skip_kb("1080p", "finish"), parse_mode="HTML")

    elif quality == "1080p":
        # All three phases done via skip — check at least one has links
        data = await state.get_data()
        has_links = (data.get("links_480") or data.get("links_720") or data.get("links_1080"))
        if not has_links:
            await callback.answer(
                "mou~ You skipped everything, master~! At least one quality needs links~ ◇",
                show_alert=True,
            )
            return
        await _check_dup_or_confirm(callback, state, data)

    await callback.answer()


# ── done buttons ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "links_done")
async def cb_links_done(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    data    = await state.get_data()

    if current == UploadStates.links_sub.state:
        if not data.get("links_sub"):
            await callback.answer("mou~ No SUB links yet, master~! Add some first~ ◇", show_alert=True)
            return
        await _check_dup_or_confirm(callback, state, data)

    elif current == UploadStates.links_480.state:
        if not data.get("links_480"):
            await callback.answer("mou~ No 480p links added yet, master~! Add links or skip~ ◇", show_alert=True)
            return
        await state.set_state(UploadStates.links_720)
        text = _build_preview(await state.get_data()) + "\n\n✦ Send <b>720p</b> Drive links — or skip~ ◈"
        await callback.message.edit_text(text, reply_markup=links_done_skip_kb("720p", "1080p"), parse_mode="HTML")

    elif current == UploadStates.links_720.state:
        if not data.get("links_720"):
            await callback.answer("mou~ No 720p links added yet, master~! Add links or skip~ ◇", show_alert=True)
            return
        await state.set_state(UploadStates.links_1080)
        text = _build_preview(await state.get_data()) + "\n\n✦ Send <b>1080p</b> Drive links — or skip~ ◈"
        await callback.message.edit_text(text, reply_markup=links_done_skip_kb("1080p", "finish"), parse_mode="HTML")

    elif current == UploadStates.links_1080.state:
        if not data.get("links_1080"):
            await callback.answer("mou~ No 1080p links added yet, master~! Add links or skip~ ◇", show_alert=True)
            return
        data = await state.get_data()
        await _check_dup_or_confirm(callback, state, data)

    await callback.answer()


# ── duplicate check & confirm ─────────────────────────────────────────────

async def _check_dup_or_confirm(callback: CallbackQuery, state: FSMContext, data: dict):
    is_dup = await check_duplicate(
        callback.from_user.id,
        data.get("anime_name"), data.get("season"), data.get("profile"),
    )
    if is_dup:
        await state.set_state(UploadStates.duplicate_check)
        text = (
            "◇ DUPLICATE DETECTED ◇\n\n"
            f"✦ <b>{data.get('anime_name')} S{data.get('season')}</b> ({data.get('profile')})\n"
            "is already in your queue, master~! ◈\n\n"
            "mou~ Want to add it anyway~ ◇?"
        )
        await callback.message.edit_text(text, reply_markup=duplicate_kb(), parse_mode="HTML")
    else:
        await _show_confirm(callback, state, data)


async def _show_confirm(callback: CallbackQuery, state: FSMContext, data: dict):
    await state.set_state(UploadStates.confirm)
    links_sub  = data.get("links_sub", [])
    links_480  = data.get("links_480", [])
    links_720  = data.get("links_720", [])
    links_1080 = data.get("links_1080", [])
    total = len(links_sub) + len(links_480) + len(links_720) + len(links_1080)

    text = (
        _build_preview(data) + "\n\n"
        f"◈ Total links : {total}\n\n"
        "✦ Everything looks good, master~? ◈\n"
        "Tap Start Upload when you're ready~ ehehe~"
    )
    await callback.message.edit_text(text, reply_markup=confirm_upload_kb(), parse_mode="HTML")


@router.callback_query(F.data == "dup_add", UploadStates.duplicate_check)
async def cb_dup_add(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await _show_confirm(callback, state, data)
    await callback.answer()


@router.callback_query(F.data == "dup_no", UploadStates.duplicate_check)
async def cb_dup_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = await _get_menu_kb(callback.from_user.id)
    await callback.message.edit_text(
        "◇ Alright, master~! Duplicate not added~ ◈\nBack to the menu~",
        reply_markup=kb,
    )
    await callback.answer()


# ── start upload ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "start_upload", UploadStates.confirm)
async def cb_start_upload(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    queue_id = await add_to_queue(
        user_id    = callback.from_user.id,
        anime_name = data["anime_name"],
        season     = data["season"],
        anime_type = data["anime_type"],
        profile    = data["profile"],
        ep_from    = data["ep_from"],
        ep_to      = data["ep_to"],
        links_sub  = data.get("links_sub", []),
        links_480  = data.get("links_480", []),
        links_720  = data.get("links_720", []),
        links_1080 = data.get("links_1080", []),
    )

    kb = await _get_menu_kb(callback.from_user.id)
    await callback.message.edit_text(
        f"✦ kyaa~! <b>{data['anime_name']} S{data['season']}</b> ({data['profile']}) queued, master~! ◈\n"
        f"◇ I'll process it soon~ ehehe~\n\n"
        f"◈ Queue ID: <code>{queue_id[:8]}...</code>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ── cancel ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel_flow")
async def cb_cancel_flow(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = await _get_menu_kb(callback.from_user.id)
    await callback.message.edit_text(
        "◇ Cancelled~ No worries, master~ ◈\nWe can try again whenever you're ready~ ehehe~",
        reply_markup=kb,
    )
    await callback.answer()
