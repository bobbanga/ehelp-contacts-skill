# 本地联系人工作台：命令说明

当前候选版本为 `0.2.7`。这份说明只覆盖本地联系人整理和本机升级保护；正文事项分析、自动回信、报价和飞书写入不在本版。

> **平台说明**：下方示例以 Windows 的 `.\ehelp_mail.bat` / `.\install.bat` 书写。**macOS / Linux** 请将入口替换为 `./run.sh`（运行）与 `./install.sh`（安装），例如在 Mac 上用 `./run.sh --json doctor`。macOS 来源的解析尚未现场验收，默认只探测、不扫描。

## 先看包和台账

```bat
.\ehelp_mail.bat --json version
.\ehelp_mail.bat --json status
```

`version` 用来确认 Agent 没有误调用旧包；`status` 只显示包、默认台账是否存在、台账是否可读和账号数量，不贴联系人明细。

## 备份、恢复和升级

```bat
.\ehelp_mail.bat --json backup --ledger "%LOCALAPPDATA%\ehelp-mail\contacts.sqlite3"
.\ehelp_mail.bat --json upgrade --package ".\新包.zip" --plan ".\本次升级\upgrade-plan.json"
.\ehelp_mail.bat --json upgrade --execute --plan ".\本次升级\upgrade-plan.json"
```

**注意**：以上 `upgrade` 命令只接受 `release.json`、`install.bat` 等位于 ZIP 根目录的“扁平独立程序升级包”，**不能直接使用 WorkBuddy 技能市场 ZIP**（后者的程序位于 `ehelp-mail/scripts/`）。WorkBuddy 市场包应通过平台的技能更新流程操作；台账保存在默认本地目录，换版之前先备份。独立程序升级预览会核对 ZIP 哈希、发布版本、清单和 Windows 启动文件；执行时解压到新目录，旧目录和默认台账不覆盖。`install.bat` 和 `doctor` 仍需在新目录分别运行。需要恢复时，先用 `restore --backup ... --ledger 新路径 --plan ...` 预览，再对同一计划加 `--execute`；已有目标文件不会被覆盖。

本版从联系人 MVP 延续。原来的 `contacts` 仍是一次性预览/导出，不记进度；持续使用改用 `update → report`。全部命令只读邮箱源库，只有 `update --execute` 和 `annotate --execute` 写联系人台账。

## 第一次与下一次

以下 PowerShell 命令由 Agent 执行。替换邮箱与每次唯一的结果目录。`--json` 放在子命令前。

```powershell
.\install.bat
.\ehelp_mail.bat --json doctor
.\ehelp_mail.bat --json accounts
.\ehelp_mail.bat --json update --account "owner@example.com" --days 30 --email-limit 200 --plan ".\results\本次时间\plan.json"
.\ehelp_mail.bat --json update --execute --plan ".\results\本次时间\plan.json"
.\ehelp_mail.bat --json report --account "owner@example.com" --limit 100 --export-excel ".\results\本次时间\contacts.xlsx" --report-html ".\results\本次时间\contacts.html"
```

安装只做一次。预览后报告范围与数量，按用户已有授权执行；同一计划重复执行返回 `already_applied`。预览文件只含选中邮箱、范围、进度摘要哈希和台账路径，不含联系人明细。预览不写联系人数据库。

每批读取的来源记录不超过 `--email-limit`（1–500，CLI底层默认100），`--days` CLI 底层默认7；WorkBuddy 技能的建议首次调用显式指定近30天、每批200条、单次导出100人。`scan_complete=false` 时下次同参数、新计划文件继续旧范围，时间上界冻结为本轮首次预览时刻。已完成后下一次重扫所选日期窗口，依靠台账去重；不依赖“本地编号必然递增”的假设。扫描中途新同步的数据可能要下轮才发现。

中途改范围会提示先继续或明确 `--restart-scan`；这个参数只重置扫描进度，不删除已整理联系人。不要替客户默认扩大成全历史。重复、冲突、跳过分别计数。邮箱大师的无有效日期记录在日期筛选前排除；Foxmail 的缺失/无日期记录计入读取及跳过，日期范围外记录另计 `scan_outside_window_count`，都不计入联系人。

`--limit` 只限制结果导出人数，不影响台账保留该批所有候选人。台账累计范围可能大于最近一轮的时间窗口。未完成/冲突记录不可称全部整理成功。

## 人工确认

