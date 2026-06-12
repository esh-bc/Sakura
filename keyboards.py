from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb(key_expires: str, nexus_configured: bool) -> InlineKeyboardMarkup:
    nexus_btn = InlineKeyboardButton(
        text="✦ Nexus API Key ✓" if nexus_configured else "△ Nexus API Key",
        callback_data="nexus_key",
        style="success" if nexus_configured else "danger",
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◈ Anime Upload", callback_data="anime_upload", style="primary")],
        [InlineKeyboardButton(text="◇ My Queue", callback_data="my_queue", style="primary"),
         InlineKeyboardButton(text="○ My Stats", callback_data="my_stats", style="primary")],
        [InlineKeyboardButton(text="◈ Status", callback_data="status_check", style="primary")],
        [nexus_btn],
    ])


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="△ Cancel", callback_data="cancel_flow", style="danger")],
    ])


def anime_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◈ Series", callback_data="type_series", style="primary"),
            InlineKeyboardButton(text="◇ Movie",  callback_data="type_movie",  style="primary"),
        ],
        [InlineKeyboardButton(text="△ Cancel", callback_data="cancel_flow", style="danger")],
    ])


def profile_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◈ SUB", callback_data="profile_sub", style="primary"),
            InlineKeyboardButton(text="◈ DUB", callback_data="profile_dub", style="primary"),
        ],
        [InlineKeyboardButton(text="△ Cancel", callback_data="cancel_flow", style="danger")],
    ])


def links_done_kb(label: str = "next") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✦ Done → {label}", callback_data="links_done", style="success")],
        [InlineKeyboardButton(text="△ Cancel", callback_data="cancel_flow", style="danger")],
    ])


def links_done_skip_kb(quality: str, next_label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✦ Done → {next_label}", callback_data="links_done",           style="success"),
            InlineKeyboardButton(text=f"◇ Skip {quality}",       callback_data=f"links_skip:{quality}", style="primary"),
        ],
        [InlineKeyboardButton(text="△ Cancel", callback_data="cancel_flow", style="danger")],
    ])


def confirm_upload_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◈ Start Upload", callback_data="start_upload", style="success")],
        [InlineKeyboardButton(text="△ Cancel", callback_data="cancel_flow", style="danger")],
    ])


def duplicate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Add Anyway", callback_data="dup_add", style="success"),
         InlineKeyboardButton(text="△ No",          callback_data="dup_no",  style="danger")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▷ Back", callback_data="main_menu", style="primary")],
    ])


def queue_nav_kb(page: int, total_pages: int, cancel_items: list[dict] | None = None) -> InlineKeyboardMarkup:
    """
    cancel_items: [{"id": "<queue_id>", "label": "Demon Slayer S1 [DUB]"}, ...]
    Adds one △ Cancel button per item, then pagination, then △ Cancel All.
    """
    buttons = []

    # Per-item cancel buttons
    if cancel_items:
        for ci in cancel_items:
            buttons.append([
                InlineKeyboardButton(
                    text=f"△ Cancel  {ci['label']}",
                    callback_data=f"cancel_task:{ci['id']}",
                    style="danger",
                )
            ])

    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◁ prev", callback_data=f"queue_page:{page - 1}", style="primary"))
    nav.append(InlineKeyboardButton(text="○ Refresh", callback_data=f"queue_page:{page}", style="primary"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▷ next", callback_data=f"queue_page:{page + 1}", style="primary"))
    if nav:
        buttons.append(nav)

    # Cancel all (only shown when there are tasks)
    if cancel_items:
        buttons.append([
            InlineKeyboardButton(text="△ Cancel All Tasks", callback_data="cancel_all_tasks", style="danger")
        ])

    buttons.append([InlineKeyboardButton(text="▷ Back", callback_data="main_menu", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def task_cancel_confirm_kb(queue_id: str) -> InlineKeyboardMarkup:
    """Confirmation keyboard for cancelling a single task."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✦ Yes, Cancel It",  callback_data=f"cancel_task_yes:{queue_id}", style="danger"),
            InlineKeyboardButton(text="◇ No, Keep It",     callback_data="my_queue",                    style="success"),
        ],
    ])


def cancel_all_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard for cancelling ALL tasks."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✦ Yes, Nuke All",  callback_data="cancel_all_tasks_yes", style="danger"),
            InlineKeyboardButton(text="◇ No, Keep Them",  callback_data="my_queue",             style="success"),
        ],
    ])


def admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Generate Key",   callback_data="admin_gen_key",      style="success")],
        [InlineKeyboardButton(text="◈ View All Keys",  callback_data="admin_view_keys",    style="primary")],
        [InlineKeyboardButton(text="△ Revoke Key",     callback_data="admin_revoke_key",   style="danger")],
        [InlineKeyboardButton(text="○ Active Users",   callback_data="admin_active_users", style="primary")],
    ])


def admin_duration_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="7 days",  callback_data="admin_dur:7",   style="primary"),
            InlineKeyboardButton(text="30 days", callback_data="admin_dur:30",  style="primary"),
        ],
        [
            InlineKeyboardButton(text="90 days",  callback_data="admin_dur:90",  style="primary"),
            InlineKeyboardButton(text="365 days", callback_data="admin_dur:365", style="primary"),
        ],
        [InlineKeyboardButton(text="△ Cancel", callback_data="admin_cancel", style="danger")],
    ])


def nexus_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="△ Cancel", callback_data="main_menu", style="danger")],
    ])
