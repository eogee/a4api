# a4agent v0.4.0

## 品牌

### a4api 正式更名为 a4agent

- 产品更名为 **a4agent**（A for Agent）：安装包、可执行文件、开始菜单/桌面快捷方式、界面标题与页脚全部启用新名称
- **数据自动迁移**：首次启动新版时，旧 `%APPDATA%\a4api\` 数据目录（配置方案、供应商、备份、本地模型设置）整体迁入 `%APPDATA%\a4agent\`，无需任何手工操作；极端情况下目录被占用时自动退化为逐项拷贝，数据不丢
- **外部配置无缝接管**：切换服务商时写入 Claude Code / Codex / dsh / zcode 配置的托管条目前缀由 `a4api_p<id>` 统一升级为 `a4a_p<id>`，切换时自动清理旧前缀条目，不留孤儿配置
- **老版本更新链路不受影响**：v0.3.x 的「检查更新」仍可正常发现并升级到本版本（本次 Release 同时提供 `a4agent-setup-*.exe` 与兼容旧版的 `a4api-setup-*.exe` 两种文件名）
- 托管仓库同步更名为 `eogee/a4agent`（Gitee / GitHub / GitCode），旧地址自动重定向
- 日志目录迁至 `~/.a4agent/logs/a4agent.log`（旧目录保留不删，应用内反馈在无新日志时仍可附带旧日志）

## 改进

- 环境变量前缀 `A4API_*` → `A4AGENT_*`，旧变量名仍可识别（脚本/CI 平滑过渡）
- 更新器支持按新旧两种安装包名匹配清单资产

## 校验

- 安装包：`a4agent-setup-0.4.0.exe`（20,748,981 字节）
- SHA256：`C2A7C26FCC713132EBFACF90DC3DF1E8073C9BF823B9870DAF32ABED4A3DA8A0`
- 兼容资产：`a4api-setup-0.4.0.exe`（与上者字节一致，供 v0.3.x 老版本自动更新）
