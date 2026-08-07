# a4api

一个开箱即用的 **Agent LLM 服务商切换工具**，通过可视化界面读写 `~/.claude/settings.json` 与 `~/.codex/config.toml`，让 **Claude Code 与 Codex** 在不同服务商、模型、API Key 之间**一键切换**，无需手动编辑配置文件。

Claude Code 官方原生只认 Anthropic 协议，Codex 则使用 OpenAI Responses 接口，对国内用户常用的 OpenAI 兼容服务商（DeepSeek、智谱、火山方舟等）支持有限。a4api 通过内置的**本地翻译代理**：把 Anthropic 请求实时翻译成 OpenAI Chat Completions 格式转发给上游，让 Claude Code 也能流畅使用任意 OpenAI 兼容 API；对原生支持 Responses 的服务商（如 DeepSeek）让 Codex **直连上游**，对仅提供 Chat Completions 的服务商（如智谱）则由代理把 Responses 翻译转发。一套配置即可同时覆盖 Claude Code 与 Codex。

核心特性：配置方案卡片化管理、切换前自动备份、API Key 采用 Windows DPAPI 加密存储、本地代理仅监听本机并以随机 token 鉴权。无论你是想快速体验各家模型，还是想统一管理团队的 API 配置，都能通过几个点击完成。

## 下载与使用

### 下载

从 Gitee **发行版（Release）** 页面下载 `a4api.exe`：

- **下载地址**：https://gitee.com/eogee/a4api/releases （选择最新版本）
- **系统要求**：Windows 10/11 64 位，**无需安装 Python**，单文件即点即用
- 建议核对下载页提供的 SHA256 校验值，确保文件完整未被篡改

### 运行

1. 下载 `a4api.exe` 后双击运行
2. 首次运行若出现 **Windows SmartScreen 提示**，点击「更多信息 → 仍要运行」即可（应用未做商业代码签名，属正常现象，不影响功能）
3. 打开界面后选择预置服务商模板，填入 API Key 即可一键切换

### 数据与隐私

- 运行时数据（数据库、配置备份）写入 `%APPDATA%\a4api\`，日志写入 `~/.a4api/logs/`
- API Key 使用 Windows DPAPI 加密存储，与当前 Windows 用户绑定
- 切换配置前自动备份原 `~/.claude/settings.json` / `~/.codex/config.toml`（滚动保留最近 5 份）

### 常见问题

- **杀毒软件报毒**：PyInstaller 打包的 exe 偶被安全软件误报，请添加信任或排除；可将样本提交给对应厂商申诉误报
- **升级**：直接下载新版替换旧文件即可，数据与配置会保留
- **反馈问题**：请附上 `~/.a4api/logs/a4api.log` 日志，便于定位

## 功能

- 预置 6 个常用服务商模板（DeepSeek、智谱、火山方舟、本地推理等），一键生成配置方案
- 支持 Anthropic 协议与 OpenAI 兼容 API（切换时自动启动本地翻译代理进程，关闭工具后仍可继续使用）
- 每个配置方案可选应用目标：Claude Code、Codex 或两者（Codex 使用 OpenAI Responses 接口写入 `~/.codex/config.toml`）
- 配置方案卡片化管理：新增、编辑、删除、一键切换
- 当前生效配置醒目高亮
- 切换前自动备份原配置（滚动保留最近 5 份），原子写入防损坏
- API Key 使用 Windows DPAPI 加密存储，接口永不回显明文
- 本地翻译代理仅监听 127.0.0.1，并以随机 token 鉴权
- 切换 Claude Code 配置后可选择一键重启 Claude Code；Codex 配置写入后重启 Codex 生效
- 单实例检测，防止重复运行

### 预置服务商模板

首次启动自动写入，可增删改：

| 服务商 | API 地址 | 协议 |
|--------|----------|------|
| DeepSeek | `https://api.deepseek.com/anthropic` | Anthropic |
| 智谱 | `https://open.bigmodel.cn/api/anthropic` | Anthropic |
| 火山方舟 | `https://ark.cn-beijing.volces.com/api/coding` | Anthropic |
| 智谱 OpenAI 兼容接口 | `https://open.bigmodel.cn/api/paas/v4` | OpenAI |
| 本地 LLM Studio 接口 | `http://127.0.0.1:1234/v1` | OpenAI |
| DeepSeek（OpenAI 兼容） | `https://api.deepseek.com/` | OpenAI |

## 安全设计

### 1. API Key 加密存储

