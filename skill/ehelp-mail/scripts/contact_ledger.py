"""Local header-derived contact ledger. No mail bodies, credentials or network."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from contact_core import (_normalize_email, _parse_datetime, _subject_key, _decode_header,
                           _candidate_type, _direction, _importance, build_contact_preview)
from contact_source import read_batch
from models import MailSearchResponse
from lifecycle import package_identity

SCHEMA = (
    "CREATE TABLE meta (version INTEGER NOT NULL, revision INTEGER NOT NULL)",
    "INSERT INTO meta VALUES (1, 0)",
    "CREATE TABLE accounts (owner TEXT PRIMARY KEY, source_id TEXT NOT NULL, scan TEXT NOT NULL, last_batch TEXT)",
    "CREATE TABLE messages (owner TEXT, key TEXT, signature TEXT NOT NULL, date TEXT NOT NULL, subject TEXT NOT NULL, PRIMARY KEY(owner,key))",
    "CREATE TABLE events (owner TEXT, key TEXT, email TEXT, name TEXT, received INTEGER, sent INTEGER, cc INTEGER, PRIMARY KEY(owner,key,email))",
    "CREATE INDEX events_contact ON events(owner,email)",
    "CREATE TABLE annotations (owner TEXT, email TEXT, name TEXT, followed INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', PRIMARY KEY(owner,email))",
    "CREATE TABLE batches (id TEXT PRIMARY KEY, owner TEXT, receipt TEXT NOT NULL)",
    "CREATE TABLE changes (batch TEXT, email TEXT, kind TEXT, PRIMARY KEY(batch,email))",
)


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _initialize(conn):
    for statement in SCHEMA:
        conn.execute(statement)


def _check(conn):
    if conn.execute("SELECT version FROM meta").fetchone()[0] != 1:
        raise ValueError("台账版本不兼容；请保留原文件，使用匹配版本。")


@contextmanager
def ledger_read(path: Path):
    if path.exists() and path.stat().st_size:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    else:
        conn = sqlite3.connect(":memory:")
        _initialize(conn)
    conn.row_factory = sqlite3.Row
    try:
        _check(conn)
        conn.execute("BEGIN") if not conn.in_transaction else None
        yield conn
    finally:
        conn.close()


def _revision(conn):
    return conn.execute("SELECT revision FROM meta").fetchone()[0]


def _scan(conn, owner, folder, days, now, restart):
    existing = conn.execute("SELECT * FROM accounts WHERE owner=?", (owner,)).fetchone()
    previous = json.loads(existing["scan"]) if existing else None
    if previous and not previous["complete"] and not restart:
        if previous["folder"] != folder or previous["days"] != days:
            raise ValueError("还有未完成的范围；沿用原范围继续，或明确加 --restart-scan 重新开始。已整理的联系人会保留。")
        return previous, existing
    return {"folder": folder, "days": days, "cutoff": now - days * 86400,
            "until": now, "cursor": None, "complete": False, "scanned": 0,
            "conflicts": 0, "skipped": 0}, existing


def _message_record(message, owner, now, days, source_id):
    # Account markers are not inferred from the requested mailbox.
    if _normalize_email(message.account_email) != owner:
        return None
    mid = str(message.message_id or "").strip().strip("<>")
    if not mid and not message.id:
        return None  # no stable identity: do not invent a merge key
    key = digest(["mid", mid]) if mid else digest(["local", source_id, message.folder, message.id])
    payload = build_contact_preview(
        MailSearchResponse(source="mailmaster_local", total=1, emails=[message]),
        account_email=owner, folder="ALL", days=days, email_limit=1, limit=100000,
        now=datetime.fromtimestamp(now, timezone.utc))
    if payload["emails_in_scope"] != 1:
        return None
    date = _parse_datetime(message.date).isoformat(timespec="seconds")
    # Names are not identity; names differing between copies do not duplicate a
    # message. Conflicting dates/participants/subject are surfaced for review.
    events = [{k: c[k] for k in ("email", "name", "received_count", "sent_count", "co_recipient_count")}
              for c in payload["candidates"]]
    subject = _decode_header(message.subject)
    signature = digest([date, subject, sorted(
        [e["email"], e["received_count"], e["sent_count"], e["co_recipient_count"]] for e in events)])
    return {"key": key, "signature": signature, "date": date,
            "subject": subject, "events": events}


def scan_summary(scan: dict) -> dict:
    """Public coverage fields only: no contact rows, subjects or source paths."""
    return {
        "scan_summary_available": True,
        "scan_complete": scan["complete"], "scan_total_read": scan["scanned"],
        "scan_conflicting_mail_count": scan["conflicts"],
        "scan_skipped_mail_count": scan["skipped"],
        "scan_requires_review": bool(scan["conflicts"] or scan["skipped"]),
        "window_start": datetime.fromtimestamp(scan["cutoff"], timezone.utc).isoformat(),
        "window_end": datetime.fromtimestamp(scan["until"], timezone.utc).isoformat(),
        "window_days": scan["days"], "folder": scan["folder"],
        "source": scan.get("source_kind", "mailmaster") + "_local",
        "scan_outside_window_count": scan.get("outside_window", 0),
        "scan_order": "local_id_desc" if scan.get("source_kind") == "foxmail" else "date_desc",
    }


def prepare(adapter, path: Path, owner: str, *, folder="ALL", days=7, limit=100,
            now=None, restart=False):
    owner = _normalize_email(owner)
    if not owner or not 1 <= days <= 36500 or not 1 <= limit <= 500:
        raise ValueError("请选择一个邮箱；days 为 1–36500，email-limit 为 1–500。")
    now = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    folder = folder.upper().strip()
    with ledger_read(path) as conn:
        scan, existing = _scan(conn, owner, folder, days, now, restart)
        batch = read_batch(adapter, owner, scan, limit)
        source_path = Path(batch["source_path"]).resolve()
        if path.resolve() == source_path or (source_path.is_dir() and path.resolve().is_relative_to(source_path)):
            raise ValueError("联系人台账不能使用邮箱数据库路径。")
        if existing and existing["source_id"] != batch["source_id"]:
            raise ValueError("该邮箱的数据位置已变化；请使用独立台账验证新来源，避免无编号邮件重复合并。")
        records, duplicate, conflict, skipped = [], 0, 0, batch.get("skipped_count", 0)
        seen = {}
        for message in batch["messages"]:
            record = _message_record(message, owner, scan["until"], scan["days"], batch["source_id"])
            if record is None:
                skipped += 1
                continue
            previous = conn.execute("SELECT signature FROM messages WHERE owner=? AND key=?", (owner, record["key"])).fetchone()
            signature = previous[0] if previous else seen.get(record["key"])
            if signature is not None:
                if signature == record["signature"]:
                    duplicate += 1
                else:
                    conflict += 1
                continue
            records.append(record)
            seen[record["key"]] = record["signature"]
        old = {r["email"]: r["last"] for r in conn.execute(
            "SELECT email,MAX(date) AS last FROM events JOIN messages USING(owner,key) WHERE owner=? GROUP BY email", (owner,))}
        touched = {}
        for record in records:
            for event in record["events"]:
                email = event["email"]
                touched[email] = max(touched.get(email, ""), record["date"])
        changes = {email: ("新联系人" if email not in old else
                           "新增记录" if date > old[email] else "补入历史")
                   for email, date in touched.items()}
        after = dict(scan, cursor=batch["cursor"], complete=not batch["more"],
                     scanned=scan["scanned"] + batch.get("scanned_count", len(batch["messages"])),
                     conflicts=scan["conflicts"] + conflict, skipped=scan["skipped"] + skipped,
                     source_kind=batch["source_kind"],
                     outside_window=scan.get("outside_window", 0) + batch.get("outside_window_count", 0))
        decision = {"revision": _revision(conn), "owner": owner, "source_id": batch["source_id"],
                    "before_scan": scan, "after_scan": after, "records": records,
                    "changes": changes, "duplicates": duplicate, "conflicts": conflict,
                    "skipped": skipped, "source_guard": batch.get("source_guard")}
        plan = {"version": 2, "ledger": str(path.resolve()), "owner": owner,
                "folder": folder, "days": days, "limit": limit, "now": now,
                "restart": restart, "decision_hash": digest(decision), "source": batch["source_kind"],
                "package": package_identity()}
        plan["plan_id"] = digest(plan)
        summary = {"status": "preview", "scanned_count": batch.get("scanned_count", len(batch["messages"])),
                   "added_mail_count": len(records), "duplicate_mail_count": duplicate,
                   "conflicting_mail_count": conflict, "skipped_mail_count": skipped,
                   "new_contact_count": sum(v == "新联系人" for v in changes.values()),
                   "updated_contact_count": sum(v != "新联系人" for v in changes.values()),
                   **scan_summary(after), "plan_id": plan["plan_id"], "body_read": False,
                   "local_database_written": False, "remote_write": False}
        return plan, decision, summary


def apply_plan(adapter, path: Path, plan: dict):
    expected = {"version", "ledger", "owner", "folder", "days", "limit", "now", "restart", "decision_hash", "plan_id", "source", "package"}
    if not isinstance(plan, dict) or set(plan) != expected:
        raise ValueError("预览文件格式无效；请重新预览。")
    for key in ("ledger", "owner", "folder", "decision_hash", "plan_id"):
        if not isinstance(plan[key], str):
            raise ValueError("预览文件字段无效；请重新预览。")
    if any(type(plan[k]) is not int for k in ("version", "days", "limit", "now")) or type(plan["restart"]) is not bool:
        raise ValueError("预览文件参数无效；请重新预览。")
    unsigned = {k: v for k, v in plan.items() if k != "plan_id"}
    if plan.get("version") != 2 or digest(unsigned) != plan.get("plan_id") or plan["ledger"] != str(path.resolve()):
        raise ValueError("预览文件无效或台账路径不一致；请重新预览。")
    if plan.get("package") != package_identity():
        raise ValueError("预览计划来自其他发布包；请在当前包中重新预览。")
    with ledger_read(path) as conn:
        old = conn.execute("SELECT receipt FROM batches WHERE id=?", (plan["plan_id"],)).fetchone()
        if old:
            receipt = json.loads(old[0])
            if "scan_conflicting_mail_count" not in receipt:
                # Pre-0.2.1 receipts did not save cumulative exceptions. Only
                # the current batch can be enriched from the stored scan.
                account = conn.execute("SELECT scan,last_batch FROM accounts WHERE owner=?", (plan["owner"],)).fetchone()
                if account and account["last_batch"] == plan["plan_id"]:
                    receipt.update(scan_summary(json.loads(account["scan"])))
                else:
                    receipt.update(scan_summary_available=False,
                                   scan_conflicting_mail_count=None, scan_skipped_mail_count=None,
                                   scan_requires_review=None,
                                   recovery="旧历史回执未保存累计异常；请运行 report 查看当前本轮摘要，不要把未知计为0。")
            return dict(receipt, status="already_applied", already_applied=True,
                        local_database_written=False)
    adapter = adapter() if callable(adapter) else adapter
    if plan["source"] != adapter.source_kind:
        raise ValueError("执行来源与预览不一致；没有写入，请重新选择来源。")
    actual, decision, summary = prepare(adapter, path, plan["owner"], folder=plan["folder"],
                                        days=plan["days"], limit=plan["limit"], now=plan["now"], restart=plan["restart"])
    if actual != plan:
        raise ValueError("邮件或台账在预览后发生变化；没有写入，请重新预览。")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT name FROM sqlite_master WHERE name='meta'").fetchone():
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("目标不是联系人台账；拒绝写入。")
            _initialize(conn)
        _check(conn)
        if _revision(conn) != decision["revision"]:
            raise ValueError("台账在预览后已变化；请重新预览。")
        owner = decision["owner"]
        for record in decision["records"]:
            conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)",
                         (owner, record["key"], record["signature"], record["date"], record["subject"]))
            for e in record["events"]:
                conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                             (owner, record["key"], e["email"], e["name"], e["received_count"], e["sent_count"], e["co_recipient_count"]))
        conn.execute("INSERT INTO accounts VALUES (?,?,?,?) ON CONFLICT(owner) DO UPDATE SET scan=excluded.scan,last_batch=excluded.last_batch",
                     (owner, decision["source_id"], canonical(decision["after_scan"]), plan["plan_id"]))
        for email, kind in decision["changes"].items():
            conn.execute("INSERT INTO changes VALUES (?,?,?)", (plan["plan_id"], email, kind))
        summary.update(status="updated", local_database_written=True,
                       ledger_path=str(path.resolve()), already_applied=False)
        conn.execute("INSERT INTO batches VALUES (?,?,?)", (plan["plan_id"], owner, canonical(summary)))
        conn.execute("UPDATE meta SET revision=revision+1")
        conn.commit()  # records, run receipt and cursor commit together
        return summary
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ledger_accounts(path):
    with ledger_read(path) as conn:
        return [r[0] for r in conn.execute("SELECT owner FROM accounts ORDER BY owner")]


def annotate(path: Path, owner, email, *, name=None, followed=None, note=None, execute=False):
    owner, email = _normalize_email(owner), _normalize_email(email)
    if not owner or not email or all(v is None for v in (name, followed, note)):
        raise ValueError("需要选择已有联系人，以及要修改的姓名、关注状态或备注。")
    if (name is not None and len(name) > 200) or (note is not None and len(note) > 4000):
        raise ValueError("姓名最多 200 字；备注最多 4000 字。")
    if followed not in (None, True, False):
        raise ValueError("关注状态必须为 yes 或 no。")
    # One connection and transaction avoids an annotation read/modify/write race.
    uri = path.resolve().as_uri() + ("?mode=rw" if execute else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.execute("BEGIN IMMEDIATE" if execute else "BEGIN")
        _check(conn)
        if not conn.execute("SELECT 1 FROM events WHERE owner=? AND email=?", (owner, email)).fetchone():
            raise ValueError("该邮箱台账中没有这个联系人；请先整理，不能跨邮箱修改。")
        old = conn.execute("SELECT name,followed,note FROM annotations WHERE owner=? AND email=?", (owner,email)).fetchone() or (None,0,"")
        values = (name if name is not None else old[0],
                  int(followed) if followed is not None else old[1],
                  note if note is not None else old[2])
        fields = [field for i,field in enumerate(("name", "followed", "note")) if values[i] != old[i]]
        if execute and fields:
            conn.execute("INSERT INTO annotations VALUES (?,?,?,?,?) ON CONFLICT(owner,email) DO UPDATE SET name=excluded.name,followed=excluded.followed,note=excluded.note", (owner,email,*values))
            conn.execute("UPDATE meta SET revision=revision+1")
            conn.commit()
        return {"status": "updated" if execute else "preview", "changed_fields": fields,
                "local_database_written": bool(execute and fields), "remote_write": False}
    finally:
        conn.close()


def report(path, owner, *, view="all", limit=50, now=None):
    owner = _normalize_email(owner)
    current = now or datetime.now(timezone.utc)
    with ledger_read(path) as conn:
        account = conn.execute("SELECT * FROM accounts WHERE owner=?", (owner,)).fetchone()
        if not account:
            raise ValueError("该邮箱还没有台账；请先预览并执行 update。")
        scan = json.loads(account["scan"])
        source = scan.get("source_kind", "mailmaster") + "_local"
        notes = {r["email"]: dict(r) for r in conn.execute("SELECT * FROM annotations WHERE owner=?", (owner,))}
        changes = {r["email"]: r["kind"] for r in conn.execute("SELECT * FROM changes WHERE batch=?", (account["last_batch"],))}
        people = {}
        for row in conn.execute("SELECT * FROM events JOIN messages USING(owner,key) WHERE owner=? ORDER BY date DESC,key", (owner,)):
            email, date = row["email"], _parse_datetime(row["date"])
            p = people.setdefault(email, {"email": email, "name": row["name"], "domain": email.split("@",1)[1],
                "first_interaction": row["date"], "last_interaction": row["date"], "received_count": 0, "sent_count": 0,
                "co_recipient_count": 0, "interaction_count": 0, "_direct_subject_keys": set(), "_subjects": {},
                "_last_direct_sort": None, "source": source})
            p["first_interaction"] = row["date"]
            p["interaction_count"] += 1
            p["received_count"] += row["received"]
            p["sent_count"] += row["sent"]
            p["co_recipient_count"] += row["cc"]
            subject = _subject_key(row["subject"])
            if subject:
                p["_subjects"].setdefault(subject, row["subject"])
            if row["received"] or row["sent"]:
                p["_last_direct_sort"] = p["_last_direct_sort"] or date
                if subject:
                    p["_direct_subject_keys"].add(subject)
        for email,p in people.items():
            score, level, reasons = _importance(p, current=current, days=30)
            manual = notes.get(email, {})
            p.update(importance_score=score, importance_level=level, importance_reasons=reasons,
                     candidate_type=_candidate_type(email), unique_subject_count=len(p["_subjects"]),
                     recent_subjects=list(p["_subjects"].values())[:3],
                     interaction_direction=_direction(p["received_count"],p["sent_count"]),
                     confirmed_name=manual.get("name") or "", followed="是" if manual.get("followed") else "否",
                     note=manual.get("note", ""), change=changes.get(email, "无新增记录"))
            p["name"] = p["confirmed_name"] or p["name"]
            for k in ("_direct_subject_keys", "_subjects", "_last_direct_sort"):
                del p[k]
        items = list(people.values())
        if view == "new":
            items = [p for p in items if p["change"] == "新联系人"]
        elif view == "recent":
            items = [p for p in items if p["email"] in changes]
        elif view == "followed":
            items = [p for p in items if p["followed"] == "是"]
        elif view != "all":
            raise ValueError("未知视图")
        items.sort(key=lambda p: (p["followed"] == "是",p["last_interaction"],p["interaction_count"],p["email"]),reverse=True)
        total_mail = conn.execute("SELECT COUNT(*) FROM messages WHERE owner=?", (owner,)).fetchone()[0]
        last_batch = json.loads(conn.execute("SELECT receipt FROM batches WHERE id=?", (account["last_batch"],)).fetchone()[0])
        return {"status": "report", "account_email": owner, "source": source, "view": view,
                "generated_at": current.isoformat(),
                "window_days": scan["days"], "folder": scan["folder"], "scan": scan,
                "last_batch": last_batch, "emails_in_scope": total_mail,
                "candidate_count": len(people), "view_count": len(items), "returned_count": min(limit,len(items)),
                "contacts_truncated": len(items)>limit, "candidates": items[:limit],
                "important_candidate_count": sum(p["importance_level"]=="重点候选" for p in people.values()),
                "followed_count": sum(p["followed"]=="是" for p in people.values()),
                "local_database_written": False, "body_read": False, "remote_write": False,
                "importance_scope": "累计已整理范围的往来证据；人工关注优先。分数只是候选排序，不等于客户价值。"}
