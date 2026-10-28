from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _text(value: object) -> str:
    return str("" if value is None else value).strip()


def _cell(value: object) -> str:
    return html.escape(_text(value), quote=True) or "-"


def _list_cell(value: object) -> str:
    if isinstance(value, list):
        items = [_text(item) for item in value if _text(item)]
        if items:
            return "<br>".join(html.escape(item, quote=True) for item in items)
    return _cell(value)


def _relative_file_link(report_path: Path, raw_path: object) -> str:
    value = _text(raw_path)
    if not value:
        return ""
    # Reject network/device paths and URI schemes before touching the filesystem.
    # On Windows, resolving a UNC path can itself initiate network I/O or stall.
    if value.replace("\\", "/").startswith("//"):
        return ""
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value) and not re.match(r"^[A-Za-z]:[/\\]", value):
        return ""
    try:
        target = Path(value).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        else:
            target = target.resolve()
        report_root = report_path.parent.resolve()
        try:
            target.relative_to(report_root)
        except ValueError:
            # Do not let a report become a path traversal launcher. The MVP
            # writes Excel beside the HTML report; an outside path is shown as
            # unavailable instead of linked.
            return ""
        relative = os.path.relpath(target, report_root).replace(os.sep, "/")
        return quote(relative, safe="/")
    except (OSError, ValueError):
        return ""


def _metric(label: str, value: object) -> str:
    return (
        '<div class="metric">'
        f'<div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{_cell(value)}</div>'
        "</div>"
    )


def _candidate_row(item: dict[str, Any]) -> str:
    return "<tr>" + "".join(
        (
            f"<td>{_cell(item.get('name'))}</td>",
            f"<td class=\"email\">{_cell(item.get('email'))}</td>",
            f"<td>{_cell(item.get('candidate_type'))}</td>",
            f"<td><strong>{_cell(item.get('importance_level'))}</strong>"
            f"<br><span class=\"muted\">{_cell(item.get('importance_score'))} 分</span></td>",
            f"<td>{_list_cell(item.get('importance_reasons'))}</td>",
            f"<td>{_cell(item.get('interaction_direction'))}"
            f"<br><span class=\"muted\">{_cell(item.get('interaction_count'))} 次</span></td>",
            f"<td>{_cell(item.get('last_interaction'))}</td>",
            f"<td>{_list_cell(item.get('recent_subjects'))}</td>",
        )
    ) + "</tr>"


