# Gemini Image Gateway

基于 Playwright 和 Gemini Web 的个人/团队内部图像生成网关。它提供 OpenAI
兼容的 Images API，同时保留原有 Python SDK 和 CLI。

这是受控内部服务，不是公共多租户 SaaS。Gemini Web 页面和 DOM 并非稳定 API，
部署方需要自行维护有效 Cookie、网络代理和页面适配器。

---

## 核心能力

- **OpenAI 兼容图片接口**：支持 `/v1/images/generations` 和 `/v1/images/edits`。
- **受控访问**：默认仅监听 `127.0.0.1`，远程绑定强制要求长 Token。
- **单会话串行队列**：所有请求按顺序操作同一个 Gemini 页面，避免并发串图。
- **请求级图片归属**：通过发送前基线和最新模型回复识别本次生成结果。
- **结构化错误和状态**：区分鉴权失败、浏览器不可用、上传失败和生成超时。
- **可插拔调试探针**：
  - `SessionTrackerPlugin`：自动抓取 Google 后端给予当前对话的真实 16 位 UUID (`chat_id`)，打印会话一致性报告。
  - `ImageInspectorPlugin`：发送前确认参考图挂载，发送后诊断最新回复中的生成图。
- **历史对话管理与定向追加**：
  - 支持 `--list-chats` 自动扫描解析侧边栏 Recents 中的所有历史 Chat ID 与标题。
  - 支持 `--chat-id <ID>` 强行切入指定的历史 Chat 记录中追加发送 Prompt 生图。
- **图生图上传**：通过 `DataTransfer ClipboardEvent` 和文件输入双路径提交参考图。

---

## 📁 目录架构

```text
gemini-image-proxy/
├── config.yaml               # 主配置文件 (代理、超时、尺寸过滤、默认路径)
├── .env                      # 密钥配置 (存储 raw Cookie 字符串)
├── main.py                   # 统一 CLI 命令行入口
├── gateway.py                # FastAPI 内部网关入口
├── src/
│   ├── api/                  # OpenAI Images API 与鉴权
│   ├── config/               # Settings 配置解析器
│   ├── core/
│   │   ├── browser.py        # Playwright Chromium 浏览器生命周期管理与 Cookie 注入
│   │   ├── extractor.py      # DOM 元素提取器、安全打字、DataTransfer 剪贴板原图注入
│   │   ├── gemini_session.py # 单浏览器 Gemini Web 适配器
│   │   ├── errors.py         # 领域错误
│   │   └── models.py         # 结构化图片与生成结果
│   ├── service/              # 队列、状态和生命周期
│   ├── plugins/              # 可插拔调试探针插件
│   │   ├── session_tracker.py # 真实 Chat ID 追查探针
│   │   └── image_inspector.py # 发送前防护门 Guard & 发送后图像诊断 Inspector
│   ├── storage/              # 高清大图落盘下载器
│   └── utils/                # 工具函数
│       ├── logger.py         # UTF-8 日志打印器
│       ├── cookie_parser.py  # Cookie 解析器
│       ├── batch_generation.py # 批量生成通用逻辑
│       └── transparency.py   # 自动抠图透明背景处理
├── scripts/
│   ├── check_env.py               # 依赖与环境诊断脚本
│   ├── update_cookies.py          # Cookie 一键交互式更新工具
│   ├── check_gemini_login.py      # 登录状态检测（DOM 判定 + 截图）
│   ├── check_gateway_health.py    # 网关健康检查工具
│   └── test_cookie_refresh_flow.py # Cookie 刷新流程完整测试
└── examples/                      # 使用示例
    ├── tasks_sample.json          # 批处理 JSON 配置文件
    ├── batch_generate.py          # 批处理 Python SDK 示例
    └── image_to_image_demo.py     # 【图生图】Python SDK 示例
```

