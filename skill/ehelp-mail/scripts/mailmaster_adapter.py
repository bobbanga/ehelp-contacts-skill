from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, suppress
import zlib
from datetime import datetime, timezone
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any

from mailmaster_discovery import _sqlite_read_uris
from models import DraftRequest, DraftResult, MailAccount, MailDetail, MailSearchResponse, MailSummary

_MAIL_META_COLUMNS: dict[str, frozenset[str]] = {}
_IDENTIFIER_TOKEN = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9._/-]{5,}$")


def _keyword_matches_text(text: str, keyword: str) -> bool:
    needle = str(keyword or "").strip()
    if not needle:
        return False
    haystack = str(text or "")
    if _IDENTIFIER_TOKEN.fullmatch(needle):
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])",
                haystack,
                flags=re.IGNORECASE,
            )
        )
    return needle.casefold() in haystack.casefold()


def _keyword_matches_summary(summary: MailSummary, keyword: str) -> bool:
    return _keyword_matches_text(
        "\n".join(
            (
                summary.subject,
                summary.from_addr,
                summary.from_name,
                summary.to_addr,
                summary.cc_addr,
            )
        ),
        keyword,
    )


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


def _strip_html(value: str) -> str:
    text = value or ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)</div\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_body_text(value: str) -> str:
    text = _strip_html(value)
    for marker in ("---- 回复的原邮件 ----", "----- Original message summary -----"):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    lines = [line.strip() for line in text.splitlines()]
    compact = []
    blank = False
    non_empty_count = 0
    for line in lines:
        if re.fullmatch(r"[-_=*]{8,}", line) and non_empty_count >= 1:
            break
        if non_empty_count >= 2 and line.startswith(("发件人：", "发件人:", "From:", "收件人：", "To:", "主题：", "Subject:")):
            break
        if not line:
            if not blank:
                compact.append("")
            blank = True
            continue
        compact.append(line)
        blank = False
        non_empty_count += 1
    return "\n".join(compact).strip()


def _parse_jsonish_list(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [part.strip() for part in text.split(";") if part.strip()]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _parse_address_entry(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "mail": str(value.get("mail") or "").strip(),
            "name": str(value.get("name") or "").strip(),
        }
    text = _decode_text(value).strip()
    if not text or text == "{}":
        return {"mail": "", "name": ""}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"mail": text, "name": ""}
    if isinstance(parsed, str):
        return _parse_address_entry(parsed)
    if isinstance(parsed, dict):
        return {
            "mail": str(parsed.get("mail") or "").strip(),
            "name": str(parsed.get("name") or "").strip(),
        }
    return {"mail": "", "name": ""}