```powershell
.\ehelp_mail.bat --json annotate --account "owner@example.com" --email "peer@example.com" --name "王先生" --follow yes --note-file ".\我的备注.txt"
.\ehelp_mail.bat --json annotate --account "owner@example.com" --email "peer@example.com" --name "王先生" --follow yes --note-file ".\我的备注.txt" --execute
.\ehelp_mail.bat --json report --account "owner@example.com" --view followed --report-html ".\results\新的时间\followed.html" --export-excel ".\results\新的时间\followed.xlsx"
```

`--view` 可选 `all`、`new`、`recent`、`followed`。new/recent 指最近成功写入批次的变化；重新执行相同计划不改变这批记录。人工姓名最长200字、备注4000字。仅修改用户指定项，空姓名/空备注文件用于清空；从不合并不同邮箱。

## 台账与隐私

默认位置 `%LOCALAPPDATA%\ehelp-mail\contacts.sqlite3`；测试可给 update/annotate/report 都加相同 `--ledger "独立路径\contacts.sqlite3"`，执行必须与预览中的路径相同。

SQLite 随 Python 提供，不需要安装数据库服务。保存的是联系人、每封已整理邮件的去重键/日期/主题、收发参与证据、人工标记和扫描进度，不含正文附件或邮箱密钥。关闭正在操作台账的命令后可复制备份；不支持跨电脑同时写同一文件或自动同步。新包使用原默认台账，旧 HTML 仍然是静态快照。

同一邮箱换来源客户端或路径时暂停自动合并，使用独立台账验证；当前没有自动迁移/跨来源合并功能。没有 Message-ID 时按来源、文件夹、本地编号去重，不能保证跨文件夹副本去重。相同 Message-ID 却有不同参与人/日期/主题，暂跳过后到数量报告中提示复核。

程序本身不联网、不调用模型。Agent 的聊天仍由用户使用的 Agent 服务处理，所以默认只返回数量和路径，不读取明细进聊天。第一次 install 可能联网下载 Python 依赖，安装完成后的整理和导出可离线进行。

本次发布包为 0.2.7（市场体验候选）。Windows 网易邮箱大师沿用稳定试用路径；Foxmail 已通过98封真实历史样本及 Windows 当前安装目录的只读流程：近7天、首批100条索引整理出38个联系人；另已验证客户端打开时的一批读取：100条索引中47封在范围内，整理出50个联系人，重复执行未新增计数。测试期间未观察到源文件变化，不能当作正在同步的并发验收；客户独立使用尚未验收。数字为测试结果，不是开箱承诺。Mac 来源、飞书写入、正文事项分析均未开放。

## Foxmail 测试来源

`accounts`、`contacts`、`update` 支持 `--source auto|mailmaster|foxmail`。auto 在新台账中优先邮箱大师，同一邮箱不混两套客户端；已有台账自动沿用原来源和账号。选定来源失败后不会换另一个客户端继续。执行时沿用计划绑定的来源。

Foxmail 从 FMStorage.list 和 Storage 账号目录发现数据，只读文件夹索引、邮件存储元数据和 RFC 邮件头；不读 Accounts 凭证、正文和附件。自定义路径仅通过本次进程 `FOXMAIL_ROOT` 指向用户明确给出的客户端目录，不扫描整盘，不寻找历史备份替代用户当前数据。

用户明确提供自定义安装目录时，Agent 在每次相关 PowerShell 调用中先设置本次进程变量，再运行包内命令。例如（把路径替换为用户给出的实际目录）：

```powershell
$env:FOXMAIL_ROOT = "E:\Data\Mail\Foxmail"
.\ehelp_mail.bat --json doctor
.\ehelp_mail.bat --json accounts --source foxmail
```

后续 update 预览和执行也须带同一进程变量；如果 Agent 每次开新进程，每次重新设置。不要使用 setx，不修改全局变量，不替换计划内的来源或台账。这个示例路径不是程序默认值。

按本地编号从大到小分批，再检查邮件日期，编号不等于时间。`--email-limit 100` 最多检查100条索引，不保证其中有100封近期邮件；未下载、无日期、范围外都会减少候选数量。`scan_complete=false` 时不能据空结果断定没有近期邮件。未完成的扫描固定编号上界，过程中补入的邮件可能下轮重扫才发现。

默认 ALL 排除已有草稿、垃圾和已删除索引；SENT 使用已发送索引；INBOX 必须有明确收件箱索引，否则拒绝，不猜收件箱。索引/文件在读取时变化或存储格式不支持则停止，等待同步结束后重新预览。

所有台账、预览、导出放在客户端目录之外。旧联系人台账可继续使用；0.2.3及以前尚未执行的预览计划请重新生成，执行时不接受修改或沿用旧计划。