def render_contacts_html(payload: dict[str, Any], output_path: str | Path, *, exclusive: bool = False) -> Path:
    """Render a dependency-free, local-only contact result page.

    The report is a snapshot of the already-built contact preview. It does not
    read mail, run JavaScript, call a remote URL, or write back to any service.
    """
    report_path = Path(output_path).expanduser()
    if report_path.suffix.casefold() != ".html":
        raise ValueError("--report-html 的路径必须以 .html 结尾")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if "scan" in payload:
        return _render_workbench(payload, report_path, exclusive=exclusive)

    candidates = [item for item in payload.get("candidates", []) if isinstance(item, dict)]
    excel_link = _relative_file_link(report_path, payload.get("excel_path"))
    excel_block = (
        f'<a class="button" href="{html.escape(excel_link, quote=True)}">打开 Excel 结果</a>'
        if excel_link
        else '<span class="muted">本次没有指定 Excel 文件</span>'
    )
    scope_note = _text(payload.get("importance_scope")) or "重点候选只代表本次读取范围内的排序。"
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    rows = "".join(_candidate_row(item) for item in candidates)
    if not rows:
        rows = '<tr><td class="empty" colspan="8">本次范围没有联系人候选。</td></tr>'

    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>联系人整理结果</title>
  <style>
    :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    body {{ margin: 0; background: #f5f7fa; color: #172033; }}
    main {{ max-width: 1500px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 19px; }}
    .muted {{ color: #697386; font-size: 13px; }}
    .notice {{ margin: 18px 0; padding: 14px 16px; border-left: 4px solid #356ae6; background: #edf3ff; border-radius: 6px; line-height: 1.6; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; margin: 20px 0; }}
    .metric {{ background: white; border: 1px solid #e2e7ef; border-radius: 8px; padding: 14px; }}
    .metric-label {{ color: #697386; font-size: 13px; }}
    .metric-value {{ margin-top: 5px; font-size: 23px; font-weight: 650; }}
    .actions {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
    .button {{ display: inline-block; padding: 9px 13px; color: white; background: #356ae6; border-radius: 6px; text-decoration: none; }}
    .table-wrap {{ overflow-x: auto; background: white; border: 1px solid #e2e7ef; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1120px; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid #edf0f5; text-align: left; vertical-align: top; line-height: 1.45; }}
    th {{ position: sticky; top: 0; background: #f8faff; color: #4d5a70; font-size: 13px; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: 0; }}
    .email {{ white-space: nowrap; }}
    .empty {{ padding: 35px; text-align: center; color: #697386; }}
    footer {{ margin-top: 24px; color: #697386; font-size: 12px; }}
  </style>
</head>
<body>
<main>
  <h1>联系人整理结果</h1>
  <div class="muted">本地报告 · 生成于 {html.escape(generated)}</div>
  <div class="notice">{html.escape(scope_note)}<br>本页只展示邮件头部整理结果，不代表客户角色、商机判断或完整历史。正文、附件、报价和飞书写入都不在本次操作中。</div>
  <div class="metrics">
    {_metric("邮箱来源", payload.get("source"))}
    {_metric("读取范围", f"近 {payload.get('window_days', '-')} 天")}
    {_metric("范围内邮件", payload.get("emails_in_scope", 0))}
    {_metric("联系人候选", payload.get("candidate_count", 0))}
    {_metric("本页显示", payload.get("returned_count", 0))}
    {_metric("重点候选", payload.get("important_candidate_count", 0))}
  </div>
  <div class="actions">{excel_block}<span class="muted">账号：{_cell(payload.get("account_email"))} · 文件保存在本机</span></div>
  <h2>联系人候选</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>姓名</th><th>邮箱</th><th>类型</th><th>候选等级</th><th>原因</th><th>往来</th><th>最近互动</th><th>最近主题</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <footer>本页由 ehelp-mail 联系人 MVP 生成。请通过 Agent 发起下一步工作；不要直接修改本页来代替源邮箱或联系人确认。</footer>
</main>
</body>
</html>
"""
    _write_document(report_path, document, exclusive=exclusive)
    return report_path


def _write_document(path, document, *, exclusive):
    if exclusive:
        with path.open("x", encoding="utf-8") as out:
            out.write(document)
    else:
        path.write_text(document, encoding="utf-8")


def _render_workbench(payload: dict[str, Any], path: Path, *, exclusive=False) -> Path:
    scan = payload["scan"]
    last = payload["last_batch"]
    labels = {"all": "全部联系人", "new": "最近一批新联系人", "recent": "最近一批有变化", "followed": "我关注的人"}
    view = labels[payload["view"]]
    def date(number):
        return datetime.fromtimestamp(number, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %z")
    excel = _relative_file_link(path, payload.get("excel_path"))
    excel_link = f'<a href="{html.escape(excel, quote=True)}">打开本次 Excel</a>' if excel else "未导出同目录 Excel"
    rows = []
    for p in payload["candidates"]:
        rows.append("<tr>" + "".join((
            f'<td><strong>{_cell(p["name"])}</strong><br>{_cell(p["email"])}</td>',
            f'<td>{_cell(p["followed"])}<br>{_cell(p["note"])}</td>',
            f'<td>{_cell(p["change"])}</td>',
            f'<td>{p["received_count"]} / {p["sent_count"]}<br>共同收件或抄送 {p["co_recipient_count"]}</td>',
            f'<td>{_cell(p["first_interaction"])}<br>{_cell(p["last_interaction"])}</td>',
            f'<td>{_cell(p["importance_level"])}<br>{_list_cell(p["importance_reasons"])}</td>',
            f'<td>{_list_cell(p["recent_subjects"])}</td>',
        )) + "</tr>")
    if not rows:
        rows.append('<tr><td colspan="7">这个视图暂时没有联系人。可让 Agent 查看全部联系人或检查处理范围。</td></tr>')
    complete = "本轮已读完本地范围" if scan["complete"] else "本轮还有未读批次"
    truncated = (f'当前视图有 {payload["view_count"]} 人，本页和 Excel 只显示前 {payload["returned_count"]} 人。'
                 if payload["contacts_truncated"] else f'当前视图显示 {payload["returned_count"]} 人。')
    source_note = (f"Foxmail 按本地编号分批，再筛选日期；本轮读取数包含未下载和范围外的索引，其中范围外 {scan.get('outside_window', 0)} 条。还有未读批次时，空结果不能证明近{scan['days']}天没有邮件。"
                   if scan.get("source_kind") == "foxmail" else "邮箱大师按本轮日期范围读取本地邮件头部。")
    scan_state = ("本轮扫描范围已读完" if scan["complete"] else "本轮只完成部分批次，尚有未读数据")
    scan_risks = (f"累计冲突 {scan['conflicts']} 条、其他跳过 {scan['skipped']} 条，请复核覆盖范围。"
                  if scan["conflicts"] or scan["skipped"] else "当前累计未报告冲突或其他跳过。")
    scan_notice = f"{scan_state}。{scan_risks}‘已读完’仅指本机选定范围，不是邮箱历史全量。"
    document = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>我的邮件联系人 · 本地工作台</title>
<style>
body{{margin:0;background:#f4f6fa;color:#192b42;font:15px/1.6 'Segoe UI','Microsoft YaHei',sans-serif}}
main{{max-width:1460px;margin:auto;padding:32px}}h1{{font-size:29px;margin:8px 0}}h2{{font-size:20px}}
.muted{{color:#546477}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:24px 0}}
.metric,section{{background:white;border:1px solid #dbe2ee;border-radius:12px;padding:18px}}
.metric-value{{font-size:27px;font-weight:700}}.notice{{background:#eaf1fc;padding:18px;border-radius:10px}}
section{{margin:20px 0}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:1150px}}
th,td{{padding:12px;border-bottom:1px solid #e6eaf1;text-align:left;vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere}}
th{{background:#f4f6fa}}td{{max-width:330px}}a{{color:#2359b9}}code{{background:#eef2f8;padding:3px 6px}}
footer{{font-size:13px;color:#546477;margin:24px 0}}nav a{{margin-right:20px}}
.scan-state{{background:#fff8e7;border:1px solid #eacb72;border-radius:10px;padding:16px 18px;margin:16px 0}}
.summary-title{{font-size:16px;font-weight:700;margin-bottom:6px}}.privacy{{font-size:13px;color:#546477}}
</style></head><body><main>
<p class="muted">易邮 · 本机邮件往来整理</p><h1>我的邮件联系人概览</h1>
<p>账号：{_cell(payload["account_email"])} · {excel_link}</p>
<nav><a href="#people">查看联系人</a><a href="#coverage">查看范围</a><a href="#next">下一步怎么说</a></nav>
<div class="metrics">{_metric("累计联系人",payload["candidate_count"])}{_metric("我关注的人",payload["followed_count"])}
{_metric("本批新联系人",last["new_contact_count"])}{_metric("本批更新联系人",last["updated_contact_count"])}
{_metric("重点复核候选",payload["important_candidate_count"])}
{_metric("累计邮件证据",payload["emails_in_scope"])}</div>
<div class="scan-state"><div class="summary-title">本轮覆盖情况</div>{_cell(scan_notice)}</div>
<div class="notice">这是已整理数据的本地快照。人工关注和备注会保留，邮箱里新来的邮件不会自动出现在旧页面里。
请让 Agent 更新并生成新页面。{_cell(payload["importance_scope"])}</div>
<section id="people"><h2>{_cell(view)}</h2><p>{_cell(truncated)}变化指最近一次成功写入的批次，不是所有历史变化。</p>
<div class="scroll"><table><thead><tr><th>联系人</th><th>人工关注 / 备注</th><th>本批变化</th><th>直接收 / 发次数</th>
<th>首次 / 最近互动时间</th><th>候选提示与依据</th><th>最近主题</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section id="coverage"><h2>这份结果覆盖了什么</h2>
<p>{_cell(source_note)}</p>
<p><strong>{complete}</strong> · 文件夹 {_cell(scan["folder"])} · {date(scan["cutoff"])} 至 {date(scan["until"])}。</p>
<p>本轮累计读取 {scan["scanned"]} 条；最近一批读取 {last["scanned_count"]} 条，新增邮件证据 {last["added_mail_count"]} 条，跳过重复 {last["duplicate_mail_count"]} 条。
本轮身份冲突 {scan["conflicts"]} 条，其他跳过 {scan["skipped"]} 条。</p>
<p>累计联系人包括之前各次已经整理的范围；本轮范围只用于说明本轮读取进度。没有日期的邮件未计入；同编号但信息冲突的邮件暂不合并。
这里只能证明读取了当时电脑上已有的数据，不能证明邮箱服务器已经同步齐全。没有新邮件也不代表客户沉默。</p>
<p>扫描中途新增或改动的本地邮件可能在下一轮重扫时才发现。没有 Message-ID 的邮件按来源、文件夹和本地编号识别，跨文件夹副本不能保证合并。</p></section>
<section id="next"><h2>接下来可以做什么</h2>
<p>首次盘点完成后，建议定期更新本地联系人台账，或人工标记需要关注的人。以下动作不会自动发生。</p>
<p><code>继续这个邮箱的下一批，先告诉我范围和数量，再更新本地台账并导出新结果。</code></p>
<p><code>把我指定的联系人标为重点关注，保留备注，然后重新生成查看页。</code></p>
<p><code>更新我的联系人台账，告诉我本次新增和变化多少人，并生成最新清单。</code></p>
<p><code>只给我看本批新联系人 / 最近变化 / 我关注的人，并导出 Excel。</code></p>
<p>请用具体邮箱地址指定要标记的人。页面和 Excel 负责查看；直接改文件不会写回台账。</p></section>
<footer>只读邮箱头部；不读取正文附件，不发信，不报价，不上传飞书。联系人台账、预览、HTML 和 Excel 含本地个人数据，请保存在自己控制的位置。</footer>
</main></body></html>'''
    # Invalid Unicode in third-party headers must not prevent a local export.
    _write_document(path, document.encode("utf-8", errors="replace").decode("utf-8"), exclusive=exclusive)
    return path
