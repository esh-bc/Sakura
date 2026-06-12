import asyncio
import logging
from bson import ObjectId
import aiohttp

from database import queue_col, users_col
from utils.nexus_client import (
    cancel_session, init_session, process_single_link,
    generate_csv, update_query,
)
from utils.helpers import now_utc
from config import NEXUS_TIMEOUT

logger = logging.getLogger(__name__)

_bot_ref = None

CONCURRENCY      = 5    # max parallel requests per quality batch
QUALITY_COOLDOWN = 10   # seconds between 480p→720p→1080p batches
POST_UPLOAD_WAIT = 300  # seconds (5 min) cooldown after full upload cycle


def set_bot(bot):
    global _bot_ref
    _bot_ref = bot


# ── queue CRUD ────────────────────────────────────────────────────────────

def _count_links(profile, links_sub, links_480, links_720, links_1080) -> int:
    if profile == "SUB":
        return len(links_sub)
    return len(links_480) + len(links_720) + len(links_1080)


async def add_to_queue(
    user_id: int, anime_name: str, season: int,
    anime_type: str, profile: str,
    ep_from: int, ep_to: int,
    links_sub: list, links_480: list, links_720: list, links_1080: list,
) -> str:
    total = _count_links(profile, links_sub, links_480, links_720, links_1080)
    doc = {
        "user_id":       user_id,
        "anime_name":    anime_name,
        "season":        season,
        "anime_type":    anime_type,
        "profile":       profile,
        "ep_from":       ep_from,
        "ep_to":         ep_to,
        "links_sub":     links_sub,
        "links_480":     links_480,
        "links_720":     links_720,
        "links_1080":    links_1080,
        "status":        "waiting",
        "created_at":    now_utc(),
        "progress":      0,
        "started_at":    None,
        "total_links":   total,
        "done_count":    0,
        "live_logs":     [],
        "current_batch": "",
        "batch_total":   0,
        "batch_offset":  0,
    }
    result = await queue_col.insert_one(doc)
    return str(result.inserted_id)


async def get_user_queue(user_id: int) -> list:
    cursor = queue_col.find({"user_id": user_id}).sort("created_at", 1)
    return await cursor.to_list(length=None)


async def get_next_waiting() -> dict | None:
    return await queue_col.find_one({"status": "waiting"}, sort=[("created_at", 1)])


async def set_status(queue_id: str, status: str, progress: int = 0):
    update = {"status": status, "progress": progress}
    if status == "processing":
        update["started_at"] = now_utc()
    await queue_col.update_one({"_id": ObjectId(queue_id)}, {"$set": update})


async def delete_queue_item(queue_id: str):
    await queue_col.delete_one({"_id": ObjectId(queue_id)})


async def check_duplicate(user_id: int, anime_name: str, season: int, profile: str) -> bool:
    existing = await queue_col.find_one({
        "user_id":    user_id,
        "anime_name": anime_name,
        "season":     season,
        "profile":    profile,
        "status":     {"$in": ["waiting", "processing"]},
    })
    return existing is not None


async def cancel_task_by_id(queue_id: str, api_key: str | None) -> bool:
    try:
        item = await queue_col.find_one({"_id": ObjectId(queue_id)})
    except Exception:
        return False
    if not item:
        return False
    if item.get("status") == "processing" and api_key:
        await cancel_session(api_key)
    result = await queue_col.delete_one({"_id": ObjectId(queue_id)})
    return result.deleted_count > 0


async def cancel_all_user_tasks(user_id: int, api_key: str | None) -> int:
    items = await get_user_queue(user_id)
    if not items:
        return 0
    for item in items:
        if item.get("status") == "processing" and api_key:
            await cancel_session(api_key)
            break
    ids = [item["_id"] for item in items]
    result = await queue_col.delete_many({"_id": {"$in": ids}})
    return result.deleted_count


# ── single quality batch dispatcher ──────────────────────────────────────

