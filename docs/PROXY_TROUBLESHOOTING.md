# 代理问题排查指南

## 问题现象：日本代理导致图像生成失败

### 症状识别

当遇到以下**所有**特征时，极有可能是代理地区问题：

#### 1. Gemini 明确提示权限不足
```
Are you signed in? I can search for images, but can't seem to create any for you right now.
```

#### 2. 模型降级为 Flash-Lite
- 正常：使用 `Imagen 3` 进行图像生成
- 异常：降级为 `Flash-Lite`（纯文本模型）

#### 3. 认证状态正常但功能受限
```
[BrowserManager] Gemini session is authenticated (account_controls=2, recent_chats=0)
[BrowserManager] Injected 25/29 cookies
```
- ✅ Cookies 注入成功
- ✅ 账号显示已认证
- ❌ 图像生成功能不可用

#### 4. ImageInspector 捕获 0 张图像
```
[ImageInspector] 模型生成图像: ✅ 捕获到 0 张高精生成图
```

### 根因分析

**Gemini 根据 IP 地理位置判定账号权限区域**：
- 日本 IP → 该账号在日本地区可能未开通图像生成功能
- 美国 IP → 账号可正常使用 Imagen 3

这与 Cookie 认证无关，是 **IP 地理指纹** + **账号区域权限**的组合限制。

### 解决方案

1. **立即切换代理到美国**
   ```bash
   # 检查当前代理地理位置
   python -c "import requests; print(requests.get('http://ip-api.com/json/?lang=zh-CN', proxies={'http':'http://127.0.0.1:7890','https':'http://127.0.0.1:7890'}).json())"
   ```

2. **重启 Gateway**
   ```bash
   # 清理旧进程
   Get-NetTCPConnection -LocalPort 4981 | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }
   
   # 启动新会话
   python gateway.py
   ```

3. **验证恢复**
   - Gemini 响应中出现图像
   - ImageInspector 捕获到 ≥1 张图像
   - 无 "can't seem to create" 提示

### 快速诊断命令

```bash
# 1. 检查代理地理位置（应返回美国）
curl -x http://127.0.0.1:7890 http://ip-api.com/json/?lang=zh-CN

# 2. 检查 Gateway 是否正在使用正确代理
grep "Starting Chromium" logs/gateway.log | tail -1

# 3. 测试图像生成
curl -X POST http://127.0.0.1:4981/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A red circle", "n": 1}'
```

### 预防措施

1. **代理配置固定化**：在 `config.yaml` 中锁定美国代理节点
2. **启动前自检**：Gateway 启动时自动检查代理地理位置
3. **监控告警**：当 ImageInspector 连续 3 次捕获 0 张图像时告警

### 相关时间线

- **2026-09-03 01:40 - 02:00**：因日本代理导致图像生成失败
- **失败尝试**：
  - 修改 DOM 选择器
  - 增加超时时间
  - 添加遮罩层移除逻辑
- **真实根因**：代理切换至日本，账号在该区域无图像生成权限
- **解决**：切换回美国代理后立即恢复正常
