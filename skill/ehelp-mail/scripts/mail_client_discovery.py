from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

from models import MailClientCapabilities, MailClientStatus
from mailmaster_adapter import MailMasterMailAdapter


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def discover_mailmaster_client(
    root_dir: Path,
    *,
    selected_account_email: str = "",
) -> MailClientStatus:
    root = Path(root_dir)
    selected = _normalize_email(selected_account_email)
    capabilities = MailClientCapabilities(
        accounts=True,
        list=True,
        search=False,
        detail=False,
        sync=False,
        visible_draft=False,
        send=False,
    )
    if not (root / "app.db").exists():
        return MailClientStatus(
            client_id="mailmaster",
            display_name="MailMaster",
            root=str(root),
            selected_account_email=selected,
            state="not_detected",
            capabilities=capabilities,
            message="MailMaster app.db not found",
        )

    try:
        # The contact doctor shares the lightweight account selection path:
        # app.db metadata + mail.db existence, never another account's Mailbox.
        accounts = MailMasterMailAdapter(root_dir=root, draft_sink=None).list_accounts()
    except RuntimeError as exc:
        return MailClientStatus(
            client_id="mailmaster",
            display_name="MailMaster",
            detected=True,
            root=str(root),
            selected_account_email=selected,
            state="data_not_ready",
            capabilities=capabilities,
            message=str(exc),
        )

    discovered_accounts = sorted({account.account_email for account in accounts if account.account_email})
    ready_accounts = {
        account.account_email for account in accounts
        if account.account_email and account.ready
    }
    selected_present = bool(selected and selected in ready_accounts)
    ready = selected_present if selected else bool(ready_accounts)
    if ready:
        state = "ready"
        message = ""
    elif selected:
        state = "selected_account_not_found"
        message = "MailMaster data is not ready for the selected account"
    else:
        state = "data_not_ready"
        message = "MailMaster account data not ready"
    return MailClientStatus(
        client_id="mailmaster",
        display_name="MailMaster",
        detected=True,
        ready=ready,
        root=str(root),
        data_root=str(root),
        discovered_accounts=discovered_accounts,
        selected_account_email=selected,
        selected_account_present=selected_present,
        state=state,
        capabilities=capabilities,
        message=message,
    )


def _registry_foxmail_roots() -> list[Path]:
    try:
        import winreg
    except ImportError:
        return []

    roots: list[Path] = []
    keys = (
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\Foxmail"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Tencent\Foxmail"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Tencent\Foxmail"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Foxmail.exe"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Foxmail.exe"),
    )
    value_names = ("", "InstallPath", "InstallDir", "Path")
    for hive, key_name in keys:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for value_name in value_names:
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if isinstance(value, str) and value.strip():
                        candidate = Path(value.strip().strip('"')).expanduser()
                        roots.append(candidate.parent if candidate.suffix.lower() == ".exe" else candidate)
        except OSError:
            continue
    return roots


def _default_foxmail_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("FOXMAIL_ROOT", "").strip()
    if configured:
        roots.append(Path(configured).expanduser())
    roots.extend(_registry_foxmail_roots())
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        program_files = os.environ.get(env_name, "").strip()
        if program_files:
            roots.extend((Path(program_files) / "Foxmail 7.2", Path(program_files) / "Foxmail"))
    roots.extend(
        Path(item)
        for item in (
            r"D:\Program Files\Foxmail 7.2",
            r"D:\Program Files\Foxmail",
            r"D:\Program Files (x86)\Foxmail 7.2",
            r"D:\Program Files (x86)\Foxmail",
            r"C:\Program Files\Foxmail 7.2",
            r"C:\Program Files\Foxmail",
            r"C:\Program Files (x86)\Foxmail 7.2",
            r"C:\Program Files (x86)\Foxmail",
        )
    )
    return roots


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        key = str(path).rstrip("\\/").lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _foxmail_accounts(root: Path) -> list[str]:
    accounts: set[str] = set()
    list_path = root / "FMStorage.list"
    if list_path.exists():
        try:
            data = list_path.read_bytes()
            encoding = "utf-16le" if b"\x00" in data[:64] else "utf-8-sig"
            text = data.decode(encoding, errors="ignore")
            for line in text.splitlines():
                for part in line.replace("/", "\\").split("\\"):
                    candidate = _normalize_email(part.strip().strip('"'))
                    if "@" in candidate:
                        accounts.add(candidate)
        except OSError:
            pass
    storage_root = root / "Storage"
    if storage_root.exists():
        try:
            for path in storage_root.iterdir():
                candidate = _normalize_email(path.name)
                if path.is_dir() and "@" in candidate:
                    accounts.add(candidate)
        except OSError:
            pass
    return sorted(accounts)




def discover_foxmail_client(
    *,
    selected_account_email: str = "",
    candidate_roots: Iterable[Path] | None = None,
) -> MailClientStatus:
    selected = _normalize_email(selected_account_email)
    roots = _unique_paths(candidate_roots if candidate_roots is not None else _default_foxmail_roots())
    root = next(
        (
            candidate
            for candidate in roots
            if (candidate / "Foxmail.exe").exists() or (candidate / "FMStorage.list").exists()
        ),
        None,
    )
    capabilities = MailClientCapabilities()
    if root is None:
        return MailClientStatus(
            client_id="foxmail",
            display_name="Foxmail",
            selected_account_email=selected,
            state="not_detected",
            capabilities=capabilities,
            message="Foxmail not detected",
        )

    executable = root / "Foxmail.exe"
    from foxmail_contact_adapter import FoxmailContactAdapter
    try:
        found = FoxmailContactAdapter(root).list_accounts()
        ready_accounts = {a.account_email for a in found if a.ready}
        accounts = [a.account_email for a in found]
        ready = selected in ready_accounts if selected else bool(ready_accounts)
        message = "" if ready else "Foxmail 账号或本地邮件索引未就绪；请先在客户端登录并同步。"
    except (OSError, ValueError, RuntimeError):
        ready, accounts = False, []
        message = "Foxmail 本地索引无法读取；请等待同步完成后重试。"
    return MailClientStatus(
        client_id="foxmail", display_name="Foxmail", detected=True, ready=ready,
        root=str(root), data_root=str(root) if (root / "FMStorage.list").is_file() else "",
        executable_path=str(executable) if executable.exists() else "",
        discovered_accounts=accounts, selected_account_email=selected,
        selected_account_present=bool(selected and selected in accounts),
        state="ready" if ready else "data_not_ready",
        capabilities=MailClientCapabilities(accounts=True, list=True), message=message,
    )


def discover_clients(
    root: Path,
    *,
    selected_account_email: str = "",
    foxmail_roots: Iterable[Path] | None = None,
) -> list[tuple[str, MailClientStatus]]:
    """平台感知的来源发现。

    - Windows：返回网易邮箱大师与 Foxmail（与历史行为一致）。
    - macOS：返回 macOS 候选来源（Foxmail Mac / Apple Mail），均标记为未验收，
      不解析内容；实际扫描需用户在 Mac 上现场验收后启用。
    """
    if sys.platform == "darwin":
        from macos_discovery import discover_macos_clients
        return discover_macos_clients(root, selected_account_email=selected_account_email)
    mailmaster = discover_mailmaster_client(root)
    foxmail = discover_foxmail_client(candidate_roots=foxmail_roots)
    return [("mailmaster", mailmaster), ("foxmail", foxmail)]
