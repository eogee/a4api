# a4api v0.1.5

## 更新内容

### 修复与改进：dsh 统一经本地翻译代理透传
- dsh 从「直连上游」改为**统一经本地翻译代理的 `/chat/completions` 透传端点**连接上游：代理会把上游流式分片中 tool_calls 的 `null` 字段归一为省略键，规避 dsh-llm-deepseek 适配器把工具名/ID 覆盖为空导致 `unknown tool ""` 的问题（如 opencode zen 等上游以 `null` 填充后续分片）。
- dsh 配置写入时 `baseURL` 指向本地代理、凭证写入代理鉴权 token（真实上游 key 由代理持有，不落盘明文）；切换后 watcher 热加载，新会话即生效。

### 新功能：内置 OpenCodeGo 服务商模板
- 预置模板新增 **OpenCodeGo-openai**（`https://opencode.ai/zen/go/v1`，OpenAI 兼容，走本地翻译代理），与 DeepSeek / 智谱 / OpenRouter / 本地 LLM Studio 并列，开箱即用。

### 测试
- 新增回归测试：代理透传端点 tool_calls null 归一化、dsh 写入代理 baseURL 与 token、dsh 配置合并式生成，全套测试通过。

## 校验

- 安装包：`a4api-setup-0.1.5.exe`
- **SHA256：`<构建后填写>`**
- 建议下载后核对校验值，确保文件完整未被篡改。
