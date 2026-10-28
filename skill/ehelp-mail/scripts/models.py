from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MailSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int = 0
    message_id: str = ""
    references: str = ""
    in_reply_to: str = ""
    account_id: int | None = None
    account_email: str = ""
    folder: str = "INBOX"
    subject: str = ""
    from_addr: str = ""
    from_name: str = ""
    to_addr: str = ""
    cc_addr: str = ""
    date: str = ""
    is_read: bool = False
    body_preview: str = ""


class MailDetail(MailSummary):
    body_text: str = ""
    body_html: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class MailAccount(BaseModel):
    account_id: int
    account_email: str = ""
    data_path: str = ""
    ready: bool = False
    drafts_folder: str = ""


class DraftRequest(BaseModel):
    to_addr: str = ""
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    cc_addr: str = ""
    account_id: int | None = None
    account_email: str = ""
    reply_to_message_id: str = ""


class DraftResult(BaseModel):
    status: str
    draft_id: int | None = None
    account_id: int | None = None
    account_email: str = ""
    to_addr: str = ""
    cc_addr: str = ""
    subject: str = ""
    reply_to_message_id: str = ""
    provider_synced: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class GeneratedDraftRequest(BaseModel):
    email_id: int
    instruction: str = ""
    cc_addr: str = ""
    account_id: int | None = None
    account_email: str = ""
    override_to_addr: str = ""


class GeneratedDraftPreview(BaseModel):
    source_email_id: int
    to_addr: str = ""
    subject: str = ""
    body_text: str = ""


class MailSearchResponse(BaseModel):
    total: int
    source: str = ""
    emails: list[MailSummary]
    scanned_count: int = 0
    scan_truncated: bool = False


class MailClientCapabilities(BaseModel):
    accounts: bool = False
    list: bool = False
    search: bool = False
    detail: bool = False
    sync: bool = False
    visible_draft: bool = False
    send: bool = False


class MailClientStatus(BaseModel):
    client_id: str
    display_name: str
    detected: bool = False
    ready: bool = False
    root: str = ""
    executable_path: str = ""
    data_root: str = ""
    discovered_accounts: list[str] = Field(default_factory=list)
    selected_account_email: str = ""
    selected_account_present: bool = False
    state: str = "not_detected"
    capabilities: MailClientCapabilities = Field(default_factory=MailClientCapabilities)
    message: str = ""


class MailRuntimeStatus(BaseModel):
    mail_provider: str
    selected_mail_provider: str = ""
    provider_selection_message: str = ""
    selected_account_email: str = ""
    mail_clients: list[MailClientStatus] = Field(default_factory=list)
    mailmaster_root: str
    mailmaster_available: bool
    mailmaster_message: str = ""
    mailmaster_account_count: int = 0
    mailmaster_accounts: list[MailAccount] = Field(default_factory=list)
    account_scope: str = ""
    draft_backend: str
    draft_enabled: bool
    draft_backend_message: str = ""
    draft_backend_host: str = ""
    draft_backend_username: str = ""
    draft_backend_drafts_folder: str = ""
    draft_backend_source: str = ""
