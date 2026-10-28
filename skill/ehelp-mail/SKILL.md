---
name: ehelp-mail
display_name: "易邮｜邮件往来联系人整理"
display_name_en: "Ehelp Mail | Local Contact Organizer"
description: "当用户想整理邮箱联系人、导出邮件往来联系人Excel、标记重点联系人、查看最近新增或变化的联系人时使用。本技能仅对用户电脑上已同步的网易邮箱大师或测试适配的Foxmail进行本地邮件头读取，不读正文、不发送邮件。"
description_zh: "从电脑上已同步的邮件中整理往来联系人，查看新增和变化、标记重点、导出本地Excel和网页。Windows版；网易邮箱大师为主要适配来源，Foxmail为测试适配。首次需要Python 3.11+和安装依赖；不登录邮箱服务器，不读正文和附件，不发信，不上传联系人。"
description_en: "Organize contacts from locally synced mail headers, review changes, mark important contacts, and export local HTML/Excel. Windows with NetEase MailMaster; Foxmail support is experimental. Requires Python 3.11+ for setup. No mail-server login, body/attachment reads, sending, or contact uploads."
examples_zh:
  - "帮我整理最近30天邮件里往来过的联系人，导出Excel。"
  - "更新我的联系人台账，告诉我这次新增和变化了多少人。"
  - "把我指定的联系人标记为关注，并保存备注。"
examples_en:
  - "Organize contacts from my last 30 days of locally synced emails and export Excel."
  - "Update my contact list and summarize what's new or changed."
  - "Mark a specific contact as followed and save my note."
version: 0.2.6
author: "易邮 Ehelp Mail"
---

# 易邮｜把邮件里的往来联系人整理清楚

## 工作原则（先读）

- 只处理**用户明确授权的、当前设备可访问的**本地邮件来源。邮件头包括收发件地址、时间、主题；主题可能包含敏感信息，网页/Excel/本地台账也不是加密文件。**不读取正文、附件、密码、Token；不发送邮件、不调用邮件服务器、不向外部上传联系人。**
- **必须先确认执行位置。** WorkBuddy 的付费/云端环境不保证能访问购买者电脑上的本地文件和可执行程序。如果当前运行环境无法直接访问用户电脑的文件和命令，不得假装能整理，不得要求用户上传整个邮箱或联系人数据库，也不得绕过限制；如实说明本版本需要本机执行条件并使用平台反馈渠道。仅仅成功解析或安装 ZIP 不等于完成本机功能验收。
- 仅在 **Windows + 用户已同步的网易邮箱大师** 上作为主要体验路径。Foxmail 是受控测试适配：可读本地邮件头，但正在同步时的源文件变化场景未完成现场验收；发生变化时停止并提示。Mac/Linux 不能当作已支持的本机邮件扫描平台；现有台账可以按文档离线查看。不要 SSH、远程读取其他电脑、整盘寻找邮件数据、修改邮箱客户端源数据。
- 先完成用户任务，再可**仅当用户主动提出**相关需求时说明邮箱工作处理或行业工具的其他服务；不要为营销插入广告、外链或要求用户留下联系人名单。用户信息仅保存在其授权的本地位置。
- 技能程序位于当前 `SKILL.md` 同级的 `scripts/`，不可调用机器上旧版同名 Skill、全局 CLI 或其他仓库。详细命令读 @references/CONTACTS_MVP.md；首次说明读 @references/QUICKSTART.md；隐私和反馈读 @references/PRIVACY_AND_FEEDBACK.md。

## 用户说“整理邮件里的联系人”时

**把操作步骤藏在 Agent 内，不让普通用户学习 CLI、SQLite、计划哈希。** 默认处理一个邮箱、最近 **30 天**，一次最多 **200 条来源记录**，导出页面最多 **100 人**；这是一批有界扫描，不是全历史，更不能承诺找到所有客户。用户指定时间范围优先；不自动扩大到全库。