async def _dispatch_quality_batch(
    api_key:    str,
    link_items: list[dict],
    queue_id:   str,
    session:    aiohttp.ClientSession,
    sem:        asyncio.Semaphore,
) -> list[dict]:
    """
    Send one quality batch concurrently, capped at CONCURRENCY=5 simultaneous
    requests. No retry — avoids duplicate CSV rows that occur when the API
    processed the request but timed-out before returning a response.
    Each settled link writes a log line + increments done_count in MongoDB.
    """

    async def _one(item: dict) -> dict:
        async with sem:
            r = await process_single_link(
                api_key, item["drive_link"], item["profile"], session
            )

        if r["ok"]:
            ep        = r["data"].get("episode_detected", "")
            fname     = r["data"].get("file", "")
            ep_str    = f"ep{ep} " if ep != "" else ""
            name_str  = fname[:42] if fname else "ok"
            node_logs = r["data"].get("logs", [])
            node_hint = f" ┄ {node_logs[0]}" if node_logs else ""
            log_line  = f"✦ [{item['profile']}] {ep_str}┄ {name_str}{node_hint}"
        else:
            err = r["data"].get("error", r["data"].get("raw", "failed"))
            if isinstance(err, dict):
                err = str(err)
            short_link = item["drive_link"].split("/")[-1][:28]
            log_line   = f"◇ [{item['profile']}] {short_link} ┄ {str(err)[:38]}"

        await queue_col.update_one(
            {"_id": ObjectId(queue_id)},
            {
                "$push": {"live_logs": {"$each": [log_line], "$slice": -10}},
                "$inc":  {"done_count": 1},
            },
        )
        return r

    tasks   = [asyncio.create_task(_one(item)) for item in link_items]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)


# ── notify helper ─────────────────────────────────────────────────────────

async def _notify(user_id: int, text: str):
    if _bot_ref:
        try:
            await _bot_ref.send_message(user_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"_notify {user_id}: {e}")


# ── main processor ────────────────────────────────────────────────────────

