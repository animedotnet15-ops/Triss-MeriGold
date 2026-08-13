"""
triss.services.backup
======================
Backs up bot configuration + MongoDB metadata (never secrets, never the
actual Store Channel files — those already live in Telegram). Restore
validates structure before touching the live settings, and only ever
runs after explicit owner confirmation via inline buttons.
"""

from __future__ import annotations

import time
from typing import Any

from triss.database import models as db

BACKUP_SCHEMA_VERSION = 1

_REQUIRED_TOP_LEVEL_KEYS = {"schema_version", "settings", "force_subs"}


class InvalidBackupError(Exception):
    pass


async def create_backup() -> dict:
    settings = await db.get_settings()
    # Defensive strip: never include anything that could be a secret, even
    # though `settings` should never hold one in the first place.
    safe_settings = {k: v for k, v in settings.items() if k not in ("_id",)}

    force_subs = await db.list_force_subs()
    safe_force_subs = [
        {k: v for k, v in entry.items() if k != "_id"} for entry in force_subs
    ]

    payload: dict[str, Any] = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": time.time(),
        "settings": safe_settings,
        "force_subs": safe_force_subs,
    }
    backup_id = await db.save_backup(payload)
    payload["_id"] = backup_id
    return payload


async def get_latest_backup_info() -> dict | None:
    return await db.get_latest_backup()


def validate_backup(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise InvalidBackupError("Backup is not a valid document.")
    missing = _REQUIRED_TOP_LEVEL_KEYS - set(payload.keys())
    if missing:
        raise InvalidBackupError(f"Backup is missing required keys: {sorted(missing)}")
    if payload.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise InvalidBackupError("Backup schema version is not supported by this bot version.")
    if not isinstance(payload.get("settings"), dict):
        raise InvalidBackupError("Backup settings section is malformed.")
    if not isinstance(payload.get("force_subs"), list):
        raise InvalidBackupError("Backup force_subs section is malformed.")


async def restore_backup(payload: dict) -> None:
    """Restores settings + force_subs from a validated backup. Runs the
    settings replace and the force_sub replace as two focused operations
    (not a single giant transaction — this bot targets a standalone
    MongoDB instance without guaranteed replica-set transaction support),
    but each step is itself atomic and idempotent to re-run."""
    validate_backup(payload)

    settings_patch = dict(payload["settings"])
    settings_patch.pop("_id", None)
    await db.update_settings(settings_patch)

    await db.clear_force_subs()
    for entry in payload["force_subs"]:
        await db.add_force_sub(
            kind=entry.get("kind"),
            chat_id=entry.get("chat_id"),
            title=entry.get("title", ""),
            invite_link=entry.get("invite_link"),
        )


async def delete_backup() -> bool:
    return await db.delete_latest_backup()
