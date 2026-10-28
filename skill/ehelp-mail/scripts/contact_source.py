"""Bounded keyset reads. The client database is always opened mode=ro."""
from __future__ import annotations

import hashlib
from contextlib import closing
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from mailmaster_adapter import MailMasterMailAdapter


class ContactHeaderSource(Protocol):
    source_kind: str

    def list_accounts(self): ...

    def read_contact_batch(self, owner: str, scan: dict, limit: int) -> dict: ...


def read_batch(adapter: ContactHeaderSource, owner: str, scan: dict, limit: int) -> dict:
    return adapter.read_contact_batch(owner, scan, limit)


def read_mailmaster_batch(adapter: MailMasterMailAdapter, owner: str, scan: dict, limit: int) -> dict:
    account = adapter._resolve_account_by_email(owner)
    db = adapter._mail_db_path(account).resolve()
    source_id = hashlib.sha256(str(db).casefold().encode()).hexdigest()
    # MailMaster stores seconds or milliseconds. Invalid/undated rows are not
    # evidence that a time interval has been covered.
    raw = "CAST(COALESCE(NULLIF(OrigDate, 0), ReceivedDate) AS REAL)"
    ts = f"(CASE WHEN {raw}>10000000000 THEN {raw}/1000.0 ELSE {raw} END)"
    where, params = adapter._build_where_clause(folder=scan["folder"])
    clauses = [where[7:]] if where else []
    clauses.extend([f"{ts}>=?", f"{ts}<=?"])
    params += [scan["cutoff"], scan["until"]]
    cursor = scan.get("cursor")
    if cursor:
        clauses.append(f"({ts}<? OR ({ts}=? AND rowid<?))")
        params += [cursor[0], cursor[0], cursor[1]]
    sql = ("SELECT rowid AS ScanId, LocalId, RemoteId, MessageId, "
           f"{adapter._thread_header_select(account)}, "
           "OrigDate, ReceivedDate, Mailbox, Subject, Froms, Sender, Tos, Ccs, Unread, "
           f"{ts} AS ScanTime FROM MailMeta WHERE " + " AND ".join(clauses) +
           f" ORDER BY {ts} DESC, rowid DESC LIMIT ?")
    try:
        with closing(adapter._connect(db)) as conn:
            conn.execute("BEGIN")
            chosen = conn.execute(sql, tuple(params + [limit])).fetchall()
            more = False
            if chosen:
                # Only test existence beyond the cursor; never read an extra
                # mail header beyond the customer's batch limit.
                tail = chosen[-1]
                next_sql = ("SELECT 1 FROM MailMeta WHERE " + " AND ".join(clauses) +
                            f" AND ({ts}<? OR ({ts}=? AND rowid<?)) LIMIT 1")
                more = conn.execute(next_sql, tuple(params + [tail["ScanTime"], tail["ScanTime"], tail["ScanId"]])).fetchone() is not None
    except sqlite3.OperationalError as exc:
        if adapter._is_locked_error(exc):
            raise RuntimeError("邮箱大师正在占用数据库；请等同步完成后重试。不会复制或修改源库。") from exc
        raise
    messages = []
    for row in chosen:
        message = adapter._to_summary(account, row)
        # RemoteId is folder-scoped, not a RFC Message-ID. Never use it to
        # merge different folders' messages in the persistent ledger.
        raw_id = row["MessageId"]
        message.message_id = raw_id.decode("utf-8", errors="replace") if isinstance(raw_id, bytes) else str(raw_id or "")
        message.date = datetime.fromtimestamp(row["ScanTime"], tz=timezone.utc).isoformat()
        messages.append(message)
    return {"source_id": source_id, "source_path": str(db), "source_kind": "mailmaster", "messages": messages,
            "cursor": [chosen[-1]["ScanTime"], chosen[-1]["ScanId"]] if chosen else cursor,
            "more": more}