- 所有 API Key 在入库前经 **Windows DPAPI**（直接调用 `crypt32.dll` 的 `CryptProtectData`，无第三方依赖）加密，密文以 base64 存入 SQLite，与当前 Windows 用户绑定，换用户/换机器后无法解密。
- 任何 API 响应都不包含 API Key 明文或密文（响应模型 `ConfigOut` 不暴露密钥字段），密钥仅在「切换」时解密并写入目标配置文件，或传入本地代理。
- 非 Windows 环境仅做 base64 编码兜底，**不具备安全性**，仅供开发调试。
- 解密失败时返回空字符串并记录错误日志，不静默产出脏数据。

### 2. 本地翻译代理鉴权（防未授权调用）

为 OpenAI 兼容服务商启动的本地翻译代理：

- **仅绑定 `127.0.0.1`**，不对外网开放；端口限定在 `17890–17899` 的固定小范围。
- 每次启动由 `secrets.token_urlsafe(24)` 生成**随机鉴权 token**，请求必须携带 `x-api-key` 或 `Authorization: Bearer <token>` 且与 token 一致，否则返回 `401`。
- 代理只在配置为「OpenAI 兼容 + 目标含 Claude/Codex」时才运行，从数据库中按当前生效配置解密密钥来更新上游，**不硬编码任何密钥**；当生效配置不再需要代理时自动退出。
- 复用已运行代理前会校验其能力版本（`/v1/api/version`，要求 ≥ 2 且支持 `openai_responses`），避免误用旧构建的未鉴权进程；端口状态文件过期时按端口反查占用进程并清理。

### 3. 配置写入与备份

- 修改 `~/.claude/settings.json`、`~/.codex/config.toml` 前**自动备份**，滚动保留最近 5 份，切换失败可随时回滚。
- 所有写入均采用**原子写**：先写临时文件并 `fsync`，再 `os.replace` 覆盖目标，避免写入中途崩溃导致配置文件损坏。
- 写入只更新目标字段（env / model 等），其余配置原样保留，不破坏用户已有设置。

### 4. 后端 API 防护

- CORS 白名单仅放行 `localhost` / `127.0.0.1` / `[::1]`，阻止任意网站读取或篡改本地配置。
- 请求体经 Pydantic 校验（如 `api_type` 仅允许 `anthropic`/`openai`），非法输入直接拒绝。
- 前端静态资源由后端统一托管，桌面应用形态下服务仅暴露给本机。

### 5. 数据目录与文件权限

- 打包后运行时数据（数据库、配置备份）写入 `%APPDATA%\a4api\`，落在当前用户目录下。
- 非 Windows 环境对数据目录与数据库文件执行 `700` / `600` 权限收紧（尽力而为的加固，Windows 上由 NTFS ACL 控制）。
- `.gitignore` 已排除数据库与运行时数据，避免密钥密文随仓库泄露。

### 6. 并发与数据一致性

- 配置激活操作使用**进程内互斥锁**串行化，避免并发请求把多个配置同时标为 active；异常时事务回滚，不留半写入状态。
- SQLite 连接开启**外键约束**（`PRAGMA foreign_keys=ON`），删除服务商前校验其下配置方案，杜绝孤儿数据。

### 7. 进程与单实例

- 使用 Windows 命名互斥体保证桌面应用**单实例**运行，防止多实例互相覆盖配置。
- 重启 Claude Code 前通过 CIM 精确匹配命令行含 `claude` 的进程，避免误杀无关进程。

### 8. 日志与隐私

- 默认日志**不记录任何请求/响应内容**，只记录时间、级别与摘要信息，日志文件写入 `~/.a4api/logs/`。
- 代理调试日志（含完整请求头、请求体、上游响应）默认关闭，仅当显式设置 `A4API_PROXY_DEBUG` 环境变量时才开启，便于排查问题而不泄露对话内容。

### 9. 自动化测试

- `test_crypto.py`：DPAPI 加解密往返、非法密文返回空。
- `test_config_manager.py`：原子写入不留临时文件残留。
- `test_openai_proxy.py`：Anthropic ⇄ OpenAI 协议翻译正确性，含工具 schema 处理回归用例。

## 开发

环境要求：Windows 10+，Python 3.10，[uv](https://docs.astral.sh/uv/)

```bash
uv sync                     # 安装依赖
uv run python desktop.py    # 启动桌面应用
# 或后端单独调试
uv run uvicorn backend.app.main:app --port 8000
```

## 打包

```bash
uv run python build.py  # 生成 dist/a4api.exe（单 exe）
```

## 项目结构

```
backend/app/       FastAPI 后端（模型、CRUD、配置读写、加密、进程管理）
frontend/          LayUI 前端
desktop.py         pywebview 桌面入口
build.py           打包脚本
```

运行时数据（数据库、配置备份）写入 `backend/database/`（开发）或 `%APPDATA%\a4api\`（打包后）。
