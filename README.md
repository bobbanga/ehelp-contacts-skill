# 易邮｜邮件往来联系人整理

**易邮 v0.2.7 · 免费 · Windows 本地邮件联系人整理 Skill · 公开测试版**

> 帮你整理电脑上已同步邮件中的往来联系人：建立本地台账、查看新增和变化、标记关注、导出 Excel / HTML。

[**在 WorkBuddy 免费安装易邮**](https://www.workbuddy.cn/share/asset?shareCode=xm3CdjLZYN32x8XuJHwet9&sig=57KKo-dO99vMavqi) · [反馈问题](../../issues/new/choose) · [阅读隐私说明](./PRIVACY.md)

> 此仓库是单独发布的 **易邮联系人 Skill**，不包含 `ehelp-mail` 商业邮箱产品、`mail-assistant` 或 `jctrans-cli` 的完整私有项目。WorkBuddy 市场版与本仓 `skill/ehelp-mail/` 的源文件对应 v0.2.7。

## 能做什么

- 从本机已同步的邮件头中整理往来联系人（收发件人、日期、主题等元数据）
- 将联系人持续保存为本地台账，后续重复更新不按重复证据累计
- 按明确的用户指令添加人工关注与备注
- 导出本地 Excel 和 HTML 概览
- 先预览、后执行；对扫描覆盖范围、截断与异常情况给出提示

**它不做什么：** 不读取邮件正文或附件，不发送邮件，不自动报价、不自动邮件跟进、不向作者服务器上传联系人；不是完整 CRM。

## 30 秒了解怎么用

1. 在 [WorkBuddy 技能市场打开易邮](https://www.workbuddy.cn/share/asset?shareCode=xm3CdjLZYN32x8XuJHwet9&sig=57KKo-dO99vMavqi) 并安装。
2. 使用 **Windows**，电脑上已有**登录并完成同步的网易邮箱大师**（主要支持来源），且具备 **Python 3.11+**；首次依赖安装可能访问 Python 软件包源。
3. 在 WorkBuddy 对话输入：**“帮我整理最近30天邮件里往来过的联系人，导出Excel。”**
4. 后续可说：**“更新联系人台账，告诉我这次新增和变化了多少人。”**
5. 必要时让它 **“把我指定的联系人标记为关注，并保存备注。”**

> 注意：是否能执行本机邮件读取，取决于当前 WorkBuddy 运行环境是否具有本地文件与程序执行权限。**市场安装或 ZIP 解析成功不等于本机读取验收成功。**若无法访问本机，请反馈环境信息，不要上传完整邮箱或联系人数据库。

### 本版支持范围

| 项目 | 当前状态 |
|---|---|
| Windows + 网易邮箱大师本地已同步数据 | 主要试用路径 |
| Foxmail | 测试适配；同步时源文件发生变化可能中止 |
| macOS / Linux 实际扫描邮箱 | 尚未验收，不承诺支持 |
| 账号范围 | 一次一个用户选定的账号 |
| 默认扫描 | 最近 30 天，每批最多 200 条来源记录（可明确调整） |
| 导出 | 默认最多 100 个展示联系人；台账不限于该展示数量 |
| 传输/隐私 | 不主动上传联系人；平台聊天内容可能由平台处理 |

**扫描范围并不是邮箱全部历史。** 未同步到本机的邮件不在结果内；发生截断时会提示，不把部分结果说成全量。

## 如何给我们反馈

你完全不需要提供个人邮箱数据。以下反馈最有帮助：

- [遇到问题 / Bug](../../issues/new?template=bug_report.yml)：说明操作系统、客户端、Skill 版本、步骤与简短错误码
- [功能建议](../../issues/new?template=feature_request.yml)：描述你真正想解决的工作问题，而不是只给功能名
- [使用体验](../../issues/new?template=experience_feedback.yml)：是否首次成功、最有用的地方、是否愿意再次使用

请**不要上传**：联系人姓名或邮箱、真实邮件主题、原始邮件、数据库、Excel、完整日志、账号密码、密钥或其他客户资料。提交前请脱敏。

## 代码仓库结构

```text
skill/ehelp-mail/              # 与上架 v0.2.7 对应的 Skill 源文件
  SKILL.md                    # WorkBuddy 调用说明
  scripts/                    # 本地扫描与联系人台账程序
  references/                 # 使用指引与技术边界
scripts/build_workbuddy_zip.py # 从公开源码生成可上传平台的 ZIP
tests/                        # 不接触真实邮箱的静态/打包测试
.github/ISSUE_TEMPLATE/       # Bug、建议、体验反馈表
```

开发者可执行：

```bash
python scripts/validate_public_package.py
python scripts/build_workbuddy_zip.py
python -m unittest discover -s tests -v
```

生成的 ZIP 位于 `dist/ehelp-contacts-workbuddy-v0.2.7.zip`。**普通用户优先通过 WorkBuddy 市场安装**，不需要通过 GitHub 源码操作 Python 命令。

## 版本与路线

- `v0.2.7`：WorkBuddy 覆盖上传修复（导出品牌 ehelp-mail、删除 SECOND-STAGE 文档）。
- `v0.2.6`：首个公开仓基线，专注联系人整理与反馈。
- 下一步按真实反馈决定，暂不承诺自动发送邮件、后台定时扫描或完整 CRM。
- 源代码更新、问题状态和后续版本在 GitHub 记录；WorkBuddy 市场更新仍以平台审核版本为准。

## 开源范围与许可

此仓库拟以 **MIT License** 开源，仅覆盖**本仓公开文件**，不自动授权任何未公开的其他产品代码、客户数据、商标或第三方资源。发布人应在首次公开前核对每个文件的权利归属和第三方许可证；参见 [LICENSE](./LICENSE)。

## 作者及项目背景

易邮是 AI 办公和业务自动化实践中的一个独立小工具，先验证“真实用户能否安全、方便地整理邮件联系人”，再决定下一步。这里欢迎具体、可复现、脱敏的反馈。
