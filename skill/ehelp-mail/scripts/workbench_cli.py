from __future__ import annotations

import json
import os
from pathlib import Path

import contact_ledger as ledger
from contact_export import export_contacts_excel
from contact_report import render_contacts_html


def default_ledger():
    base = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / ".local/share"
    return base / "ehelp-mail/contacts.sqlite3"


def add_commands(subs):
    update = subs.add_parser("update", help="预览下一批；确认后写入本地联系人台账（不改邮箱）")
    update.add_argument("--ledger", default=str(default_ledger()))
    update.add_argument("--account", default="")
    update.add_argument("--source", choices=("auto", "mailmaster", "foxmail"), default="auto")
    update.add_argument("--folder", default="ALL")
    update.add_argument("--days", type=int, default=7)
    update.add_argument("--email-limit", type=int, default=100)
    update.add_argument("--restart-scan", action="store_true", help="明确放弃未完的扫描进度，保留已有联系人")
    update.add_argument("--plan", required=True, help="本地预览文件；执行时读取相同文件")
    update.add_argument("--execute", action="store_true")
    mark = subs.add_parser("annotate", help="预览或保存用户指定的姓名、关注标记和备注")
    mark.add_argument("--ledger", default=str(default_ledger()))
    mark.add_argument("--account", default="")
    mark.add_argument("--email", required=True)
    mark.add_argument("--name", default=None, help="空字符串清除人工姓名，恢复邮件中的名称")
    mark.add_argument("--follow", choices=("yes", "no"), default=None)
    mark.add_argument("--note-file", default=None, help="本机 UTF-8 备注文件；空文件清空备注")
    mark.add_argument("--execute", action="store_true")
    report = subs.add_parser("report", help="从台账生成本地 HTML/Excel，不需要打开邮箱")
    report.add_argument("--ledger", default=str(default_ledger()))
    report.add_argument("--account", default="")
    report.add_argument("--view", choices=("all", "new", "recent", "followed"), default="all")
    report.add_argument("--limit", type=int, default=50)
    report.add_argument("--report-html", default="")
    report.add_argument("--export-excel", default="")


def _select(account, available):
    selected = account.strip().casefold()
    if not selected and len(available) == 1:
        selected = available[0].casefold()
    if not selected or selected not in {a.casefold() for a in available}:
        raise ValueError("请明确选择一个已就绪邮箱；多个邮箱不能自动选第一个。")
    return selected


def run_workbench(args, root):
    path = Path(args.ledger).expanduser().resolve()
    if args.command == "update":
        from cli import _pick_source, _protect_source_outputs
        plan_path = Path(args.plan).expanduser().resolve()
        if args.execute:
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                required = {"version","ledger","owner","folder","days","limit","now","restart","decision_hash","plan_id","source","package"}
                if not isinstance(plan, dict) or set(plan) != required:
                    raise ValueError("预览文件格式无效")
                if args.account and args.account.casefold().strip() != plan["owner"]:
                    raise ValueError("执行邮箱与预览不一致")
                if plan["source"] not in {"mailmaster", "foxmail"} or args.source not in {"auto", plan["source"]}:
                    raise ValueError("执行来源与预览不一致")
                return ledger.apply_plan(lambda: _pick_source(root, plan["owner"], plan["source"])[0], path, plan)
            except (TypeError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError("预览文件无效，请重新预览。") from exc
        from cli import _preflight_output_parent
        _preflight_output_parent(plan_path)
        _preflight_output_parent(path)
        if plan_path in path.parents or path in plan_path.parents:
            raise ValueError("预览和台账文件不能用作彼此的父目录。")
        if Path(args.plan).expanduser().is_symlink() or plan_path.exists() or plan_path == path:
            raise ValueError("预览文件已存在；请使用新文件名。")
        if plan_path.suffix.lower() != ".json":
            raise ValueError("预览文件请使用 .json 后缀。")
        requested = args.source
        selected_account = args.account
        # Keep a previously selected source; installing a second client later
        # must not change the origin or merge its local identifiers silently.
        if requested == "auto" and path.is_file():
            owners = ledger.ledger_accounts(path)
            owner = args.account.casefold().strip() or (owners[0] if len(owners) == 1 else "")
            with ledger.ledger_read(path) as conn:
                row = conn.execute("SELECT scan FROM accounts WHERE owner=?", (owner,)).fetchone()
                if row:
                    requested = json.loads(row[0]).get("source_kind", "mailmaster")
                    selected_account = owner
        adapter, owner, _ = _pick_source(root, selected_account, requested)
        _protect_source_outputs(adapter, (path, plan_path))
        plan, _, summary = ledger.prepare(adapter, path, owner, folder=args.folder,
            days=args.days, limit=args.email_limit, restart=args.restart_scan)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        with plan_path.open("x", encoding="utf-8") as out:
            json.dump(plan, out, ensure_ascii=False, indent=2)
        summary["plan_path"] = str(plan_path)
        summary["ledger_path"] = str(path)
        return summary
    owner = _select(args.account, ledger.ledger_accounts(path))
    if args.command == "annotate":
        note = Path(args.note_file).read_text(encoding="utf-8-sig") if args.note_file is not None else None
        return ledger.annotate(path, owner, args.email, name=args.name,
                               followed=None if args.follow is None else args.follow=="yes",
                               note=note, execute=args.execute)
    if not 1 <= args.limit <= 100000:
        raise ValueError("limit 必须在 1–100000 之间。")
    # Validate every output before writing either; preserve previous reports.
    from cli import _output_paths, _export_outputs
    paths = _output_paths(args)
    payload = ledger.report(path, owner, view=args.view, limit=args.limit)
    _export_outputs(payload, paths, export_contacts_excel, render_contacts_html)
    keys = ("status","view","candidate_count","view_count","returned_count","contacts_truncated",
            "emails_in_scope","followed_count","important_candidate_count",
            "body_read","local_database_written","remote_write","excel_path","html_path")
    summary = {k:payload[k] for k in keys if k in payload}
    summary.update(ledger.scan_summary(payload["scan"]))
    last = payload["last_batch"]
    summary.update(last_batch_new_contact_count=last.get("new_contact_count", 0),
                   last_batch_updated_contact_count=last.get("updated_contact_count", 0),
                   last_batch_added_mail_count=last.get("added_mail_count", 0))
    return summary