def _parse_address_list(value: Any) -> list[dict[str, str]]:
    text = _decode_text(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        single = _parse_address_entry(text)
        return [single] if single["mail"] or single["name"] else []
    if isinstance(parsed, list):
        items = [_parse_address_entry(item) for item in parsed]
        return [item for item in items if item["mail"] or item["name"]]
    single = _parse_address_entry(parsed)
    return [single] if single["mail"] or single["name"] else []


def _format_timestamp(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        number = int(raw)
    except ValueError:
        return raw
    if number > 10_000_000_000:
        number = number / 1000
    return datetime.fromtimestamp(number, tz=timezone.utc).isoformat(timespec="seconds")


@dataclass
class MailMasterAccount:
    account_id: int
    account_email: str
    data_path: Path


@dataclass
class MailMasterMailAdapter:
    source_kind = "mailmaster"

    def read_contact_batch(self, owner: str, scan: dict, limit: int) -> dict:
        from contact_source import read_mailmaster_batch
        return read_mailmaster_batch(self, owner, scan, limit)

    root_dir: Path
    draft_sink: Any
    body_scan_limit: int = 500

    _FOLDER_ALIASES = {
        "INBOX": {"INBOX"},
        "SENT": {"SENT", "&XFJT0ZAB-"},
        "DRAFTS": {"DRAFTS", "&G0L6P3UX-"},
        "TRASH": {"TRASH", "&XFJSIJZK-"},
        "ALL": set(),
    }

    def _app_db_path(self) -> Path:
        return self.root_dir / "app.db"

    def _ensure_root_ready(self) -> None:
        if not self.root_dir.exists():
            raise RuntimeError("MailMaster root not found")
        if not self._app_db_path().exists():
            raise RuntimeError("MailMaster app.db not found")

    def _connect(self, db_path: Path, *, nolock: bool = False) -> sqlite3.Connection:
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

    def _is_locked_error(self, exc: sqlite3.OperationalError) -> bool:
        message = str(exc).lower()
        return "database is locked" in message or "database table is locked" in message

    def _fetchall(
        self,
        db_path: Path,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        nolock: bool = False,
    ) -> list[sqlite3.Row]:
        try:
            with closing(self._connect(db_path, nolock=nolock)) as conn:
                return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            if not self._is_locked_error(exc):
                raise
        raise RuntimeError(
            "MailMaster 数据库当前被客户端占用；请先关闭或完成同步后重试。"
            "联系人 MVP 不会复制邮件数据库。"
        )

    def _fetchone(
        self,
        db_path: Path,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        nolock: bool = False,
    ) -> sqlite3.Row | None:
        try:
            with closing(self._connect(db_path, nolock=nolock)) as conn:
                return conn.execute(sql, params).fetchone()
        except sqlite3.OperationalError as exc:
            if not self._is_locked_error(exc):
                raise
        raise RuntimeError(
            "MailMaster 数据库当前被客户端占用；请先关闭或完成同步后重试。"
            "联系人 MVP 不会复制邮件数据库。"
        )

    def _load_accounts(self) -> dict[int, MailMasterAccount]:
        self._ensure_root_ready()
        accounts: dict[int, MailMasterAccount] = {}
        rows = self._fetchall(
            self._app_db_path(),
            "SELECT ID, Email, DataPath, Valid FROM Account WHERE COALESCE(Valid, 1) = 1",
        )
        for row in rows:
            account_id = int(row["ID"])
            account_email = _decode_text(row["Email"]).strip().lower()
            data_path = Path(_decode_text(row["DataPath"]).strip())
            accounts[account_id] = MailMasterAccount(
                account_id=account_id,
                account_email=account_email,
                data_path=data_path,
            )
        return accounts

    def _find_account_by_email(self, account_email: str) -> MailMasterAccount:
        normalized = str(account_email or "").strip().lower()
        if not normalized:
            raise ValueError("account_email is required for MailMaster draft operations")
        for account in self._load_accounts().values():
            if account.account_email == normalized:
                return account
        raise RuntimeError("MailMaster account data not ready")

    def _resolve_accounts(self, account_id: int | None = None) -> list[MailMasterAccount]:
        accounts = self._load_accounts()
        if account_id is not None:
            account = accounts.get(int(account_id))
            return [account] if account else []
        return sorted(accounts.values(), key=lambda item: (item.account_email, item.account_id))

    def _mail_db_path(self, account: MailMasterAccount) -> Path:
        return account.data_path / "mail.db"


    def _is_account_ready(self, account: MailMasterAccount) -> bool:
        return self._mail_db_path(account).is_file()

    def _ensure_account_ready(self, account: MailMasterAccount) -> None:
        if not self._is_account_ready(account):
            raise RuntimeError("MailMaster account data not ready")

    def _resolve_account_by_email(self, account_email: str) -> MailMasterAccount:
        account = self._find_account_by_email(account_email)
        self._ensure_account_ready(account)
        return account

    def list_accounts(self) -> list[MailAccount]:
        # Contact selection needs app.db metadata and file existence only.
        # Probing Mailbox in every mail.db couples A to an unselected B's lock.
        return [
            MailAccount(account_id=account.account_id, account_email=account.account_email,
                        data_path=str(account.data_path), ready=self._is_account_ready(account))
            for account in self._resolve_accounts()
        ]

    def _resolve_folder_values(self, folder: str | None) -> tuple[str | None, set[str]]:
        normalized = str(folder or "INBOX").strip()
        upper = normalized.upper()
        aliases = self._FOLDER_ALIASES.get(upper)
        if aliases is None:
            return normalized, {normalized.upper()}
        if upper == "ALL":
            return None, set()
        return normalized, aliases

    def _build_where_clause(
        self,
        *,
        folder: str | None,
        date: str | None = None,
        unread_only: bool = False,
        keyword: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses = []
        params: list[Any] = []
        raw_folder, aliases = self._resolve_folder_values(folder)
        if raw_folder is not None:
            placeholders = ", ".join("?" for _ in aliases)
            clauses.append(f"UPPER(COALESCE(Mailbox, '')) IN ({placeholders})")
            params.extend(sorted(aliases))
        if date:
            clauses.append("date(datetime(COALESCE(OrigDate, ReceivedDate), 'unixepoch')) = date(?)")
            params.append(date)
        if unread_only:
            clauses.append("COALESCE(Unread, 0) = 1")
        if keyword:
            like_value = f"%{keyword}%"
            clauses.append(
                "("
                "COALESCE(Subject, '') LIKE ? OR COALESCE(Froms, '') LIKE ? OR "
                "COALESCE(Sender, '') LIKE ? OR COALESCE(Tos, '') LIKE ?"
                ")"
            )
            params.extend([like_value] * 4)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def _to_summary(self, account: MailMasterAccount, row: sqlite3.Row) -> MailSummary:
        sender = _parse_address_entry(row["Sender"])
        froms = _parse_address_entry(row["Froms"])
        tos = _parse_address_list(row["Tos"])
        ccs = _parse_address_list(row["Ccs"])
        subject = _decode_text(row["Subject"]).strip()
        primary_from = froms if froms["mail"] or froms["name"] else sender
        return MailSummary(
            id=int(row["LocalId"]),
            message_id=_decode_text(row["MessageId"]).strip() or _decode_text(row["RemoteId"]).strip(),
            references=_decode_text(row["ReferenceIds"]).strip(),
            in_reply_to=_decode_text(row["InReplyTos"]).strip(),
            account_id=account.account_id,
            account_email=account.account_email,
            folder=_decode_text(row["Mailbox"]).strip() or "INBOX",
            subject=subject,
            from_addr=primary_from["mail"],
            from_name=primary_from["name"] or primary_from["mail"],
            to_addr="; ".join(item["mail"] for item in tos if item["mail"]),
            cc_addr="; ".join(item["mail"] for item in ccs if item["mail"]),
            date=_format_timestamp(row["OrigDate"] or row["ReceivedDate"]),
            is_read=not bool(int(row["Unread"] or 0)),
            body_preview="",
        )

    def _mail_meta_columns(self, account: MailMasterAccount) -> frozenset[str]:
        cache_key = str(self._mail_db_path(account))
        cached = _MAIL_META_COLUMNS.get(cache_key)
        if cached is not None:
            return cached
        columns = frozenset(
            _decode_text(row["name"]).strip()
            for row in self._fetchall(
                self._mail_db_path(account),
                "PRAGMA table_info(MailMeta)",
                nolock=True,
            )
        )
        _MAIL_META_COLUMNS[cache_key] = columns
        return columns

    def _thread_header_select(self, account: MailMasterAccount) -> str:
        columns = self._mail_meta_columns(account)
        references = "ReferenceIds" if "ReferenceIds" in columns else "'' AS ReferenceIds"
        in_reply_to = "InReplyTos" if "InReplyTos" in columns else "'' AS InReplyTos"
        return f"{references}, {in_reply_to}"

    def _fetch_mail_rows(
        self,
        *,
        account: MailMasterAccount,
        folder: str | None,
        limit: int,
        date: str | None = None,
        unread_only: bool = False,
        keyword: str | None = None,
    ) -> list[sqlite3.Row]:
        where_sql, params = self._build_where_clause(
            folder=folder,
            date=date,
            unread_only=unread_only,
            keyword=keyword,
        )
        sql = (
            "SELECT LocalId, RemoteId, MessageId, "
            f"{self._thread_header_select(account)}, "
            "OrigDate, ReceivedDate, Mailbox, Subject, "
            "Froms, Sender, Tos, Ccs, Unread "
            "FROM MailMeta"
            f"{where_sql} "
            "ORDER BY COALESCE(ReceivedDate, OrigDate) DESC LIMIT ?"
        )
        params.append(max(1, min(int(limit), 500)))
        return self._fetchall(self._mail_db_path(account), sql, tuple(params), nolock=True)










    def list_emails_for_account_email(
        self,
        *,
        account_email: str,
        folder: str = "INBOX",
        limit: int = 20,
        date: str | None = None,
        unread_only: bool = False,
    ) -> MailSearchResponse:
        account = self._resolve_account_by_email(account_email)
        rows = self._fetch_mail_rows(
            account=account,
            folder=folder,
            limit=limit,
            date=date,
            unread_only=unread_only,
        )
        emails = [self._to_summary(account, row) for row in rows]
        return MailSearchResponse(total=len(emails), source="mailmaster_local", emails=emails)








