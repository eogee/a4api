# a4api

帮助用户快速切换 Claude Code 使用的不同 LLM 服务商 API。
通过可视化界面读写 `~/.claude/settings.json`，一键切换服务商、模型、API Key。

## 功能

- 预置 DeepSeek、智谱、火山方舟服务商模板，一键生成配置方案
- 支持 Anthropic 协议与 OpenAI 兼容 API（切换时自动启动本地翻译代理进程，关闭工具后仍可继续使用）
- 配置方案卡片化管理：新增、编辑、删除、一键切换
- 当前生效配置醒目高亮
- 切换前自动备份原配置（滚动保留最近 5 份），原子写入防损坏
- API Key 使用 Windows DPAPI 加密存储
- 切换后可选一键重启 Claude Code
- 单实例检测，防止重复运行

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
