import asyncio
import logging
import aiohttp
from config import NEXUS_BASE_URL, NEXUS_TIMEOUT

logger = logging.getLogger(__name__)


def _headers(api_key: str) -> dict:
    return {
        "X-Nexus-API-Key": api_key,
        "Content-Type": "application/json",
    }


async def cancel_session(api_key: str) -> bool:
    """Purge the current workspace on the Nexus server."""
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{NEXUS_BASE_URL}?action=cancel",
                headers=_headers(api_key),
            ) as resp:
                ok = resp.status == 200
                logger.info(f"cancel_session → {resp.status}")
                return ok
    except Exception as e:
        logger.error(f"cancel_session error: {e}")
        return False


async def init_session(
    api_key: str,
    anime_name: str,
    anime_type: str,
    season: int,
    from_ep: int,
    to_ep: int,
) -> bool:
    """
    anime_type: "series" or "movie" — maps directly to the API `type` field.
    Profile/quality is supplied per-link in process_link, not here.
    """
    payload = {
        "anime_name": anime_name,
        "type":       anime_type,
        "season":     season,
        "from_ep":    from_ep,
        "to_ep":      to_ep,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{NEXUS_BASE_URL}?action=init_session",
                headers=_headers(api_key),
                json=payload,
            ) as resp:
                body = await resp.text()
                logger.info(f"init_session status={resp.status} body={body[:200]}")
                return resp.status == 200
    except Exception as e:
        logger.error(f"init_session error: {e}")
        return False


async def process_single_link(
    api_key:    str,
    drive_link: str,
    profile:    str,
    session:    aiohttp.ClientSession,
) -> dict:
    """
    Payload: { "profile": "1080p", "drive_link": "https://drive.google.com/..." }
    Response includes: status, file, episode_detected, assigned_slot, logs[]
    """
    payload = {"profile": profile, "drive_link": drive_link}
    try:
        timeout = aiohttp.ClientTimeout(total=NEXUS_TIMEOUT)
        async with session.post(
            f"{NEXUS_BASE_URL}?action=process_link",
            headers=_headers(api_key),
            json=payload,
            timeout=timeout,
        ) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {"raw": await resp.text()}
            ok = resp.status == 200 and data.get("status") == "success"
            return {
                "drive_link": drive_link,
                "profile":    profile,
                "status":     resp.status,
                "ok":         ok,
                "data":       data,
            }
    except Exception as e:
        logger.error(f"process_link error for {drive_link[-40:]}: {e}")
        return {
            "drive_link": drive_link,
            "profile":    profile,
            "status":     0,
            "ok":         False,
            "data":       {"error": str(e)},
        }


async def generate_csv(api_key: str) -> tuple[bytes, str] | None:
    """
    API returns JSON:
      { "status": "success", "filename": "...", "csv_data": "col,...\\n..." }
    Returns (csv_bytes, filename) or None on failure.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{NEXUS_BASE_URL}?action=generate_csv",
                headers=_headers(api_key),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"generate_csv HTTP {resp.status}")
                    return None
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    raw = await resp.text()
                    logger.error(f"generate_csv JSON parse error, raw={raw[:200]}")
                    return None

                if data.get("status") != "success":
                    logger.error(f"generate_csv non-success: {data}")
                    return None

                csv_str = data.get("csv_data", "")
                if not csv_str:
                    logger.error("generate_csv: csv_data field is empty")
                    return None

                logger.info(f"generate_csv: {len(csv_str)} chars, filename={data.get('filename')}")
                return csv_str.encode("utf-8"), data.get("filename", "")
    except Exception as e:
        logger.error(f"generate_csv error: {e}")
        return None


async def update_query(api_key: str) -> bool:
    """
    Called after generate_csv — tells the Nexus server to commit/finalize
    the processed data into its backend database before the session is cleared.
    Must be called BEFORE cancel_session.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{NEXUS_BASE_URL}?action=update_query",
                headers=_headers(api_key),
            ) as resp:
                body = await resp.text()
                logger.info(f"update_query → {resp.status} body={body[:200]}")
                return resp.status == 200
    except Exception as e:
        logger.error(f"update_query error: {e}")
        return False


async def ping_nexus(api_key: str) -> bool:
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{NEXUS_BASE_URL}?action=cancel",
                headers=_headers(api_key),
            ) as resp:
                return resp.status == 200
    except Exception:
        return False
