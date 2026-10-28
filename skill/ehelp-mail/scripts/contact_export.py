from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


CONTACT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("\u90ae\u7bb1", "email"),
    ("\u59d3\u540d", "name"),
    ("\u8054\u7cfb\u4eba\u7c7b\u578b", "candidate_type"),
    ("\u5019\u9009\u7ea7\u522b", "importance_level"),
    ("\u91cd\u8981\u5ea6\u5206\u6570", "importance_score"),
    ("\u5019\u9009\u539f\u56e0", "importance_reasons"),
    ("\u57df\u540d", "domain"),
    ("\u9996\u6b21\u4e92\u52a8", "first_interaction"),
    ("\u6700\u8fd1\u4e92\u52a8", "last_interaction"),
    ("\u4e92\u52a8\u6b21\u6570", "interaction_count"),
    ("\u6536\u4ef6\u6b21\u6570", "received_count"),
    ("\u53d1\u4ef6\u6b21\u6570", "sent_count"),
    ("\u5171\u540c\u6536\u4ef6\u6216\u6284\u9001\u6b21\u6570", "co_recipient_count"),
    ("\u4e3b\u9898\u6570", "unique_subject_count"),
    ("\u5f80\u6765\u65b9\u5411", "interaction_direction"),
    ("\u6700\u8fd1\u4e3b\u98981", "recent_subject_1"),
    ("\u6700\u8fd1\u4e3b\u98982", "recent_subject_2"),
    ("\u6700\u8fd1\u4e3b\u98983", "recent_subject_3"),
    ("\u6765\u6e90", "source"),
    ("人工确认姓名", "confirmed_name"),
    ("人工关注", "followed"),
    ("人工备注", "note"),
    ("最近一批变化", "change"),
)


def _column_name(index: int) -> str:
    result = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _inline_cell(reference: str, value: object, *, style: int = 0) -> str:
    # Mail headers may contain malformed controls/surrogates. XML 1.0 forbids
    # them even when escaped; replace them visibly rather than corrupt XLSX.
    cleaned = "".join(
        char if (ord(char) in (9, 10, 13) or 0x20 <= ord(char) <= 0xD7FF
                 or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF)
        else "\uFFFD"
        for char in str(value or "")
    )
    text = escape(cleaned)
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{text}</t></is></c>'
    )


def _number_cell(reference: str, value: object) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    return f'<c r="{reference}" t="n"><v>{number}</v></c>'


def _worksheet_xml(rows: list[list[object]]) -> str:
    max_row = max(1, len(rows))
    max_col = max(1, len(rows[0]) if rows else 1)
    dimension = f"A1:{_column_name(max_col)}{max_row}"
    body: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_index, value in enumerate(row, start=1):
            reference = f"{_column_name(col_index)}{row_index}"
            if row_index == 1:
                cells.append(_inline_cell(reference, value, style=1))
            elif col_index in {5, 10, 11, 12, 13, 14}:
                cells.append(_number_cell(reference, value))
            else:
                cells.append(_inline_cell(reference, value))
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    widths = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(
            (30, 22, 16, 16, 12, 34, 24, 22, 22, 12, 12, 16, 10, 10, 14, 48, 48, 48, 20, 22, 12, 48, 16),
            start=1,
        )
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{widths}</cols>"
        f"<sheetData>{''.join(body)}</sheetData>"
        f'<autoFilter ref="{dimension}"/>'
        "</worksheet>"
    )


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def _workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="联系人" sheetId="1" r:id="rId1"/>'
        '<sheet name="范围说明" sheetId="2" r:id="rId3"/></sheets></workbook>'
    )


def _rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        "</Relationships>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _core_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>ehelp-mail</dc:creator>'
        '<dc:title>联系人整理结果</dc:title></cp:coreProperties>'
    )


def _app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>ehelp-mail</Application></Properties>'
    )


