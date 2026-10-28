from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
_FALLBACK_MAILMASTER_ROOT = Path(r"E:\MailMasterData")
_DRAFT_MAILBOX_TYPE = 2
_DRAFT_FOLDER_KEYWORDS = ("draft", "\u8349\u7a3f")



def _decode_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin1"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _default_profile_path() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Netease" / "MailMaster" / "profile.ini"
    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        return Path(user_profile) / "AppData" / "Local" / "Netease" / "MailMaster" / "profile.ini"
    return None


def discover_mailmaster_root_from_profile(profile_path: Path | None = None) -> Path | None:
    candidate = profile_path or _default_profile_path()
    if candidate is None or not candidate.exists():
        return None
    try:
        lines = candidate.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DataPath" and value.strip():
            return Path(value.strip()).expanduser()
    return None


def default_mailmaster_root() -> Path:
    discovered = discover_mailmaster_root_from_profile()
    return discovered or _FALLBACK_MAILMASTER_ROOT


def _sqlite_read_uris(db_path: Path, *, nolock: bool = False) -> list[str]:
    base_uri = db_path.resolve().as_uri()
    # Honor SQLite locking; do not bypass a live client's write lock.
    return [f"{base_uri}?mode=ro"]


def _connect_bytes(db_path: Path, *, nolock: bool = False) -> sqlite3.Connection:
    last_error: sqlite3.OperationalError | None = None
    for uri in _sqlite_read_uris(db_path, nolock=nolock):
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.text_factory = bytes
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA schema_version").fetchone()
            return conn
        except sqlite3.OperationalError as exc:
            last_error = exc
            with suppress(Exception):
                conn.close()
            if nolock and "unable to open database file" in str(exc).lower():
                continue
            raise
    if last_error is not None:
        raise last_error
    raise sqlite3.OperationalError("unable to open database file")


def _is_locked_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _fetchall_bytes(
    db_path: Path,
    sql: str,
    params: tuple[Any, ...] = (),
    *,
    nolock: bool = False,
) -> list[sqlite3.Row]:
    try:
        with closing(_connect_bytes(db_path, nolock=nolock)) as conn:
            return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if not _is_locked_error(exc):
            raise
    raise RuntimeError(
        "MailMaster 数据库当前被客户端占用；请先关闭或完成同步后重试。"
        "联系人 MVP 不会复制邮件数据库。"
    )


def _fetchone_bytes(
    db_path: Path,
    sql: str,
    params: tuple[Any, ...] = (),
    *,
    nolock: bool = False,
) -> sqlite3.Row | None:
    try:
        with closing(_connect_bytes(db_path, nolock=nolock)) as conn:
            return conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError as exc:
        if not _is_locked_error(exc):
            raise
    raise RuntimeError(
        "MailMaster 数据库当前被客户端占用；请先关闭或完成同步后重试。"
        "联系人 MVP 不会复制邮件数据库。"
    )


@dataclass(frozen=True)
class MailMasterAccountProfile:
    account_id: int
    account_email: str
    data_path: Path
    drafts_folder_id: str = ""
    drafts_folder_name: str = ""
    mailboxes: dict[str, str] = field(default_factory=dict)




def discover_mailmaster_account_profiles(root_dir: Path) -> list[MailMasterAccountProfile]:
    app_db = root_dir / "app.db"
    if not app_db.exists():
        raise RuntimeError("MailMaster app.db not found")

    try:
        rows = _fetchall_bytes(
            app_db,
            "SELECT ID, Email, DataPath FROM Account "
            "WHERE COALESCE(Valid, 1) = 1 ORDER BY LOWER(COALESCE(Email, '')), ID",
        )
    except sqlite3.Error as exc:
        raise RuntimeError("MailMaster account data not ready") from exc

    profiles: list[MailMasterAccountProfile] = []
    for row in rows:
        account_id = int(row["ID"])
        resolved_email = _decode_text(row["Email"]).strip().lower()
        data_path = Path(_decode_text(row["DataPath"]).strip())
        mail_db = data_path / "mail.db"
        if not mail_db.exists():
            profiles.append(
                MailMasterAccountProfile(
                    account_id=account_id,
                    account_email=resolved_email,
                    data_path=data_path,
                )
            )
            continue

        mailboxes: dict[str, str] = {}
        drafts_folder_id = ""
        drafts_folder_name = ""
        try:
            mailbox_rows = _fetchall_bytes(mail_db, "SELECT Id, DisplayName, Type FROM Mailbox", nolock=True)
        except sqlite3.Error:
            mailbox_rows = []
        for mailbox_row in mailbox_rows:
            mailbox_id = _decode_text(mailbox_row["Id"]).strip()
            display_name = _decode_text(mailbox_row["DisplayName"]).strip() or mailbox_id
            mailbox_type = int(mailbox_row["Type"] or 0)
            if mailbox_id:
                mailboxes[mailbox_id] = display_name
            if mailbox_type == _DRAFT_MAILBOX_TYPE and not drafts_folder_name:
                drafts_folder_id = mailbox_id
                drafts_folder_name = display_name
        if not drafts_folder_name:
            for mailbox_id, display_name in mailboxes.items():
                lowered = f"{mailbox_id} {display_name}".lower()
                if any(keyword in lowered for keyword in _DRAFT_FOLDER_KEYWORDS):
                    drafts_folder_id = mailbox_id
                    drafts_folder_name = display_name
                    break

        profiles.append(
            MailMasterAccountProfile(
                account_id=account_id,
                account_email=resolved_email,
                data_path=data_path,
                drafts_folder_id=drafts_folder_id,
                drafts_folder_name=drafts_folder_name,
                mailboxes=mailboxes,
            )
        )
    return profiles