1. 只读检查本机系统环境。若不是用户 Windows 本地执行环境，明确停止并解释；无需安装任何东西。若 Windows 尚无 `scripts/.venv/Scripts/python.exe`，在说明需要 Python 3.11+、首次可能联网下载已固定版本的依赖后，获得用户授权才运行 `scripts/install.bat`，安装到本 Skill 的独立目录，不装全局软件。不得因失败反复自动安装。
2. 在技能目录使用 `scripts/ehelp_mail.bat --json version` 确认版本；随后 `scripts/ehelp_mail.bat --json doctor`。已装客户端却发现失败时先检查用户自定义目录、登录状态与本地同步状态；不直接让用户重装。绝不索取邮箱密码、验证码、授权码。
3. `scripts/ehelp_mail.bat --json accounts` 列出可用账号。**仅一个**可默认选择；多个让用户选一个，不能自动扫描其他邮箱。相同邮箱在两个客户端时主要路径先选邮箱大师；已建立台账的来源不能无确认切换。Foxmail 自定义根目录需用户明确提供，并仅在本次进程设置 `FOXMAIL_ROOT`；详情见命令说明。
4. 先向用户说明：将读取指定账号的本机邮件头，并在用户电脑上建立**持续可更新的联系人台账**；不会读正文附件或发信。创建一次新的可写输出目录（不在邮箱客户端目录内），例如用户 Documents 下的 `易邮结果/本次时间/`，不要复用已有计划或导出文件名。
5. 在 Windows 技能目录内执行：

   ```powershell
   .\scripts\ehelp_mail.bat --json update --account "用户选定的邮箱" --days 30 --email-limit 200 --plan "本次新结果目录\plan.json"
   ```

   首次**只预览**：展示读取条数、拟新增证据、预计新增联系人、冲突/跳过、范围和是否读完；**不能在预览阶段声称已保存**。用户已经明确提出“整理/更新并导出”时，可沿用该任务授权执行预览计划；只问“能不能整理/看看能干什么”时，不执行写入。只有同一计划文件才可执行：

   ```powershell
   .\scripts\ehelp_mail.bat --json update --execute --plan "本次新结果目录\plan.json"
   .\scripts\ehelp_mail.bat --json report --account "用户选定的邮箱" --limit 100 --export-excel "本次新结果目录\contacts.xlsx" --report-html "本次新结果目录\contacts.html"
   ```

6. 返回**用户看得懂的结果**：累计联系人总数、本次新增/更新人数、人工关注人数、是否还有未读批次、异常条数，以及 HTML/Excel 的本地路径（若宿主支持则提供可访问的本地文件入口）。不要在聊天里粘贴联系人姓名/邮箱/主题/备注；默认不读取导出文件内容回传给 AI。**页面显示人数是导出上限，台账保留的人数可能更多。**
7. 如果 `scan_complete=false`，必须告知只完成一批；用户要求“继续/更新下一批”时，使用**同一个账号与扫描范围，新建 plan.json** 继续，不静默循环直至扫完。范围调整需要按现有扫描规则处理，不擅自 `--restart-scan`。扫描完成后用户以后再次说“更新联系人”，才启动新一轮扫描。结果为 0 且扫描未完成，不能说邮箱没有往来联系人。

## 用户说“更新 / 看新增 / 标记重点”时

- **更新**：先用 `--json status` 查看本地台账；按同一来源和范围预览、执行更新，再用 `report` 导出新文件。若之前尚未完成，按原范围继续。报告的“本批新增/更新”是最近一次成功执行批次，不是全部历史变化。
- **看新增/最近变化/人工关注**：针对已存在的台账执行 `report --view new|recent|followed`，只生成用户指定的新 HTML/Excel 文件；无需重新读取邮件源。导出数不足不等于台账被截断。
- **人工标记**：只处理用户明确指定的联系人邮箱、姓名/关注状态/备注；先预览 `annotate`，在任务授权下再加 `--execute`。备注写 UTF-8 本地文件，不把 AI 推断的姓名、客户价值或商机当事实。
- **安全表达**：往来多只是“可优先复核”，不是高价值客户；无新邮件不能推断客户流失。读取范围只覆盖本机**已同步**数据。`scan_requires_review=true` 时说明冲突或跳过可能影响结果。不能把“扫描窗口已读完”等于“邮箱全历史齐全”。

## 异常与数据保护

- `doctor` 若检测不到有效本地来源，先引导用户检查客户端已登录并完成同步、自定义路径、所选账号是否就绪；只提供官方客户端安装来源，不请求密码。如果当前 WorkBuddy 的执行位置并非本机，应该告知平台环境限制，不能以“成功安装依赖”掩盖无法读取本机数据库。
- `update` 计划为一次性预览，计划过期或冲突就重新预览；不改计划文件绕过校验。同一计划重试已执行时可能返回 `already_applied`，不得二次计数。
- `report` 失败保留已完成文件，只补缺失结果；输出文件均用新名字，不覆盖或删除旧成果。台账和结果不得写入邮箱客户端数据目录。
- 用户要求换包/搬迁前先 `backup`。WorkBuddy 市场发布的 ZIP **不是** `upgrade` 命令接收的扁平独立程序升级 ZIP；市场版使用平台的技能更新流程。`upgrade` 仅用于明确提供了扁平程序发布包的独立安装场景，不能把本市场 ZIP 直接交给它。`restore` 先预览后按授权执行，不覆盖现有台账。详情见 @references/CONTACTS_MVP.md。
- 用户问费用、更新、售后时，不假设平台价格或优惠机制；收费由 WorkBuddy 上架页确定。反馈使用平台内置评价/反馈渠道；不要主动索取或上传联系人列表、邮件内容、台账数据库、原始错误日志。

## 对外效果承诺

让用户在第一次使用时得到一个可在本地打开的“联系人概览 + 表格”，之后能增量整理和人工关注。**本版不是 CRM，也不包含邮件自动回复、邮件发送、飞书写入、JCTrans 自动报价、定时后台扫描或企业实施服务。**