---

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
playwright install chromium
```

Chrome 137 及以上不再允许正式版 Chrome 通过命令行临时加载扩展，因此 Cookie 更新器使用固定目录的本地扩展。扩展只在本机更新器运行时连接 `127.0.0.1:4982`，并且只在 Gemini 页面确认登录后返回 Google Cookie；它不会直接解密 Chrome 数据库。

### 2. 配置环境 `.env`
复制 `.env.example` 为 `.env`，填入 Gemini Cookie。

**推荐使用自动更新工具**：

```env
GEMINI_RAW_COOKIES="SID=...; __Secure-1PSID=...; ..."
GATEWAY_BIND_HOST="127.0.0.1"
GATEWAY_PORT="4981"
GATEWAY_API_TOKEN="your-private-token"
```

不要提交 `.env`，也不要把 Gemini Cookie 放到客户端、URL 或日志中。

**Cookie 失效时自动刷新**（耗时约 30 秒）：

```bash
python scripts/update_cookies.py
```

**检测当前登录状态**：

```bash
python scripts/check_gemini_login.py
# 返回 LOGIN_STATUS=AUTHENTICATED 或 FAILED
# 截图保存至 output/playwright/login-*.png
```

首次使用某个 Chrome 用户时，需要在该 Profile 中安装一次本地扩展：

```bash
python scripts/update_cookies.py --setup-extension
```

该命令会先列出本机 Chrome Profile，选择后为该 Profile 打开 `chrome://extensions` 和扩展目录。打开“开发者模式”，点击“加载未打包的扩展程序”，选择脚本显示的 `src/auth/chrome_extension` 目录。需要刷新哪个 Chrome 用户，就在那个 Profile 中安装一次；扩展未安装时更新器会给出明确诊断，不会写入 `.env`。

刷新命令会先在 CLI 中列出资料序号、实际名称、邮箱、Profile 目录和扩展安装状态。选定后再关闭已有的系统 Chrome；更新器会使用该明确 Profile 启动一个不可见的无头 Chrome 并进入 Gemini，不会依赖“最后打开的用户”。只有在 Gemini 编辑器确认已登录后，才会捕获 Cookie 并原子更新 `.env` 的 `GEMINI_RAW_COOKIES`，随后只关闭本次启动的无头 Chrome。日志不会输出 Cookie 值。

常用参数：

```bash
python scripts/update_cookies.py --timeout 600
python scripts/update_cookies.py --user-data-dir "C:\\Users\\Administrator\\AppData\\Local\\Google\\Chrome\\User Data"
python scripts/update_cookies.py --close-wait 300
python scripts/update_cookies.py --profile-directory "Profile 4"
python scripts/update_cookies.py --visible
python scripts/update_cookies.py --setup-extension --profile-directory "Profile 4"
```

### 3. 启动内部网关

```bash
python gateway.py
```

本机地址：

```text
API:    http://127.0.0.1:4981/v1
Docs:   http://127.0.0.1:4981/docs
Health: http://127.0.0.1:4981/healthz
Ready:  http://127.0.0.1:4981/readyz
```

`healthz` 只表示服务进程存活；`readyz` 返回 200 才表示 Playwright 和 Gemini
会话可用。

**检查网关健康状态**：

```bash
python scripts/check_gateway_health.py
# 检测 /healthz、/readyz 和 /v1/status
```

## OpenAI 兼容 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/healthz` | 进程健康检查 |
| `GET` | `/readyz` | Gemini 会话就绪检查 |
| `GET` | `/v1/status` | 受保护的队列和失败状态 |
| `GET` | `/v1/models` | 当前图片模型别名 |
| `POST` | `/v1/images/generations` | 文生图 |
| `POST` | `/v1/images/edits` | multipart 图生图 |

文生图示例：

```bash
curl http://127.0.0.1:4981/v1/images/generations \
  -H "Authorization: Bearer your-private-token" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-web-image","prompt":"A neon trophy sticker","n":1,"response_format":"b64_json"}'
```