async def _process_item(item: dict) -> bool:
    """
    Returns True if a full upload cycle completed (triggers the post-upload
    cooldown in queue_processor). Returns False on early-exit errors.
    """
    queue_id   = str(item["_id"])
    user_id    = item["user_id"]
    anime_name = item["anime_name"]
    season     = item["season"]
    anime_type = item.get("anime_type", "series")
    profile    = item["profile"]
    ep_from    = item["ep_from"]
    ep_to      = item["ep_to"]
    links_sub  = item.get("links_sub",  [])
    links_480  = item.get("links_480",  [])
    links_720  = item.get("links_720",  [])
    links_1080 = item.get("links_1080", [])

    user = await users_col.find_one({"telegram_id": user_id})
    if not user or not user.get("nexus_api_key"):
        logger.error(f"No nexus key for user {user_id}, dropping {queue_id}")
        await delete_queue_item(queue_id)
        return False

    api_key = user["nexus_api_key"]

    # Build ordered quality batches
    if profile == "SUB":
        quality_batches = [("SUB", links_sub)]
    else:
        quality_batches = [
            ("480p",  links_480),
            ("720p",  links_720),
            ("1080p", links_1080),
        ]

    # Total links across all batches
    total = sum(len(lks) for _, lks in quality_batches)

    # Mark processing + reset all tracking fields
    await queue_col.update_one(
        {"_id": ObjectId(queue_id)},
        {"$set": {
            "status":        "processing",
            "started_at":    now_utc(),
            "total_links":   total,
            "done_count":    0,
            "live_logs":     [],
            "progress":      0,
            "current_batch": "",
            "batch_total":   0,
            "batch_offset":  0,
        }},
    )

    await _notify(
        user_id,
        f"✦ ara ara~! <b>{anime_name} S{season}</b> ({profile}) is starting now, master~\n"
        f"◈ {total} link(s) across "
        f"{len([q for q, lks in quality_batches if lks])} quality batch(es)~ ehehe~",
    )

    # ── Step 1: Clear leftover workspace ──────────────────────────────────
    await cancel_session(api_key)

    # ── Step 2: Initialize session ─────────────────────────────────────────
    ok = await init_session(api_key, anime_name, anime_type, season, ep_from, ep_to)
    if not ok:
        logger.error(f"init_session failed for {queue_id}")
        await _notify(
            user_id,
            f"mou~ Session init failed for <b>{anime_name} S{season}</b>~ ◇\n"
            "Please check your Nexus API key or try again later~ ◈",
        )
        await delete_queue_item(queue_id)
        return False

    # ── Step 3: Dispatch per quality — sequential with cooldown ───────────
    #
    # Order: 480p → [10 s] → 720p → [10 s] → 1080p
    # Within each batch: up to 5 concurrent requests (Semaphore).
    # No retry — retrying causes duplicate CSV rows.
    #
    all_results: list[dict] = []
    sem             = asyncio.Semaphore(CONCURRENCY)
    connector       = aiohttp.TCPConnector(limit=CONCURRENCY)
    session_timeout = aiohttp.ClientTimeout(total=NEXUS_TIMEOUT + 60)

    active_batches = [(q, lks) for q, lks in quality_batches if lks]
    done_so_far    = 0  # tracks done_count at start of each batch (for batch_offset)

    async with aiohttp.ClientSession(timeout=session_timeout, connector=connector) as http_session:
        for idx, (quality, links) in enumerate(active_batches):
            items = [{"drive_link": l, "profile": quality} for l in links]

            # Update batch tracking so the queue display knows what's happening
            await queue_col.update_one(
                {"_id": ObjectId(queue_id)},
                {"$set": {
                    "current_batch": quality,
                    "batch_total":   len(items),
                    "batch_offset":  done_so_far,
                }},
            )

            logger.info(f"{queue_id}: dispatching {len(items)} × {quality}")
            batch_results = await _dispatch_quality_batch(
                api_key, items, queue_id, http_session, sem
            )
            all_results.extend(batch_results)
            done_so_far += len(items)

            # 10 s cooldown between batches — skip after last one
            if idx < len(active_batches) - 1:
                logger.info(f"{queue_id}: {quality} done — {QUALITY_COOLDOWN}s cooldown")
                await asyncio.sleep(QUALITY_COOLDOWN)

    succeeded = [r for r in all_results if r["ok"]]
    failed    = [r for r in all_results if not r["ok"]]
    logger.info(f"{queue_id}: {len(succeeded)} ok / {len(failed)} failed")

    # ── Step 4: Generate CSV ───────────────────────────────────────────────
    csv_result = await generate_csv(api_key)

    # ── Step 5: Update query (commit to Nexus backend DB) ─────────────────
    await update_query(api_key)

    # ── Step 6: Purge workspace ────────────────────────────────────────────
    await cancel_session(api_key)

    # ── Step 7: Send summary + CSV to user ────────────────────────────────
    summary = [
        f"✦ <b>{anime_name} S{season}</b> — complete~! kyaa~ ◈\n",
        f"◇ type     : {anime_type}",
        f"◈ profile  : {profile}",
        f"◈ episodes : {ep_from} → {ep_to}",
        f"◈ links    : {len(succeeded)} ✦  /  {len(failed)} ◇ failed",
    ]
    if failed:
        summary.append(f"\n⊹ failed links ({len(failed)}):")
        for r in failed[:5]:
            summary.append(f"  ◇ [{r['profile']}] {r['drive_link'][-50:]}")
        if len(failed) > 5:
            summary.append(f"  ... and {len(failed) - 5} more~")

    await _notify(user_id, "\n".join(summary))

    if csv_result:
        from aiogram.types import BufferedInputFile
        csv_bytes, csv_filename = csv_result
        filename = csv_filename or f"{anime_name}_S{season}_{profile}.csv".replace(" ", "_")
        try:
            await _bot_ref.send_document(
                user_id,
                BufferedInputFile(csv_bytes, filename=filename),
                caption=f"✦ Your CSV is ready, master~ ◈ {anime_name} S{season} ({profile}) ehehe~",
            )
        except Exception as e:
            logger.error(f"send_document error: {e}")
    else:
        await _notify(
            user_id,
            f"mou~ CSV generation failed for <b>{anime_name} S{season}</b>~ ◇\n"
            "The Nexus API didn't return data~ ◈",
        )

    # ── Step 8: Remove from queue + increment stats ────────────────────────
    await delete_queue_item(queue_id)
    await users_col.update_one(
        {"telegram_id": user_id},
        {"$inc": {"total_uploaded": 1, "month_uploaded": 1}},
    )

    return True  # full cycle completed → triggers POST_UPLOAD_WAIT


async def queue_processor():
    logger.info("Queue processor started")
    while True:
        try:
            item = await get_next_waiting()
            if item:
                completed = await _process_item(item)
                if completed:
                    # 5-minute cooldown after each successful upload
                    # (requested by Nexus API owner to avoid overloading the backend)
                    logger.info(
                        f"Upload cycle complete — cooling down {POST_UPLOAD_WAIT}s "
                        f"({POST_UPLOAD_WAIT // 60} min) before next queue item"
                    )
                    await asyncio.sleep(POST_UPLOAD_WAIT)
            else:
                await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Queue processor error: {e}")
            await asyncio.sleep(5)
