# Chrome 扩展安装指南

## 方法一：自动安装（推荐）🚀

运行自动化安装脚本：

```bash
python scripts/auto_install_extension.py --profile-directory "Profile 4"
```

脚本会：
1. 自动打开 Chrome 扩展管理页面
2. 检测扩展是否已安装
3. 如未安装，显示详细步骤指引

---

## 方法二：手动安装

### 步骤1：打开扩展管理页面

在 Chrome 地址栏输入：
```
chrome://extensions/
```

### 步骤2：启用开发者模式

点击页面**右上角**的"开发者模式"开关，确保已启用（开关变蓝）。

### 步骤3：加载扩展

1. 点击左上角的 **「加载未打包的扩展程序」** 按钮
2. 在弹出的文件选择器中，导航到：
   ```
   D:\project_qin\Proxy_project\gemini-image-proxy\src\auth\chrome_extension
   ```
3. 点击「选择文件夹」

### 步骤4：验证安装

扩展列表中应该出现：
- **名称**：Gemini Cookie Refresh Bridge
- **ID**：一串随机字母（例如：`abcdefghijklmnop`）
- **状态**：已启用

---

## 常见问题

### Q: 看不到「加载未打包的扩展程序」按钮？
**A**: 请确保已启用开发者模式（步骤2）。

### Q: 提示「无法加载扩展」？
**A**: 检查是否选择了正确的文件夹（应包含 `manifest.json`）。

### Q: 每次重启 Chrome 扩展都失效？
**A**: 这是开发者模式扩展的正常行为。如需永久使用，建议将扩展打包或发布到 Chrome Web Store。

---

## 自动化检测逻辑

安装脚本会：
1. 通过 Chrome DevTools Protocol 检测扩展状态
2. 如已安装，直接跳过
3. 如未安装，显示上述手动步骤

---

## 技术细节

扩展功能：
- 监听 `gemini.google.com` 页面的 Cookie 变更
- 通过 Native Messaging 将 Cookie 传递给 Python 后端
- 支持多账号、多 Profile 管理
