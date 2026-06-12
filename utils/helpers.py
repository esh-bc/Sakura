import random
import string
from datetime import datetime, timezone


def generate_key_string() -> str:
    def seg():
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"SAKURA-{seg()}-{seg()}"


def format_expiry(dt: datetime) -> str:
    return ensure_utc(dt).strftime("%d %b %Y")


def ensure_utc(dt: datetime) -> datetime:
    """Attach UTC timezone to naive datetimes returned from MongoDB."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def progress_bar(done: int, total: int, width: int = 12) -> str:
    filled = int((done / total) * width) if total > 0 else 0
    bar = "⬢" * filled + "⬡" * (width - filled)
    return bar


def elapsed_str(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def is_drive_link(url: str) -> bool:
    url = url.strip()
    return "drive.google.com" in url or "docs.google.com" in url


def parse_links(text: str) -> list[str]:
    lines = text.strip().splitlines()
    links = []
    for line in lines:
        for token in line.split():
            token = token.strip()
            if token.startswith("http"):
                links.append(token)
    return links


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
