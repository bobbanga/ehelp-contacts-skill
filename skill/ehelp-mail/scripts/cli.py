from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from contact_core import build_contact_preview
from contact_export import export_contacts_excel
from contact_report import render_contacts_html
from mail_client_discovery import discover_clients, discover_mailmaster_client, discover_foxmail_client
from mailmaster_adapter import MailMasterMailAdapter
from foxmail_contact_adapter import FoxmailContactAdapter
from mailmaster_discovery import default_mailmaster_root
from workbench_cli import add_commands, run_workbench
from lifecycle import (
    apply_restore_plan,
    apply_upgrade_plan,
    backup_ledger,
    default_ledger as lifecycle_default_ledger,
    ledger_info,
    package_info,
    status_payload,
    write_restore_plan,
    write_upgrade_plan,
)

MAILMASTER_URL = "https://dashi.163.com/"
FOXMAIL_URL = "https://www.foxmail.com/win/zh/"
FEISHU_URL = "https://www.feishu.cn/feishu-cli"

_CONTACT_RESULT_KEYS = (
    "status", "source", "folder", "window_days", "email_limit", "emails_returned",
    "emails_in_scope", "emails_skipped_undated", "emails_skipped_outside_window",
    "emails_skipped_duplicates", "emails_skipped_other_account", "candidate_count",
    "returned_count", "contacts_truncated", "returned_important_candidate_count",
    "important_candidate_count", "person_candidate_count", "system_candidate_count",
    "importance_scope", "importance_rule_version", "scope_truncated",
    "source_scanned_count", "source_scan_truncated", "body_read",
    "local_database_written", "remote_write", "excel_path", "html_path",
)


def _contact_result_summary(payload: dict) -> dict:
    return {key: payload[key] for key in _CONTACT_RESULT_KEYS if key in payload}


def _print_json(payload: object) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _mailmaster_root() -> Path:
    configured = os.environ.get("MAILMASTER_ROOT", "").strip()
    return Path(configured).expanduser() if configured else default_mailmaster_root()


def _doctor_payload(root: Path) -> dict:
    if sys.platform == "darwin":
        return _doctor_payload_macos(root)
    if sys.platform != "win32":
        return {
            "status": "unsupported_platform", "product": "易邮本地联系人",
            "platform": sys.platform, "verified_platform": "Windows",
            "package": package_info(), "ledger": ledger_info(),
            "mail_sources": [], "read_only": True, "body_read": False,
            "remote_calls": 0, "remote_write": False, "local_database_written": False,
            "next_step": "当前系统未经过邮件来源读取验收；请使用 Windows 本机已同步的邮箱大师。已有台账可离线生成报告。",
        }
    mailmaster = discover_mailmaster_client(root)
    configured_foxmail = os.environ.get("FOXMAIL_ROOT", "").strip()
    foxmail = discover_foxmail_client(
        candidate_roots=[Path(configured_foxmail)] if configured_foxmail else None
    )
    return {
        "status": "ready" if mailmaster.ready or foxmail.ready else "needs_mail_source",
        "product": "ehelp-mail 本地联系人工作台",
        "package": package_info(),
        "ledger": ledger_info(),
        "platform": sys.platform,
        "verified_platform": "Windows",
        "read_only": True,
        "body_read": False,
        "model_required": False,
        "remote_calls": 0,
        "remote_write": False,
        "local_database_written": False,
        "mail_sources": [
            {
                "source": "mailmaster", "detected": mailmaster.detected,
                "ready": mailmaster.ready, "state": mailmaster.state,
                "account_count": len(mailmaster.discovered_accounts),
                "official_url": MAILMASTER_URL,
            },
            {
                "source": "foxmail", "detected": foxmail.detected, "ready": foxmail.ready,
                "state": foxmail.state, "account_count": len(foxmail.discovered_accounts),
                "validation": "windows_install_closed_client_sample", "live_install_verified": True,
                "active_sync_verified": False, "ready_scope": "account_and_index_metadata_only",
                "official_url": FOXMAIL_URL,
            },
        ],
        "next_step": (
            "运行 accounts；多个账号时选择一个，再用 update 预览本地台账更新，执行后用 report 查看。"
            if mailmaster.ready or foxmail.ready else
            "未检测到时先确认是否使用自定义安装目录；Foxmail 可指定 FOXMAIL_ROOT。"
            "确实未安装再使用官方入口；已安装但索引未就绪时，先在客户端登录并同步。"
        ),
        "feishu": {
            "required": False, "write_available": False, "official_url": FEISHU_URL,
            "note": "飞书协作属于后续版本，本版无需 Bot、模型或飞书 CLI。",
        },
    }


