from __future__ import annotations

from pathlib import Path

from models import MailClientCapabilities, MailClientStatus

# macOS 邮件客户端候选数据目录。注意：本模块只做“存在性探测”与就绪度标记，
# 不解析任何邮件内容。macOS 来源的解析逻辑尚未在真实 macOS 上现场验收，
# 因此无论是否探测到，都标记为未验收，默认不扫描（与 Windows 的 Foxmail 候选策略一致）。
FOXMAIL_MAC_CANDIDATES = (
    Path.home() / "Library" / "Containers" / "com.tencent.Foxmail" / "Data",
    Path.home() / "Library" / "Application Support" / "Foxmail",
)

APPLE_MAIL_CANDIDATES = (
    Path.home() / "Library" / "Mail",
)


def _first_existing(candidates) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def discover_macos_clients(root: Path, *, selected_account_email: str = "") -> list[tuple[str, MailClientStatus]]:
    clients: list[tuple[str, MailClientStatus]] = []

    foxmail_root = _first_existing(FOXMAIL_MAC_CANDIDATES)
    clients.append((
        "macos-foxmail",
        MailClientStatus(
            client_id="macos-foxmail",
            display_name="Foxmail (macOS, 候选/未验收)",
            detected=foxmail_root is not None,
            root=str(foxmail_root) if foxmail_root else "",
            state="detected_unvalidated" if foxmail_root else "not_detected",
            capabilities=MailClientCapabilities(accounts=True, list=True),
            message=(
                "已在 macOS 探测到 Foxmail 数据目录，但解析逻辑尚未现场验收；"
                "默认不扫描，需在 Mac 上由用户确认后启用。"
            ) if foxmail_root else "未检测到 macOS 版 Foxmail 数据目录",
        ),
    ))

    apple_root = _first_existing(APPLE_MAIL_CANDIDATES)
    clients.append((
        "macos-mail",
        MailClientStatus(
            client_id="macos-mail",
            display_name="Apple Mail (macOS, 候选/未验收)",
            detected=apple_root is not None,
            root=str(apple_root) if apple_root else "",
            state="detected_unvalidated" if apple_root else "not_detected",
            capabilities=MailClientCapabilities(accounts=True, list=True),
            message=(
                "已在 macOS 探测到 Apple Mail 数据目录，但解析逻辑尚未现场验收；"
                "默认不扫描，需在 Mac 上由用户确认后启用。"
            ) if apple_root else "未检测到 Apple Mail 数据目录",
        ),
    ))

    return clients
