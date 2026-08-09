# a4api

一个开箱即用的 **Agent LLM 服务商切换工具**，通过可视化界面读写 `~/.claude/settings.json` 与 `~/.codex/config.toml`，让 **Claude Code 与 Codex** 在不同服务商、模型、API Key 之间**一键切换**，无需手动编辑配置文件。

Claude Code 官方原生只认 Anthropic 协议，Codex 则使用 OpenAI Responses 接口，对国内用户常用的 OpenAI 兼容服务商（DeepSeek、智谱等）以及 OpenRouter 这类聚合网关支持有限。a4api 通过内置的**本地翻译代理**：把 Anthropic 请求实时翻译成 OpenAI Chat Completions 格式转发给上游，让 Claude Code 也能流畅使用任意 OpenAI 兼容 API；对原生支持 Responses 的服务商（如 DeepSeek）让 Codex **直连上游**，对仅提供 Chat Completions 的服务商（如智谱）则由代理把 Responses 翻译转发。一套配置即可同时覆盖 Claude Code 与 Codex。

核心特性：配置方案卡片化管理、切换前自动备份、API Key 采用 Windows DPAPI 加密存储、本地代理仅监听本机并以随机 token 鉴权。无论你是想快速体验各家模型，还是想统一管理团队的 API 配置，都能通过几个点击完成。

## 下载、安装与使用

### 下载安装

从 **发行版（Release）** 页面下载安装包 `a4api-setup-*.exe`：

- **下载地址**：https://github.com/eogee/a4api/releases （选择最新版本）
- **系统要求**：Windows 10/11 64 位
- 建议核对下载页提供的 SHA256 校验值，确保文件完整未被篡改

安装包采用**每用户安装（免 UAC）**：双击运行后按向导安装到当前用户目录，全程无需管理员权限。安装完成后自动创建开始菜单与桌面快捷方式，并可在「设置 → 应用」中卸载。

### 运行

1. 安装完成后，从**开始菜单**或**桌面快捷方式**启动 a4api
2. 首次安装/运行时若出现 **Windows SmartScreen 提示**，点击「更多信息 → 仍要运行」即可（应用未做商业代码签名，属正常现象，不影响功能）
3. 打开界面后选择预置服务商模板，填入 API Key 即可一键切换

### 数据与隐私

- 运行时数据（数据库、配置备份）写入 `%APPDATA%\a4api\`，日志写入 `~/.a4api/logs/`
- API Key 使用 Windows DPAPI 加密存储，与当前 Windows 用户绑定
- 切换配置前自动备份原 `~/.claude/settings.json` / `~/.codex/config.toml`（滚动保留最近 5 份）

### 常见问题

- **杀毒软件报毒**：PyInstaller 打包的程序偶被安全软件误报，请添加信任或排除；可将样本提交给对应厂商申诉误报
- **升级**：直接运行新版 `a4api-setup-*.exe` 覆盖安装即可，数据与配置（`%APPDATA%\a4api\`）会保留；升级前会自动停止后台翻译代理并清理旧文件
- **卸载**：在「设置 → 应用」中卸载；程序文件会移除，运行数据（数据库、配置备份）保留在 `%APPDATA%\a4api\`，如需彻底清除请手动删除该目录
- **反馈问题**：请附上 `~/.a4api/logs/a4api.log` 日志，便于定位

### 提交 Issue 要求

提交 Issue 前请确认以下信息，缺失可能导致问题无法定位：

1. **明确类型**：Bug 报告 / 功能建议 / 使用疑问，选择对应标签，便于分流处理
2. **环境信息（必填）**：
   - a4api 版本号（发行版页面标注的版本）
   - 目标应用：Claude Code / Codex / 其他
   - 服务商与模型：如 DeepSeek、智谱 GLM 等
3. **复现步骤**：从打开应用到出现问题的完整操作路径，越具体越好；尽量写明「做了什么 → 实际结果 → 预期结果」
4. **日志**：附上 `~/.a4api/logs/a4api.log` 的**相关片段**（不要整份粘贴，可截取报错前后内容）
5. **报错信息与截图**：界面报错文案、终端输出、异常截图一并附上
6. **隐私红线**：**切勿在 Issue 中粘贴 API Key、模型密钥等敏感信息**；如日志可能含敏感内容，请先脱敏
7. **排查先行**：提交前先自查——重启应用、确认 API Key 有效、确认本机能访问上游服务、确认无代理/杀软干扰

> 提交前请先搜索是否已有相同 Issue，避免重复提交。

## 功能

- 预置 6 个常用服务商模板（DeepSeek、智谱、OpenRouter、本地推理等），一键生成配置方案
- 选择服务商时支持按名称关键字实时搜索（如输入 `openrouter`、`deep` 即可快速定位）
- 支持 Anthropic 协议与 OpenAI 兼容 API（切换时自动启动本地翻译代理进程，关闭工具后仍可继续使用）
- 每个配置方案可选应用目标：Claude Code、Codex 或两者（Codex 使用 OpenAI Responses 接口写入 `~/.codex/config.toml`；原生支持 Responses 的上游如 DeepSeek 直连，其余经本地翻译代理）
- 配置方案卡片化管理：新增、编辑、删除、一键切换
- 当前生效配置醒目高亮
- 切换前自动备份原配置（滚动保留最近 5 份），原子写入防损坏
- API Key 使用 Windows DPAPI 加密存储，接口永不回显明文
- 本地翻译代理仅监听 127.0.0.1，并以随机 token 鉴权
- 切换 Claude Code 配置后可选择一键重启 Claude Code；Codex 配置写入后重启 Codex 生效
- 单实例检测，防止重复运行

### 预置服务商模板

启动时自动写入并按模板定义同步，可增删改：

| 服务商 | API 地址 | 协议 | 原生 Responses |
|--------|----------|------|----------------|
| DeepSeek-anthropic | `https://api.deepseek.com/anthropic` | Anthropic | — |
| 智谱-anthropic | `https://open.bigmodel.cn/api/anthropic` | Anthropic | — |
| DeepSeek-openai | `https://api.deepseek.com/` | OpenAI | ✅ 直连 |
| 智谱-openai | `https://open.bigmodel.cn/api/paas/v4` | OpenAI | — |
| OpenRouter-openai | `https://openrouter.ai/api/v1` | OpenAI | — |
| 本地llmstudio-openai | `http://127.0.0.1:1234/v1` | OpenAI | — |