def _doctor_payload_macos(root: Path) -> dict:
    clients = discover_clients(root)
    detected = [c for _, c in clients if c.detected]
    return {
        "status": "unverified_platform",
        "product": "ehelp-mail 本地联系人工作台",
        "package": package_info(),
        "ledger": ledger_info(),
        "platform": sys.platform,
        "verified_platform": "macOS (候选/未验收)",
        "read_only": True,
        "body_read": False,
        "model_required": False,
        "remote_calls": 0,
        "remote_write": False,
        "local_database_written": False,
        "mail_sources": [
            {
                "source": kind, "detected": c.detected, "ready": c.ready,
                "state": c.state, "account_count": len(c.discovered_accounts),
                "validation": "macos_candidate_unverified", "ready_scope": "探测到目录，但解析未现场验收",
                "message": c.message,
            }
            for kind, c in clients
        ],
        "next_step": (
            "已在 macOS 探测到候选邮件客户端（Foxmail / Apple Mail），但解析逻辑尚未现场验收；"
            "默认不扫描。请在 Mac 上由用户确认后，再按 SKILL.md 的 macOS 流程现场验收并启用。"
            if detected else
            "未检测到 macOS 邮件客户端数据目录；如需整理，请先安装并同步 Foxmail (macOS) 或 Apple Mail。"
        ),
        "feishu": {
            "required": False, "write_available": False, "official_url": FEISHU_URL,
            "note": "飞书协作属于后续版本，本版无需 Bot、模型或飞书 CLI。",
        },
    }


def _source_options(root, requested="auto"):
    options = []
    if sys.platform == "darwin":
        # macOS 来源解析尚未现场验收；默认不扫描，避免产生不可信数据。
        return options
    if requested in {"auto", "mailmaster"}:
        try:
            adapter = MailMasterMailAdapter(root_dir=root, draft_sink=None)
            options.extend(("mailmaster", adapter, a) for a in adapter.list_accounts() if a.ready and a.account_email)
        except (OSError, RuntimeError):
            if requested == "mailmaster":
                raise
    if requested in {"auto", "foxmail"}:
        configured = os.environ.get("FOXMAIL_ROOT", "").strip()
        status = discover_foxmail_client(candidate_roots=[Path(configured)] if configured else None)
        if status.ready and status.data_root:
            adapter = FoxmailContactAdapter(Path(status.data_root))
            options.extend(("foxmail", adapter, a) for a in adapter.list_accounts() if a.ready and a.account_email)
    return options


def _pick_source(root, account="", requested="auto"):
    options = _source_options(root, requested)
    available = {a.account_email.casefold() for _, _, a in options}
    selected = account.casefold().strip()
    if not selected and len(available) == 1:
        selected = next(iter(available))
    if not selected or selected not in available:
        raise ValueError("请运行 accounts，明确选择一个已就绪的邮箱和来源。")
    # Source order is explicit and stable; no fallback after a reading failure.
    kind, adapter, _ = next(row for row in options if row[2].account_email.casefold() == selected)
    return adapter, selected, kind


def _protect_source_outputs(adapter, paths):
    source_root = getattr(adapter, "root", None) or getattr(adapter, "root_dir", None)
    if isinstance(source_root, (str, Path)):
        source_root = Path(source_root).expanduser().resolve()
        if any(Path(p).resolve().is_relative_to(source_root) for p in paths):
            raise ValueError("台账、预览和结果必须放在邮箱客户端数据目录之外。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ehelp-mail 联系人工作台：只读邮件头部，持续整理本地台账和人工标记，导出 HTML 与 Excel。"
    )
    parser.add_argument("--json", action="store_true", help="只输出数量、范围、状态和文件位置")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("version", help="查看当前发布包版本与边界")
    status = subs.add_parser("status", help="查看发布包、台账和本机运行状态")
    status.add_argument("--ledger", default=str(lifecycle_default_ledger()))
    backup = subs.add_parser("backup", help="备份本地联系人台账，不改邮箱和原台账")
    backup.add_argument("--ledger", default=str(lifecycle_default_ledger()))
    backup.add_argument("--output", default="", help="新备份文件路径；不填则自动生成")
    restore = subs.add_parser("restore", help="先生成恢复预览，再恢复到新的台账路径")
    restore.add_argument("--backup", default="")
    restore.add_argument("--ledger", default=str(lifecycle_default_ledger()))
    restore.add_argument("--plan", required=True)
    restore.add_argument("--execute", action="store_true")
    upgrade = subs.add_parser("upgrade", help="先检查升级包，再安全解压到新目录")
    upgrade.add_argument("--package", default="")
    upgrade.add_argument("--target", default="", help="新版本目录；不填则自动生成同级目录")
    upgrade.add_argument("--plan", required=True)
    upgrade.add_argument("--execute", action="store_true")
    subs.add_parser("doctor", help="检查环境和本地邮箱来源")
    accounts = subs.add_parser("accounts", help="列出本机邮箱账号供选择")
    accounts.add_argument("--source", choices=("auto", "mailmaster", "foxmail"), default="auto")
    contacts = subs.add_parser("contacts", help="预览联系人数量，或导出本地结果")
    contacts.add_argument("--account", default="", help="多个账号时必须指定一个")
    contacts.add_argument("--source", choices=("auto", "mailmaster", "foxmail"), default="auto")
    contacts.add_argument("--folder", default="ALL")
    contacts.add_argument("--days", type=int, default=7)
    contacts.add_argument("--email-limit", type=int, default=100)
    contacts.add_argument("--limit", type=int, default=50)
    contacts.add_argument("--export-excel", default="")
    contacts.add_argument("--report-html", default="")
    add_commands(subs)
    return parser


