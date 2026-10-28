from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


PLAN_VERSION = 1
MAX_PACKAGE_FILES = 256
MAX_PACKAGE_BYTES = 200 * 1024 * 1024


def package_root() -> Path:
    return Path(__file__).resolve().parents[0]


def default_ledger() -> Path:
    base = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / ".local/share"
    return base / "ehelp-mail/contacts.sqlite3"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_release(root: Path | None = None) -> dict:
    path = (root or package_root()) / "release.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("发布信息缺失或格式无效。") from exc
    if not isinstance(payload, dict) or not payload.get("version"):
        raise ValueError("发布信息缺失版本号。")
    return payload


def package_info(root: Path | None = None) -> dict:
    root = (root or package_root()).resolve()
    release = _read_release(root)
    identity = package_identity(root)
    return {
        "release": release.get("release", ""),
        "version": release["version"],
        "channel": release.get("release_channel", "unknown"),
        "package_root": str(root),
        "platform_verified": release.get("platform_verified", []),
        "model_required": bool(release.get("model_required", False)),
        "runtime_requires_network": bool(release.get("runtime_requires_network", False)),
        "available_commands": release.get("available_commands", []),
        "license_required": bool(release.get("license_required", False)),
        "package_identity": identity,
    }


def package_identity(root: Path | None = None) -> dict:
    root = (root or package_root()).resolve()
    release = _read_release(root)
    manifest = root / "MANIFEST.sha256.json"
    if manifest.is_file():
        identity_hash = _sha256(manifest)
        identity_source = "MANIFEST.sha256.json"
    else:
        identity_hash = _sha256(root / "release.json")
        identity_source = "release.json"
    return {
        "release": release.get("release", ""), "version": release["version"],
        "hash": identity_hash, "hash_source": identity_source,
    }


def ledger_info(path: Path | None = None) -> dict:
    path = (path or default_ledger()).expanduser().resolve()
    result = {
        "ledger_path": str(path),
        "exists": path.is_file(),
        "schema_version": None,
        "revision": None,
        "account_count": 0,
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "valid": False,
    }
    if not path.is_file():
        return result
    try:
        uri = path.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            meta = conn.execute("SELECT version,revision FROM meta").fetchone()
            if not meta:
                return result
            result.update(
                schema_version=meta[0], revision=meta[1],
                account_count=conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
                valid=meta[0] == 1,
            )
    except (OSError, sqlite3.Error):
        return result
    return result


def status_payload(ledger: Path | None = None) -> dict:
    return {
        "status": "ready",
        "product": "ehelp-mail 本地联系人工作台",
        "package": package_info(),
        "ledger": ledger_info(ledger),
        "remote_calls": 0,
        "remote_write": False,
        "body_read": False,
        "model_required": False,
        "next_step": "先运行 doctor 检查邮箱来源；已有台账可直接运行 report。",
    }


