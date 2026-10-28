"""Account-scoped Foxmail contact headers; no old full-message/draft runtime."""
from __future__ import annotations

from datetime import datetime, timezone
from email import policy
from email.parser import BytesHeaderParser
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
from pathlib import Path
import re
import struct

from foxmail_headers import FoxmailHeaderReader, read_metadata
from models import MailAccount, MailSearchResponse, MailSummary


class FoxmailContactAdapter:
    source_kind = "foxmail"

    def __init__(self, root_dir: Path):
        self.root = Path(root_dir).expanduser().resolve()

    def _accounts(self):
        # FMStorage and directory names are account metadata, not credentials.
        found = {}
        if not (self.root / "FMStorage.list").is_file():
            return found
        data = read_metadata(self.root / "FMStorage.list", self.root, maximum=1024 * 1024)
        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-16le" if b"\0" in data[:64] else "utf-8-sig"
        candidates = []
        for line in data.decode(encoding, errors="strict").splitlines():
            value = line.strip().strip('"')
            if value:
                candidate = Path(value)
                candidates.append(candidate if candidate.is_absolute() else self.root / candidate)
        storage = self.root / "Storage"
        if storage.is_dir():
            candidates.extend(storage.iterdir())
        for path in candidates:
            resolved = path.resolve()
            email = path.name.casefold().strip()
            if (resolved.is_relative_to(self.root) and resolved.is_dir()
                    and re.fullmatch(r"[^\s/\\@]+@[^\s/\\@]+", email)):
                if email in found and found[email] != resolved:
                    raise RuntimeError("Foxmail 同名邮箱有多个存储目录；请先确认来源。")
                found[email] = resolved
        return found

    def list_accounts(self):
        return [MailAccount(account_id=i, account_email=email, data_path=str(path),
                    ready=(path / "Mails").is_dir() and (path / "Boxes/all.box").is_file())
                for i, (email, path) in enumerate(sorted(self._accounts().items()), 1)]

    def _account(self, owner):
        selected = str(owner).strip().casefold()
        if not selected:
            raise ValueError("请明确选择一个邮箱。")
        account = next((a for a in self.list_accounts() if a.account_email == selected and a.ready), None)
        if account is None:
            raise ValueError("所选 Foxmail 邮箱没有就绪的本地索引。")
        return account, Path(account.data_path)

    def read_contact_batch(self, owner: str, scan: dict, limit: int) -> dict:
        if not 1 <= limit <= 500:
            raise ValueError("email-limit 必须在 1–500 之间。")
        account, root = self._account(owner)
        boxes = root / "Boxes"
        snapshots = {}

        def box(name, required=False):
            path = boxes / (name + ".box")
            if not path.exists():
                snapshots[path] = None
                if required:
                    raise RuntimeError("Foxmail 文件夹索引未就绪。")
                return set()
            data = read_metadata(path, root)
            snapshots[path] = hashlib.sha256(data).hexdigest()
            if len(data) < 64 or data[:4] != b"LSTG" or (len(data) - 64) % 4:
                raise RuntimeError("Foxmail 文件夹索引格式暂不支持。")
            return {v[0] for v in struct.iter_unpack("<I", data[64:]) if v[0]}

        all_ids = box("all", True)
        excluded = set().union(*(box(n) for n in ("draft", "trash", "junk", "spam", "deleted")))
        sent = box("sent")
        folder = scan["folder"].upper()
        if folder == "ALL":
            ids = all_ids - excluded
        elif folder == "SENT":
            ids = (all_ids & sent) - excluded
        elif folder == "INBOX":
            name = "inbox" if (boxes / "inbox.box").is_file() else "in"
            ids = (all_ids & box(name, True)) - excluded
        else:
            raise ValueError("Foxmail 联系人来源只支持 ALL、SENT 或有明确索引的 INBOX。")
        cursor = scan.get("cursor")
        if cursor and (not isinstance(cursor, dict) or set(cursor) != {"ceiling", "last"}):
            raise ValueError("扫描进度与 Foxmail 来源不匹配；请使用独立台账。")
        ceiling = cursor["ceiling"] if cursor else max(ids, default=0)
        remaining = sorted((i for i in ids if i <= ceiling and (not cursor or i < cursor["last"])), reverse=True)
        chosen = remaining[:limit]
        reader = FoxmailHeaderReader(root)
        messages, skipped, outside, parsed = [], 0, 0, 0
        for mail_id in chosen:
            path = root / "Mails" / str(mail_id % 32) / str((mail_id // 32) % 32) / str(mail_id)
            if not path.is_file():
                skipped += 1
                continue
            header = reader.read(path)  # Unsupported or changing source aborts before any ledger write.
            message = BytesHeaderParser(policy=policy.default).parsebytes(header)
            if not message.get("From"):
                raise RuntimeError("Foxmail 邮件头缺少发件人，不能可靠整理。")
            parsed += 1
            try:
                dt = parsedate_to_datetime(str(message.get("Date") or ""))
                if dt is None or dt.tzinfo is None:
                    raise ValueError("undated")
                stamp = dt.timestamp()
            except (ValueError, TypeError, OverflowError):
                skipped += 1
                continue
            if not scan["cutoff"] <= stamp <= scan["until"]:
                outside += 1
                continue

            def addresses(field):
                return getaddresses([str(v) for v in message.get_all(field, [])])

            sender = addresses("From") or addresses("Sender")
            messages.append(MailSummary(id=mail_id, account_id=account.account_id,
                account_email=account.account_email, folder="SENT" if mail_id in sent else "RECEIVED",
                message_id=str(message.get("Message-ID") or ""),
                references=str(message.get("References") or ""), in_reply_to=str(message.get("In-Reply-To") or ""),
                subject=str(message.get("Subject") or ""), from_name=sender[0][0], from_addr=sender[0][1],
                to_addr=", ".join(a for _, a in addresses("To")), cc_addr=", ".join(a for _, a in addresses("Cc")),
                date=dt.astimezone(timezone.utc).isoformat(), body_preview=""))
        for path, expected in snapshots.items():
            actual = hashlib.sha256(read_metadata(path, root)).hexdigest() if path.exists() else None
            if actual != expected:
                raise RuntimeError("Foxmail 正在同步，索引已变化；没有更新台账，请重新预览。")
        reader.verify_unchanged()
        source_id = hashlib.sha256(("foxmail|" + str(root).casefold()).encode()).hexdigest()
        return {"source_id": source_id, "source_path": str(root), "source_kind": self.source_kind,
                "source_guard": sorted((p.name, v) for p, v in snapshots.items()),
                "messages": messages, "scanned_count": len(chosen), "skipped_count": skipped,
                "outside_window_count": outside, "header_count": parsed,
                "cursor": {"ceiling": ceiling, "last": chosen[-1]} if chosen else cursor,
                "more": len(remaining) > len(chosen)}

    def list_emails_for_account_email(self, *, account_email, folder="ALL", limit=100):
        now = datetime.now(timezone.utc).timestamp()
        batch = self.read_contact_batch(account_email,
            {"folder": folder.upper(), "cutoff": -62135596800, "until": now, "cursor": None}, limit)
        return MailSearchResponse(source="foxmail_local", total=len(batch["messages"]),
            emails=batch["messages"], scanned_count=batch["scanned_count"], scan_truncated=batch["more"])