def _preflight_output_parent(target: Path) -> None:
    """Check existing ancestors without creating any files or directories."""
    ancestor = target.parent
    while not ancestor.exists() and not ancestor.is_symlink():
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise ValueError("输出父路径不是目录；请改用有效的新目录。")
    if not os.access(ancestor, os.W_OK | os.X_OK):
        raise ValueError("输出父目录不可写或不可访问；请改用自己可写的目录。")


class ExportFailure(RuntimeError):
    def __init__(self, completed, paths, failed):
        super().__init__("导出未全部完成；已完成文件保留，请只补齐未完成项。")
        self.completed = dict(completed)
        self.paths = paths
        self.failed = failed

    def summary(self, command):
        remaining = {key: str(path) for key, path in self.paths.items() if key not in self.completed}
        return {
            "status": "partial_export" if self.completed else "export_failed",
            "error": str(self), "completed_outputs": self.completed,
            "remaining_outputs": remaining, "failed_output": self.failed,
            "failed_path": str(self.paths[self.failed]),
            "failed_path_exists": os.path.lexists(self.paths[self.failed]),
            **{key + "_path": value for key, value in self.completed.items()},
            "recovery": f"仅重新运行 {command} 的未完成输出参数，保持账号、视图和台账不变；"
                        "不要重跑 update。失败路径若已有文件，请保留并换新文件名；不覆盖或删除已有结果。",
            "body_read": False, "remote_write": False, "local_database_written": False,
        }


def _export_outputs(payload, paths, excel_writer, html_writer):
    completed = {}
    for key, writer in (("excel", excel_writer), ("html", html_writer)):
        if key not in paths:
            continue
        try:
            # Each public CLI export creates its final file exclusively, even
            # if another writer creates that target after the preflight.
            result = str(writer(payload, paths[key], exclusive=True))
        except (OSError, ValueError, RuntimeError) as exc:
            raise ExportFailure(completed, paths, key) from exc
        completed[key] = result
        payload[key + "_path"] = result