def _scope_rows(payload):
    rows = [
        ["项目", "说明"], ["所属账号", payload.get("account_email", "")],
        ["生成时间（UTC）", payload.get("generated_at") or datetime.now(timezone.utc).isoformat()],
        ["视图", payload.get("view", "一次性预览")],
        ["联系人总数", str(payload.get("candidate_count", 0))],
        ["视图人数", str(payload.get("view_count", payload.get("candidate_count", 0)))],
        ["导出人数", str(payload.get("returned_count", 0))],
        ["联系人截断", "是，只显示部分联系人" if payload.get("contacts_truncated") else "否"],
        ["本地数据限制", "不能证明邮箱服务器已同步齐全；没有新邮件不代表客户沉默。"],
    ]
    if "scan" in payload:
        from contact_ledger import scan_summary
        scope = scan_summary(payload["scan"])
        rows.extend([
            ["邮件来源", scope["source"]],
            ["读取方式", "按本地编号分批，再筛选日期；含未下载和范围外索引" if scope["scan_order"] == "local_id_desc" else "按日期读取邮件头"],
            ["本轮范围外索引", str(scope["scan_outside_window_count"])],
            ["文件夹", scope["folder"]], ["本轮天数", str(scope["window_days"])],
            ["冻结范围开始（UTC）", scope["window_start"]], ["冻结范围结束（UTC）", scope["window_end"]],
            ["本轮读取状态", "本轮已读完本地范围" if scope["scan_complete"] else "本轮还有未读批次"],
            ["本轮累计读取", str(scope["scan_total_read"])],
            ["本轮累计冲突", str(scope["scan_conflicting_mail_count"])],
            ["本轮累计其他跳过", str(scope["scan_skipped_mail_count"])],
            ["本轮仍需复核", "是" if scope["scan_requires_review"] else "否"],
            ["范围口径", "联系人来自累计台账，不仅限于本轮日期范围；读取完成不代表没有冲突或跳过。"],
        ])
    else:
        rows.extend([
            ["文件夹", payload.get("folder", "")], ["时间窗口（天）", str(payload.get("window_days", ""))],
            ["范围口径", "一次性 contacts 预览，不记录冻结扫描进度，不代表完整通讯录。"],
            ["读取达到上限", "是" if payload.get("scope_truncated") else "否"],
        ])
    return rows


def export_contacts_excel(payload: dict[str, Any], output_path: str | Path, *, exclusive: bool = False) -> Path:
    """Write a dependency-free .xlsx contact result locally."""
    path = Path(output_path).expanduser()
    if path.suffix.casefold() != ".xlsx":
        raise ValueError("--export-excel 的路径必须以 .xlsx 结尾")
    path.parent.mkdir(parents=True, exist_ok=True)
    candidates = payload.get("candidates", [])
    rows: list[list[object]] = [[label for label, _ in CONTACT_COLUMNS]]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        subjects = candidate.get("recent_subjects", [])
        if not isinstance(subjects, list):
            subjects = []
        values: dict[str, object] = dict(candidate)
        if isinstance(values.get("importance_reasons"), list):
            values["importance_reasons"] = "、".join(
                str(value) for value in values["importance_reasons"]
            )
        for index in range(3):
            values[f"recent_subject_{index + 1}"] = (
                subjects[index] if index < len(subjects) else ""
            )
        rows.append([values.get(key, "") for _, key in CONTACT_COLUMNS])
    worksheet = _worksheet_xml(rows)
    temp_name = ""
    try:
        with NamedTemporaryFile(
            mode="wb",
            suffix=".xlsx",
            prefix=f".{path.stem}.",
            dir=str(path.parent),
            delete=False,
        ) as temp:
            temp_name = temp.name
        with ZipFile(temp_name, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _content_types_xml())
            archive.writestr("_rels/.rels", _root_rels_xml())
            archive.writestr("xl/workbook.xml", _workbook_xml())
            archive.writestr("xl/_rels/workbook.xml.rels", _rels_xml())
            archive.writestr("xl/styles.xml", _styles_xml())
            archive.writestr("xl/worksheets/sheet1.xml", worksheet)
            archive.writestr("xl/worksheets/sheet2.xml", _worksheet_xml(_scope_rows(payload)))
            archive.writestr("docProps/core.xml", _core_xml())
            archive.writestr("docProps/app.xml", _app_xml())
        if exclusive:
            # xb refuses an existing target atomically. If copying fails, leave
            # the incomplete target in place for the CLI recovery receipt.
            with Path(temp_name).open("rb") as source, path.open("xb") as target:
                copyfileobj(source, target)
        else:
            Path(temp_name).replace(path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
    return path