> 模板命名遵循「服务商-协议」约定：同一服务商可能同时提供 Anthropic 与 OpenAI 兼容两套接口，因此预置两条记录（如 `DeepSeek-anthropic` / `DeepSeek-openai`）。OpenRouter 为 OpenAI 兼容聚合网关，配置方案中填入其 API Key 即可路由到 OpenRouter 上架的各家模型。
>
> **原生 Responses**：勾选后 Codex 直接连接上游 `/responses` 接口，无需本地翻译代理。DeepSeek 官方原生支持 OpenAI Responses（仅 `deepseek-v4-flash` 模型），其余 OpenAI 兼容服务商默认经本地代理转发。内置模板在升级时会按模板定义自动同步（`api_base` / 协议 / 原生 Responses），自定义服务商不受影响。

## 自动更新与安全

发布新版本到 GitHub/Gitee 后，应用会在**启动时静默检查**或点顶部「检查更新」时发现更新，经你确认后下载安装包并显示进度，下载校验通过后再次确认即可运行安装器完成升级；也可选择「忽略此版本」。

### 更新源与校验（防 MITM / 防伪造）

- **双源下载**：安装包优先从 GitHub、不可达时回退 Gitee（同一 SHA256 验证两个镜像地址）。
- **更新清单签名**：发布侧用 Ed25519 私钥签名 `latest.json`（版本、更新说明、安装包 SHA256 等字段），应用内置对应公钥验签；任何字段异常或签名不符，清单直接作废、**不弹更新提示**。URL 不入签名，因此 GitHub/Gitee 两份清单字节一致、共用同一签名，URL 指向的内容由被签名的 SHA256 绑死。
- **完整性校验**：安装包边下边算 SHA256，与签名过的清单比对通过才落盘（存于 `%APPDATA%\a4api\updates\<版本>\`）；点击「立即更新」时会对磁盘文件**再次校验**才启动安装器。
- **传输白名单**：仅 HTTPS，且每次重定向逐跳校验主机白名单（`github.com` / `gitee.com` / 两个 `*.githubusercontent.com` 对象存储域 / `*.gitee.com`），拦截跳转到任意域名。
- **防降级**：候选版本需严格高于当前版本；低于清单 `min_version`（过旧需完整安装包）时拒绝；预发布版本仅当当前运行版本也是预发布时才提示。
- **尺寸上限**：清单 512KB、安装包 300MB，超限拒绝；下载只写入用户数据目录，不信任系统临时目录。

### 更新流程（一次点击走完）

1. 检测到新版本 → 弹窗展示版本号与更新说明（说明内容由签名清单携带，篡改即拒收）。
2. 确认 → 后台下载，前端实时进度；下载中可取消。
3. 校验通过 → 提示「立即更新 / 稍后」。点击立即更新：应用先停掉本地翻译代理、自动退出并释放单实例锁，随后拉起 Inno Setup 安装向导；安装完成后启动的是新版本，配置、数据库与密钥完整保留。

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
- 写入采用**合并式更新**：只覆盖工具托管的字段（`env` 中的 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL`、`model`、`alwaysThinkingEnabled`），`hooks`、`permissions`、`mcpServers` 及其他 `env` 变量原样保留，不破坏用户已有的 hook、授权与配置。

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
- `test_updater.py`：签名载荷 golden 基准（防跨实现回归）、验签/篡改拒绝、版本比较与降级、SHA256/尺寸校验、忽略逻辑、URL 白名单、清单字段校验、GitHub→Gitee 回退与 TTL 缓存、本地服务器下载/取消/镜像回退、状态原子读写。

## 开发

环境要求：Windows 10+，Python 3.10，[uv](https://docs.astral.sh/uv/)

```bash
uv sync                     # 安装依赖
uv run python desktop.py    # 启动桌面应用
# 或后端单独调试
uv run uvicorn backend.app.main:app --port 8000
```

## 打包

前置：编译安装包需要 [Inno Setup 6](https://jrsoftware.org/isinfo.php)（`winget install --id JRSoftware.InnoSetup -e --accept-source-agreements`）。

```bash
uv run python build.py                 # 生成 dist/a4api/（文件夹版 onedir）
uv run python build.py --installer     # 文件夹版 + 编译安装包 dist/a4api-setup-<版本>.exe
uv run python build.py --onefile       # 可选：生成单 exe（临时分发用）
```

版本号自动取自 `pyproject.toml`（`[project].version`），也可用 `--version` 覆盖；ISCC.exe 自动探测（`--iscc` 指定路径）。

## 项目结构

```
backend/app/       FastAPI 后端（模型、CRUD、配置读写、加密、进程管理）
frontend/          LayUI 前端
desktop.py         pywebview 桌面入口
build.py           打包脚本
```

运行时数据（数据库、配置备份）写入 `backend/database/`（开发）或 `%APPDATA%\a4api\`（打包后）。