def _output_paths(args: argparse.Namespace) -> dict[str, Path]:
    paths = {}
    for key, value, suffix in (
        ("excel", args.export_excel, ".xlsx"), ("html", args.report_html, ".html")
    ):
        if not value:
            continue
        raw_target = Path(value).expanduser()
        if raw_target.is_symlink():
            raise ValueError("结果文件已存在（符号链接）；请使用新文件名。")
        target = raw_target.resolve()
        if target.suffix.casefold() != suffix:
            raise ValueError(f"{key} 输出路径必须以 {suffix} 结尾")
        if target.exists():
            raise ValueError("结果文件已存在；请使用新文件名，避免覆盖以前的结果。")
        _preflight_output_parent(target)
        paths[key] = target
    if any(a in b.parents for a in paths.values() for b in paths.values()):
        raise ValueError("输出文件不能同时用作另一个输出的父目录；请使用同级的新文件名。")
    return paths


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = _mailmaster_root()
        if args.command in {"update", "annotate", "report"}:
            payload = run_workbench(args, root)
            return _print_json(payload)
        if args.command == "version":
            payload = {"status": "ready", "package": package_info(), "remote_write": False}
            if args.json:
                return _print_json(payload)
            print(f"{payload['package']['release']} {payload['package']['version']} ({payload['package']['channel']})")
            print(payload["package"]["package_root"])
            return 0
        if args.command == "status":
            payload = status_payload(Path(args.ledger))
            if args.json:
                return _print_json(payload)
            print(f"版本：{payload['package']['version']}（{payload['package']['channel']}）")
            ledger = payload["ledger"]
            print(f"台账：{'已存在' if ledger['exists'] else '尚未建立'}；联系人账号数：{ledger['account_count']}")
            print(payload["next_step"])
            return 0
        if args.command == "backup":
            payload = backup_ledger(Path(args.ledger), Path(args.output) if args.output else None)
            return _print_json(payload)
        if args.command == "restore":
            if args.execute:
                payload = apply_restore_plan(Path(args.plan).expanduser().resolve())
            else:
                payload = write_restore_plan(
                    Path(args.backup).expanduser().resolve(),
                    Path(args.ledger).expanduser().resolve(),
                    Path(args.plan).expanduser().resolve(),
                )
            return _print_json(payload)
        if args.command == "upgrade":
            if args.execute:
                payload = apply_upgrade_plan(Path(args.plan).expanduser().resolve())
            else:
                package = Path(args.package).expanduser().resolve()
                from lifecycle import _inspect_zip
                inspected = _inspect_zip(package)
                target = Path(args.target).expanduser().resolve() if args.target else (
                    package_info()["package_root"]
                )
                target = Path(target)
                if not args.target:
                    target = target.parent / f"{target.name}-v{inspected['version']}"
                payload = write_upgrade_plan(package, target, Path(args.plan).expanduser().resolve())
            return _print_json(payload)
        if args.command == "doctor":
            payload = _doctor_payload(root)
            if args.json:
                _print_json(payload)
            else:
                print(payload["status"])
                print(payload["next_step"])
                print(f"网易邮箱大师：{MAILMASTER_URL}")
                print(f"Foxmail：{FOXMAIL_URL}")
            return 0 if payload["status"] == "ready" else 1

        # A null draft sink and direct header method avoid all legacy runtime
        # policy, model, IMAP, DevTools and Feishu services.
        if args.command == "accounts":
            options = _source_options(root, args.source)
            report = {
                "status": "ready" if options else "needs_mail_source",
                "source": args.source, "account_count": len({a.account_email.casefold() for _, _, a in options}),
                "accounts": [
                    {"account_email": item.account_email, "ready": item.ready, "source": kind}
                    for kind, _, item in options
                ],
                "remote_write": False, "local_database_written": False,
            }
            if args.json:
                _print_json(report)
            else:
                for item in report["accounts"]:
                    print(item["source"] + " " + item["account_email"])
            return 0 if options else 1

        if args.days <= 0 or not 1 <= args.email_limit <= 500 or args.limit <= 0:
            raise ValueError("days/limit 必须为正数；email-limit 必须在 1–500 之间。")
        paths = _output_paths(args)
        adapter, selected, _ = _pick_source(root, args.account, args.source)
        _protect_source_outputs(adapter, paths.values())
        response = adapter.list_emails_for_account_email(
            account_email=selected, folder=args.folder, limit=args.email_limit
        )
        payload = build_contact_preview(
            response, account_email=selected, folder=args.folder, days=args.days,
            email_limit=args.email_limit, limit=args.limit,
        )
        _export_outputs(payload, paths, export_contacts_excel, render_contacts_html)
        safe = _contact_result_summary(payload)
        if args.json:
            _print_json(safe)
        else:
            print(f"范围：近 {safe['window_days']} 天；邮件 {safe['emails_in_scope']} 封；"
                  f"联系人候选 {safe['candidate_count']} 个；输出 {safe['returned_count']} 个。")
            if safe["scope_truncated"]:
                print("本次读取达到上限；结果不能代表全历史。")
            for key in ("html_path", "excel_path"):
                if safe.get(key):
                    print(f"{key}={safe[key]}")
        return 0
    except ExportFailure as exc:
        _print_json(exc.summary(args.command))
        return 1
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        # Avoid raw traceback, email addresses, SQL values, or paths in errors.
        message = str(exc)
        if "@" in message:
            message = "本地读取失败；请运行 doctor 检查来源，再选择一个已就绪账号。"
        payload = {
            "status": "error", "error": message, "remote_write": False,
            "local_database_written": False, "mailmaster_official_url": MAILMASTER_URL,
        }
        if args.json:
            _print_json(payload)
        else:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
