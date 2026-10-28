# 首次设为 Public 前的人工确认清单

- [ ] 这是**新建的** `bobbanga/ehelp-contacts-skill` 仓，不要把 `ehelp-mail`、`mail-assistant`、`Ehelpcn` 或 `jctrans-cli` 原仓直接设为 Public。
- [ ] 确认本人对 `skill/ehelp-mail/` 的代码拥有公开发布权，包含第三方代码时检查许可证。
- [ ] 确认采用 MIT License，并检查 LICENSE 版权署名；如不同意，不要原样公开本准备包。
- [ ] 不导入私有 Git 历史；新仓从单个干净的初始提交开始。
- [ ] 发布前跑 `python scripts/validate_public_package.py` 并手工搜索账号、密码、私有域名、工作电脑绝对路径、客户信息、内部文档。
- [ ] 检查仓库根目录、git 暂存区与构建文件：不含 `*.sqlite3`、`*.db`、`.env`、真实邮件、Excel、HTML、日志、备份。
- [ ] 在仓库 Settings 中启用 Issues；启用 Secret scanning、Push protection、Dependabot、Private vulnerability reporting（可用时）。
- [ ] 把仓库默认分支设为 main，创建 v0.2.6 Release，附上从本仓构建的 WorkBuddy ZIP。
- [ ] 公开 README 对照 WorkBuddy 当前版本；更新前不要宣称 WorkBuddy 平台已自动升级。
- [ ] 初始 10-20 名测试用户只收集匿名化的功能成功与失败，不索取联系人数据。
- [ ] 分享链接由开发者提供；GitHub 仓库创建后检查 README 的相对 Issues 链接、实际 WorkBuddy 分享链接是否有效。