def _check_new_output(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ValueError("目标文件或目录已存在；请使用新的路径，不覆盖旧结果。")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(path.parent, os.W_OK | os.X_OK):
        raise ValueError("目标父目录不可写。")
    return path


def _validate_sqlite(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError("台账备份不存在或不是普通文件。")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            meta = conn.execute("SELECT version FROM meta").fetchone()
            if not meta or meta[0] != 1:
                raise ValueError("这不是当前版本的联系人台账。")
            conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise ValueError("台账备份无法通过 SQLite 检查。") from exc


def _sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            dst.commit()


def backup_ledger(ledger: Path | None = None, output: Path | None = None) -> dict:
    source = (ledger or default_ledger()).expanduser().resolve()
    _validate_sqlite(source)
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output = source.parent / "backups" / f"contacts-{stamp}-{secrets.token_hex(3)}.sqlite3"
    target = _check_new_output(output)
    if target == source:
        raise ValueError("备份目标不能与当前台账相同。")
    _sqlite_backup(source, target)
    _validate_sqlite(target)
    return {
        "status": "backed_up", "ledger_path": str(source), "backup_path": str(target),
        "backup_sha256": _sha256(target), "backup_bytes": target.stat().st_size,
        "ledger_changed": False, "remote_write": False,
    }


def _restore_plan(backup: Path, ledger: Path) -> dict:
    _validate_sqlite(backup)
    if ledger.exists() or ledger.is_symlink():
        raise ValueError("恢复目标已存在；为避免覆盖，请换一个新路径。")
    unsigned = {
        "version": PLAN_VERSION, "backup": str(backup.resolve()),
        "backup_sha256": _sha256(backup), "ledger": str(ledger.resolve()),
    }
    return {**unsigned, "plan_id": _digest(unsigned)}


def write_restore_plan(backup: Path, ledger: Path, plan_path: Path) -> dict:
    plan_path = _check_new_output(plan_path)
    plan = _restore_plan(backup.expanduser().resolve(), ledger.expanduser().resolve())
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "restore_preview", "plan_path": str(plan_path),
        "backup_path": plan["backup"], "ledger_path": plan["ledger"],
        "backup_sha256": plan["backup_sha256"], "would_write": False,
        "remote_write": False,
    }


def apply_restore_plan(plan_path: Path) -> dict:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("恢复预览文件无效，请重新预览。") from exc
    expected = {"version", "backup", "backup_sha256", "ledger", "plan_id"}
    if not isinstance(plan, dict) or set(plan) != expected:
        raise ValueError("恢复预览文件无效，请重新预览。")
    unsigned = {key: value for key, value in plan.items() if key != "plan_id"}
    if plan["version"] != PLAN_VERSION or _digest(unsigned) != plan["plan_id"]:
        raise ValueError("恢复预览文件已被修改，请重新预览。")
    backup, ledger = Path(plan["backup"]).resolve(), Path(plan["ledger"]).resolve()
    if _sha256(backup) != plan["backup_sha256"]:
        raise ValueError("备份文件在预览后发生变化，请重新预览。")
    if ledger.exists() or ledger.is_symlink():
        raise ValueError("恢复目标已存在；没有覆盖，请换一个新路径。")
    _check_new_output(ledger)
    _sqlite_backup(backup, ledger)
    _validate_sqlite(ledger)
    return {
        "status": "restored", "plan_id": plan["plan_id"],
        "ledger_path": str(ledger), "backup_path": str(backup),
        "ledger_changed": True, "remote_write": False,
    }


def _zip_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("升级包包含不安全的文件路径。")
    if ":" in path.parts[0]:
        raise ValueError("升级包包含不安全的文件路径。")
    return path


def _inspect_zip(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("升级包不存在或不是普通文件。")
    with ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_PACKAGE_FILES:
            raise ValueError("升级包文件数量异常。")
        total = 0
        names = []
        for info in infos:
            _zip_member_path(info.filename)
            if info.is_dir() or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("升级包不能包含目录链接或符号链接。")
            total += info.file_size
            names.append(info.filename)
        if total > MAX_PACKAGE_BYTES or "release.json" not in names:
            raise ValueError("升级包缺少发布信息或体积异常。")
        try:
            release = json.loads(archive.read("release.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("升级包的 release.json 无效。") from exc
        if not isinstance(release, dict) or not release.get("version"):
            raise ValueError("升级包缺少版本号。")
        has_windows_launchers = "install.bat" in names and "ehelp_mail.bat" in names
        has_posix_launchers = "install.sh" in names and "run.sh" in names
        if not (has_windows_launchers or has_posix_launchers):
            raise ValueError("升级包缺少启动文件（install.bat/ehelp_mail.bat 或 install.sh/run.sh）。")
        manifest_ok = None
        if "MANIFEST.sha256.json" in names:
            try:
                manifest = json.loads(archive.read("MANIFEST.sha256.json"))
                manifest_ok = all(
                    name in names and hashlib.sha256(archive.read(name)).hexdigest() == digest
                    for name, digest in manifest.items()
                )
            except (KeyError, json.JSONDecodeError, TypeError):
                manifest_ok = False
        return {
            "version": release["version"], "release": release.get("release", ""),
            "channel": release.get("release_channel", "unknown"),
            "file_count": len(infos), "uncompressed_bytes": total,
            "manifest_verified": manifest_ok,
        }


def write_upgrade_plan(package: Path, target: Path, plan_path: Path) -> dict:
    package, target = package.expanduser().resolve(), target.expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise ValueError("升级目标目录已存在；为保护旧版本，请换一个新目录。")
    inspected = _inspect_zip(package)
    plan_path = _check_new_output(plan_path)
    unsigned = {
        "version": PLAN_VERSION, "package": str(package), "package_sha256": _sha256(package),
        "target": str(target), "release_version": inspected["version"],
    }
    plan = {**unsigned, "plan_id": _digest(unsigned)}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "upgrade_preview", "plan_path": str(plan_path), **inspected,
        "package_path": str(package), "package_sha256": plan["package_sha256"],
        "target": str(target), "would_write": False, "ledger_untouched": True,
        "remote_write": False,
    }


def _extract_zip(package: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        with ZipFile(package) as archive:
            for info in archive.infolist():
                relative = _zip_member_path(info.filename)
                destination = (staging / Path(*relative.parts)).resolve()
                if staging.resolve() not in destination.parents:
                    raise ValueError("升级包包含越界路径。")
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
        if not (staging / "release.json").is_file():
            raise ValueError("升级包解压后缺少 release.json。")
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def apply_upgrade_plan(plan_path: Path) -> dict:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("升级预览文件无效，请重新预览。") from exc
    expected = {"version", "package", "package_sha256", "target", "release_version", "plan_id"}
    if not isinstance(plan, dict) or set(plan) != expected:
        raise ValueError("升级预览文件无效，请重新预览。")
    unsigned = {key: value for key, value in plan.items() if key != "plan_id"}
    if plan["version"] != PLAN_VERSION or _digest(unsigned) != plan["plan_id"]:
        raise ValueError("升级预览文件已被修改，请重新预览。")
    package, target = Path(plan["package"]).resolve(), Path(plan["target"]).resolve()
    if _sha256(package) != plan["package_sha256"]:
        raise ValueError("升级包在预览后发生变化，请重新预览。")
    inspected = _inspect_zip(package)
    if inspected["version"] != plan["release_version"]:
        raise ValueError("升级包版本在预览后发生变化，请重新预览。")
    if target.exists() or target.is_symlink():
        raise ValueError("升级目标目录已存在；没有覆盖旧版本。")
    _extract_zip(package, target)
    return {
        "status": "upgrade_prepared", "plan_id": plan["plan_id"],
        "release_version": inspected["version"], "target": str(target),
        "ledger_untouched": True, "remote_write": False,
        "next_step": "在新目录运行对应平台的安装脚本（Windows: install.bat；macOS/Linux: install.sh），"
                     "然后运行启动脚本 --json doctor。",
    }
