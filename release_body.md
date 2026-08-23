# a4api v0.2.1

## 更新内容

### 修复：dsh 目标切换后 `.credentials.yaml` 被写坏、dsh 无法启动
- 切换含 dsh 目标的配置时，`DEEPSEEK_API_KEY` 曾被写到凭证文档**顶层**，而 dsh 要求 version-1 布局（顶层仅允许 `version` / `refs` / `records`），导致 dsh 启动即报 `unknown top-level key "DEEPSEEK_API_KEY"` 拒绝引导。
- 现在固定输出 `{"version": 1, "refs": {...}}` 布局：`DEEPSEEK_API_KEY` 写入 `refs` 下；输入若为旧版扁平文档（凭证散在顶层）自动并入 `refs` 迁移；`records` 段（如 OAuth 记录）原样保留。

### 修复：切换后 dsh 请求被上游以 max_tokens 超限打回（400 [1210]）
- 未显式填写 max_tokens 时，文件里遗留的 dsh 适配器默认值 **256000** 曾被当作"手动设置"一路带到新上游；实测 Console Go 等上游仅接受 `[1, 131072]`，超限直接 400。
- 现在既有 maxTokens 恰为适配器默认 256000 时视为历史遗留，回落安全默认 **131072**；用户显式填写的值仍然最优先。

### 测试
- 新增/更新回归用例（凭证 version-1 布局与旧扁平迁移、records 保留、遗留 256000 重置），后端测试套件 117 个全部通过。

## 校验

- 安装包：`a4api-setup-0.2.1.exe`
- **SHA256：`69CC25AD3F8A143E35673867268A5960054CBF19D2C999F8FB518515C3BF5429`**
- 建议下载后核对校验值，确保文件完整未被篡改。
