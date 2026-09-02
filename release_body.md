# a4api v0.2.2

## 更新内容

### 新增：ZCode（智谱 Agentic 开发环境）全量适配，四端统一管理
- **API 切换**：新增 `zcode` 目标。ZCode 原生支持 Anthropic / OpenAI 两种协议，切换时直连写入 CLI（`~/.zcode/cli/config.json`）与桌面端（`~/.zcode/v2/config.json`）两份配置，无需本地翻译代理、不受服务商协议限制；provider 条目以 `a4api_p<id>` 托管、切换时整体替换旧条目并保留用户手工添加的 provider，hooks 等其它键原样保留。
- **技能管理**：三端 → 四端，纳入 ZCode（全局 `~/.zcode/skills` / 项目级 `<项目>/.zcode/skills`），发现、聚合标注、跨端迁移、「一键适配四端」补齐、回收站全链路支持。
- **MCP 管理**：新增 zcode 端（`~/.zcode/cli/config.json` / 项目 `.zcode/config.json` 的 `mcp.servers`，支持 stdio / sse / http），传输能力矩阵、快照回收站与脱敏机制全覆盖。

### 新增：MCP 四端管理模块
- 自动发现 Claude Code、Codex、dsh、ZCode 的全局与项目级 MCP server 并聚合标注；跨端迁移按**传输能力矩阵**严格校验（claude/zcode 支持 stdio/sse/http，codex 仅 stdio，dsh 支持 stdio/streamable-http 且无项目级），不兼容组合整对失败并留日志、不静默降级。
- 目标端同名 server 先快照进回收站再写入；快照中的 `env` / `headers` 用 DPAPI 加密落盘、恢复时解密；发现与预览接口对敏感字段一律脱敏，API 永不回传明文。
- ZCode 端 schema 严格（未知键会被丢弃），写入只输出其规范字段（`type`/`command`/`args`/`cwd`/`env`/`url`/`headers`/`enabled`/`timeoutMs`）。

### 修复：MCP 迁移同配置多 server 去重误跳过
- 同一配置文件内多个 server 迁移到同一目标时，旧去重键只含文件路径不含 server 名，第二个 server 会被误跳过；现按「server 名 + 源路径 + 目标」去重，整批迁移正确完成。

### 文档
- README 重构：叙事重心转为「四端技能 / MCP 管理中枢」，技能管理与 MCP 管理各成章节（含四端目录位置表与传输能力矩阵），API 切换弱化为独立简章节；开发文档与技能手动测试文档同步更新至四端。

### 测试
- 新增/更新 zcode 与 MCP 四端用例（切换双配置写入、协议自由、托管条目替换、技能存取、MCP 发现/迁移/传输矩阵/schema），后端测试套件 141 个全部通过。

## 校验

- 安装包：`a4api-setup-0.2.2.exe`
- **SHA256：`A3C6BD2F5D1F08D97840558D7D7CB2B96CF1A9E7BFA47F4DF4CA1C75907C24D5`**
- 建议下载后核对校验值，确保文件完整未被篡改。