from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any
import re
import unicodedata

from models import MailSearchResponse, MailSummary


def _normalize_email(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(
        char
        for char in text
        if unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )
    text = text.strip().lower()
    if not text or "@" not in text:
        return ""
    local, domain = text.rsplit("@", 1)
    if not local or not domain or any(char.isspace() for char in text):
        return ""
    return text


def _decode_header(value: object) -> str:
    text = str(value or "").strip()
    try:
        return str(make_header(decode_header(text)))
    except (LookupError, UnicodeError, ValueError):
        return text


def _parse_addresses(value: object) -> list[tuple[str, str]]:
    text = str(value or "").strip()
    if not text:
        return []
    pairs = getaddresses([text.replace(";", ",")])
    result: list[tuple[str, str]] = []
    for name, address in pairs:
        email = _normalize_email(address)
        if email:
            result.append((_decode_header(name), email))
    return result


def _sender(summary: MailSummary) -> tuple[str, str]:
    pairs = _parse_addresses(summary.from_addr)
    if pairs:
        name, email = pairs[0]
        return _decode_header(summary.from_name or name), email
    return _decode_header(summary.from_name), _normalize_email(summary.from_addr)


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date_text(value: object, parsed: datetime | None) -> str:
    if parsed is None:
        return str(value or "").strip()
    return parsed.isoformat(timespec="seconds")


def _display_name(name: str, email: str) -> str:
    cleaned = str(name or "").strip()
    if cleaned and cleaned.casefold() != email.casefold():
        return cleaned
    return email.split("@", 1)[0]


def _direction(received: int, sent: int) -> str:
    if received and sent:
        return "双向往来"
    if received:
        return "收件为主"
    if sent:
        return "发件为主"
    return "仅共同收件/抄送"


_SYSTEM_LOCAL_PARTS = {
    "auto-reply",
    "autoreply",
    "bounce",
    "bounces",
    "daemon",
    "donotreply",
    "mailer-daemon",
    "no-reply",
    "noreply",
    "notification",
    "notifications",
    "postmaster",
    "updates",
}


def _candidate_type(email: str) -> str:
    local_part = email.split("@", 1)[0].casefold().split("+", 1)[0]
    if local_part in _SYSTEM_LOCAL_PARTS:
        return "疑似系统地址"
    if local_part.startswith(("no-reply-", "noreply-", "notify-")):
        return "疑似系统地址"
    return "联系人候选"


def _subject_key(subject: str) -> str:
    # Reply prefixes are not evidence of additional topics or business matters.
    return re.sub(r"^(?:(?:re|fw|fwd|回复|答复|转发)\s*[:：]\s*)+", "", subject, flags=re.I).strip().casefold()


def _importance(
    item: dict[str, Any],
    *,
    current: datetime,
    days: int,
) -> tuple[int, str, list[str]]:
    candidate_type = _candidate_type(str(item["email"]))
    if candidate_type == "疑似系统地址":
        return 0, candidate_type, ["地址符合常见系统命名，需人工复核"]

    received_count = int(item["received_count"])
    sent_count = int(item["sent_count"])
    direct_count = received_count + sent_count
    if not direct_count:
        return 0, "共同收件候选", ["仅在共同收件或抄送中出现，未见直接往来"]
    unique_subject_count = len(item["_direct_subject_keys"])
    last_interaction = item["_last_direct_sort"]
    age_days = max(0.0, (current - last_interaction).total_seconds() / 86400)

    # Fixed weights keep unrelated senders from changing this contact's score.
    frequency_points = round(40 * min(direct_count / 5, 1.0))
    recency_points = round(25 * max(0.0, 1 - min(age_days / max(days, 1), 1.0)))
    if received_count and sent_count:
        direction_points = 25
    elif received_count or sent_count:
        direction_points = 10
    else:
        direction_points = 0
    subject_points = round(10 * min(unique_subject_count / 3, 1.0))
    score = min(100, frequency_points + recency_points + direction_points + subject_points)

    reasons: list[str] = []
    reasons.append(f"直接往来 {direct_count} 封")
    if age_days <= min(2, days):
        reasons.append("最近有往来")
    if received_count and sent_count:
        reasons.append("有双向往来")
    if unique_subject_count >= 2:
        reasons.append(f"直接往来含 {unique_subject_count} 个不同主题（非业务事项数）")

    if score >= 65 and direct_count >= 3:
        level = "重点候选"
    elif score >= 40 and direct_count >= 2:
        level = "关注候选"
    else:
        level = "一般候选"
    return score, level, reasons


def build_contact_preview(
    response: MailSearchResponse,
    *,
    account_email: str,
    folder: str,
    days: int = 7,
    email_limit: int = 100,
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a bounded, read-only contact preview from mail headers."""
    if days <= 0:
        raise ValueError("days must be a positive integer")
    if email_limit <= 0:
        raise ValueError("email_limit must be a positive integer")
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    owner = _normalize_email(account_email)
    if not owner:
        raise ValueError("account_email must identify the selected mailbox")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    cutoff = current - timedelta(days=days)

    candidates: OrderedDict[str, dict[str, Any]] = OrderedDict()
    in_scope = 0
    skipped_undated = 0
    skipped_outside_window = 0
    skipped_duplicates = 0
    skipped_other_account = 0
    seen_messages: set[tuple[object, ...]] = set()

    for summary in response.emails[:email_limit]:
        # A missing mailbox marker is not safe when more than one local mailbox
        # may exist. Keep the selected account boundary closed by default.
        if _normalize_email(summary.account_email) != owner:
            skipped_other_account += 1
            continue
        parsed_date = _parse_datetime(summary.date)
        if parsed_date is None:
            skipped_undated += 1
            continue
        if parsed_date < cutoff or parsed_date > current:
            skipped_outside_window += 1
            continue
        # Do not collapse unrelated messages merely because their headers match.
        message_id = str(summary.message_id or "").strip().strip("<>")
        identity = ("message_id", message_id) if message_id else (
            ("local_id", summary.folder, summary.id) if summary.id else None
        )
        if identity is not None:
            if identity in seen_messages:
                skipped_duplicates += 1
                continue
            seen_messages.add(identity)
        in_scope += 1

        sender_name, sender_email = _sender(summary)
        to_recipients = _parse_addresses(summary.to_addr)
        recipients = to_recipients + _parse_addresses(summary.cc_addr)
        direct_recipient_emails = {email for _, email in to_recipients}
        participant_details: OrderedDict[str, str] = OrderedDict()
        if sender_email:
            participant_details[sender_email] = sender_name
        for name, email in recipients:
            participant_details.setdefault(email, name)

        subject = _decode_header(summary.subject)
        subject_key = _subject_key(subject)
        date_text = _date_text(summary.date, parsed_date)
        for email, name in participant_details.items():
            if not email or email == owner:
                continue
            item = candidates.setdefault(
                email,
                {
                    "email": email,
                    "name": _display_name(name, email),
                    "domain": email.split("@", 1)[1],
                    "first_interaction": date_text,
                    "last_interaction": date_text,
                    "interaction_count": 0,
                    "received_count": 0,
                    "sent_count": 0,
                    "co_recipient_count": 0,
                    "_subjects": {},
                    "_direct_subject_keys": set(),
                    "_last_sort": parsed_date,
                    "_last_direct_sort": None,
                },
            )
            if name and item["name"] == email.split("@", 1)[0]:
                item["name"] = _display_name(name, email)
            item["interaction_count"] += 1
            if date_text < item["first_interaction"]:
                item["first_interaction"] = date_text
            if date_text > item["last_interaction"]:
                item["last_interaction"] = date_text
            if parsed_date > item["_last_sort"]:
                item["_last_sort"] = parsed_date
            direct = False
            if sender_email == email and owner in direct_recipient_emails:
                item["received_count"] += 1
                direct = True
            if sender_email == owner and email in direct_recipient_emails:
                item["sent_count"] += 1
                direct = True
            if direct:
                if item["_last_direct_sort"] is None or parsed_date > item["_last_direct_sort"]:
                    item["_last_direct_sort"] = parsed_date
                if subject_key:
                    item["_direct_subject_keys"].add(subject_key)
            else:
                item["co_recipient_count"] += 1
            if subject_key:
                previous = item["_subjects"].get(subject_key)
                if previous is None or parsed_date > previous[0]:
                    item["_subjects"][subject_key] = (parsed_date, subject)

    for item in candidates.values():
        score, level, reasons = _importance(
            item,
            current=current,
            days=days,
        )
        item["candidate_type"] = _candidate_type(str(item["email"]))
        item["importance_score"] = score
        item["importance_level"] = level
        item["importance_reasons"] = reasons

    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            item["candidate_type"] != "疑似系统地址",
            int(item["importance_score"]),
            int(item["interaction_count"]),
            item["last_interaction"],
            item["email"],
        ),
        reverse=True,
    )
    public_candidates: list[dict[str, Any]] = []
    for item in ordered:
        subjects = [
            subject
            for _, subject in sorted(item["_subjects"].values(), key=lambda pair: pair[0], reverse=True)[:3]
        ]
        public_candidates.append(
            {
                "email": item["email"],
                "name": item["name"],
                "domain": item["domain"],
                "first_interaction": item["first_interaction"],
                "last_interaction": item["last_interaction"],
                "interaction_count": item["interaction_count"],
                "received_count": item["received_count"],
                "sent_count": item["sent_count"],
                "co_recipient_count": item["co_recipient_count"],
                "candidate_type": item["candidate_type"],
                "importance_score": item["importance_score"],
                "importance_level": item["importance_level"],
                "importance_reasons": item["importance_reasons"],
                "unique_subject_count": len(item["_subjects"]),
                "interaction_direction": _direction(
                    item["received_count"],
                    item["sent_count"],
                ),
                "recent_subjects": subjects,
                "source": response.source,
            }
        )

    returned = public_candidates[:limit]
    important_count = sum(
        1 for item in public_candidates if item["importance_level"] == "重点候选"
    )
    person_count = sum(
        1 for item in public_candidates if item["candidate_type"] == "联系人候选"
    )
    return {
        "status": "preview",
        "account_email": owner,
        "source": response.source,
        "folder": folder,
        "window_days": days,
        "email_limit": email_limit,
        "emails_returned": len(response.emails),
        "emails_in_scope": in_scope,
        "emails_skipped_undated": skipped_undated,
        "emails_skipped_outside_window": skipped_outside_window,
        "emails_skipped_duplicates": skipped_duplicates,
        "emails_skipped_other_account": skipped_other_account,
        "candidate_count": len(public_candidates),
        "returned_count": len(returned),
        "contacts_truncated": len(returned) < len(public_candidates),
        "returned_important_candidate_count": sum(item["importance_level"] == "重点候选" for item in returned),
        "important_candidate_count": important_count,
        "person_candidate_count": person_count,
        "system_candidate_count": len(public_candidates) - person_count,
        "importance_scope": "仅根据本次范围的直接往来排序；不等于真人识别、客户价值或商机判断。共同收件/抄送不计直接往来；疑似系统地址保留供复核。",
        "importance_rule_version": "headers-v2",
        "scope_truncated": bool(
            response.scan_truncated or len(response.emails) >= email_limit
        ),
        "source_scanned_count": response.scanned_count,
        "source_scan_truncated": response.scan_truncated,
        "body_read": False,
        "local_database_written": False,
        "remote_write": False,
        "candidates": returned,
    }
