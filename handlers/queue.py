import logging
import math

from aiogram import Router, F
from aiogram.types import CallbackQuery

from database import users_col
from utils.helpers import now_utc, elapsed_str, ensure_utc
from utils.queue_manager import (
    get_user_queue,
    cancel_task_by_id,
    cancel_all_user_tasks,
    POST_UPLOAD_WAIT,
)
from keyboards import queue_nav_kb, back_kb, task_cancel_confirm_kb, cancel_all_confirm_kb

router = Router()
logger = logging.getLogger(__name__)

PAGE_SIZE = 2


# ── helpers ───────────────────────────────────────────────────────────────

def _cancel_label(item: dict) -> str:
    name    = item.get("anime_name", "?")
    season  = item.get("season", "?")
    profile = item.get("profile", "?")
    return f"{name} S{season} [{profile}]"


def _format_queue_item(item: dict, index: int) -> str:
    name          = item.get("anime_name", "Unknown")
    season        = item.get("season", "?")
    profile       = item.get("profile", "?")
    anime_type    = item.get("anime_type", "series")
    ep_from       = item.get("ep_from", "?")
    ep_to         = item.get("ep_to", "?")
    status        = item.get("status", "waiting")
    started_at    = item.get("started_at")

    total_links   = item.get("total_links", 0)
    done_count    = item.get("done_count", 0)
    live_logs     = item.get("live_logs", [])

    current_batch = item.get("current_batch", "")
    batch_total   = item.get("batch_total", 0)
    batch_offset  = item.get("batch_offset", 0)
    batch_done    = max(0, done_count - batch_offset)

    lines = [f"┄┄ task {index} ┄┄"]
    lines.append(f"✦ {name} S{season}  [{anime_type}]")

    if status == "processing":
        elapsed_secs = 0
        if started_at:
            elapsed_secs = int((now_utc() - ensure_utc(started_at)).total_seconds())

        lines.append("┌ processing~ ◈")
        lines.append(f"├ profile   : {profile}")
        lines.append(f"├ episodes  : {ep_from} → {ep_to}")
        lines.append(f"├ elapsed   : {elapsed_str(elapsed_secs)}")

        # Overall progress
        lines.append(f"├ links     : {done_count} / {total_links}")

        # Per-quality batch progress
        if current_batch:
            lines.append(f"├ quality   : {current_batch}")
            if batch_total > 0:
                lines.append(f"├ batch     : {batch_done} / {batch_total} × {current_batch}")

        # Live logs — last 5
        if live_logs:
            lines.append("├ ─ live logs ──────────")
            last_five = live_logs[-5:]
            for i, log in enumerate(last_five):
                connector = "└" if i == len(last_five) - 1 else "├"
                lines.append(f"{connector} {log}")
        else:
            lines.append("└ waiting for first response~")

    else:
        lines.append("┌ waiting~ ◇")
        lines.append("└ starts after task " + str(index - 1) if index > 1 else "└ next up~")

    return "\n".join(lines)


# ── queue page ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_queue")
async def cb_my_queue(callback: CallbackQuery):
    await _show_queue_page(callback, 0)


@router.callback_query(F.data.startswith("queue_page:"))
async def cb_queue_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await _show_queue_page(callback, page)


async def _show_queue_page(callback: CallbackQuery, page: int):
    user = await users_col.find_one({"telegram_id": callback.from_user.id})
    if not user:
        await callback.answer("mou~ Auth first, master~ ◈", show_alert=True)
        return

    items = await get_user_queue(callback.from_user.id)

    if not items:
        await callback.message.edit_text(
            "◇ YOUR QUEUE ◇\n\n"
            "mou~ Your queue is empty, master~ ◈\n"
            "Nothing to show here~ ehehe~\n"
            "Start an upload to fill it up~!",
            reply_markup=back_kb(),
        )
        await callback.answer()
        return

    total_pages = math.ceil(len(items) / PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))
    start       = page * PAGE_SIZE
    page_items  = items[start: start + PAGE_SIZE]

    lines = ["◇ YOUR QUEUE ◇\n"]
    cancel_items = []
    for i, item in enumerate(page_items, start=start + 1):
        lines.append(_format_queue_item(item, i))
        lines.append("")
        cancel_items.append({"id": str(item["_id"]), "label": _cancel_label(item)})

    cooldown_min = POST_UPLOAD_WAIT // 60
    lines.append(
        f"◈ page {page + 1} of {total_pages}"
        f"  ┄  {cooldown_min} min cooldown between uploads~ ◇"
    )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=queue_nav_kb(page, total_pages, cancel_items=cancel_items),
    )
    await callback.answer()


# ── cancel single task ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_task:"))
async def cb_cancel_task(callback: CallbackQuery):
    queue_id = callback.data.split(":", 1)[1]
    items    = await get_user_queue(callback.from_user.id)
    target   = next((it for it in items if str(it["_id"]) == queue_id), None)

    if not target:
        await callback.answer("mou~ That task is already gone~ ◇", show_alert=True)
        return

    label  = _cancel_label(target)
    status = target.get("status", "waiting")
    warn   = (
        "  ⊹ It is currently <b>processing</b> — Nexus session will also be purged~"
        if status == "processing" else ""
    )

    await callback.message.edit_text(
        f"◇ CANCEL TASK ◇\n\n"
        f"ara ara~ Are you sure you want to cancel~?\n\n"
        f"◈ <b>{label}</b>\n"
        f"{warn}\n\n"
        "This cannot be undone~ ehehe~",
        reply_markup=task_cancel_confirm_kb(queue_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_task_yes:"))
async def cb_cancel_task_yes(callback: CallbackQuery):
    queue_id = callback.data.split(":", 1)[1]
    user     = await users_col.find_one({"telegram_id": callback.from_user.id})
    api_key  = user.get("nexus_api_key") if user else None

    removed = await cancel_task_by_id(queue_id, api_key)

    if removed:
        await callback.answer("◈ Task cancelled~ Done, master~!", show_alert=True)
    else:
        await callback.answer("mou~ Task not found~ already done? ◇", show_alert=True)

    await _show_queue_page(callback, 0)


# ── cancel all tasks ──────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel_all_tasks")
async def cb_cancel_all(callback: CallbackQuery):
    items = await get_user_queue(callback.from_user.id)
    if not items:
        await callback.answer("mou~ Queue is already empty~ ◇", show_alert=True)
        return

    count = len(items)
    await callback.message.edit_text(
        f"◇ CANCEL ALL ◇\n\n"
        f"ara ara~ You want to nuke <b>all {count} task(s)</b>~?!\n\n"
        "⊹ Any processing tasks will have their Nexus sessions purged too~\n\n"
        "This <b>cannot</b> be undone~ ehehe~",
        reply_markup=cancel_all_confirm_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_all_tasks_yes")
async def cb_cancel_all_yes(callback: CallbackQuery):
    user    = await users_col.find_one({"telegram_id": callback.from_user.id})
    api_key = user.get("nexus_api_key") if user else None

    removed = await cancel_all_user_tasks(callback.from_user.id, api_key)

    await callback.answer(
        f"◈ Done~ {removed} task(s) cancelled, master~! Queue is clean now~ ehehe~",
        show_alert=True,
    )
    await _show_queue_page(callback, 0)