当前兼容边界：

- 只支持 `n=1`。
- 只返回 `b64_json`，不公开本地输出路径。
- `size` 只接受 `auto` 或 `1024x1024`，作为兼容提示，底层网页不保证精确尺寸。
- 不支持 `quality` 和 `style` 选择。
- 不提供伪造的 `/v1/chat/completions` 图片行为。
- 页面明确拒绝生图（例如账户、地区或模型能力不可用）时，返回 HTTP `422` 和
  `generation_rejected`；只有页面没有结果也没有明确拒绝信号时才返回
  `generation_timeout`。

PowerShell 请使用 `Invoke-RestMethod`，或把 `curl.exe` 命令写在同一行；反斜杠
`\` 是 Bash 的续行符，在 PowerShell 中会把后续 `-H`、`-d` 当成独立命令。

图生图使用 multipart：

```bash
curl http://127.0.0.1:4981/v1/images/edits \
  -H "Authorization: Bearer your-private-token" \
  -F "model=gemini-web-image" \
  -F "prompt=Turn this into a neon sticker" \
  -F "image=@reference.png"
```

上传只接受 PNG、JPEG 和 WebP，并检查声明类型、真实文件签名和大小上限。

## 团队远程访问

优先通过 Tailscale 或 WireGuard 暴露服务，不建议直接做公网端口转发。

```env
GATEWAY_BIND_HOST="0.0.0.0"
GATEWAY_API_TOKEN="use-a-random-token-with-at-least-32-characters"
GATEWAY_CORS_ORIGINS="https://your-internal-client.example"
```

当绑定地址不是回环地址时，Token 少于 32 个字符会直接拒绝启动。公网场景还需要
HTTPS 反向代理、IP 限制、请求体限制和至少 120 秒的上游读取超时。

## 测试

```bash
pip install -r requirements-dev.txt
pytest -q
```

核心测试覆盖：
- ✅ 登录证据检测逻辑（`tests/test_login_evidence.py`）
- ✅ 队列和合同测试（不访问真实 Gemini）
- ✅ Cookie 刷新完整流程（`scripts/test_cookie_refresh_flow.py`）

合同和队列测试不会访问 Gemini，也不会触发生图。

---

## CLI 命令

### 1. 查看侧边栏所有历史 Chat ID 列表
```bash
python main.py --list-chats
```

### 2. 常规单 Prompt 生图
```bash
python main.py -p "Vox style sticker cutout of a golden trophy" -o "golden_trophy"
```

### 3. 切入特定 Chat ID 追加生图
```bash
python main.py -p "Generate another variation" --chat-id "7e456d5f36505b8c"
```

### 4. 【真·图生图】传入参考原图
```bash
python main.py -i "output/vox_trophy_1.png" -p "Transform this into a cyberpunk neon sticker" -o "neon_trophy"
```

### 5. 批处理模式 (JSON/JSONL 批量生图)
```bash
python main.py -f examples/tasks_sample.json --keep-chat
python main.py -f examples/batch_tasks.jsonl --keep-chat
```

### 6. 带透明背景的批量生成
```bash
# 使用 batch_generation.py 工具自动抠图
python -c "from src.utils.batch_generation import batch_generate; import asyncio; asyncio.run(batch_generate('examples/batch_tasks.jsonl', remove_bg=True))"
```

---

## Python SDK

```python
import asyncio
from src import GeminiSession, Settings

async def main():
    settings = Settings.load_from_files()
    
    async with GeminiSession(settings) as session:
        # 1. 检索历史 Chat ID
        chats = await session.list_chats()
        
        # 2. 图生图与防护门双校验
        paths = await session.generate_image(
            prompt="Transform this trophy into a glowing neon sticker",
            input_image="output/vox_trophy_1.png",
            output_name="neon_trophy"
        )
        print("图片落地保存结果:", paths)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 📜 许可证

MIT License © 2026 Gemini Crawl Project
