# Figma 设计对接说明（解决 400 无法获取设计数据）

## 为什么当前链接会返回 400？

你提供的链接是 **Figma Make** 项目：

- 格式：`https://www.figma.com/make/aYSADFEVR3d6CF6ip4JrKd/...`
- **Figma 官方 REST API 只支持「Design」文件，不支持「Make」项目**。  
  用 Make 的 file key 去调 `GET /v1/files/:key` 会返回 **400 Bad Request**，这是预期行为，不是配置错误。

参考：[Figma API 文件端点](https://developers.figma.com/docs/rest-api/file-endpoints/)；[Figma Make 与 API 限制讨论](https://github.com/GLips/Figma-Context-MCP/issues/255)。

---

## 解决方案（任选其一即可用于 UI 整改）

### 方案 A：改用 Figma Design 文件链接（推荐，可自动拉设计）

若同一份 UI 在 **Figma Design** 里也有一份（或你愿意在 Design 里做一版）：

1. 在 Figma 里打开的是 **Design** 文件（URL 形如 `figma.com/design/...` 或 `figma.com/file/...`）。
2. 从浏览器地址栏复制链接，例如：  
   `https://www.figma.com/design/XXXXXXXXXX/你的文件名`
3. 把链接里的 **file key**（即 `XXXXXXXXXX` 这一段）发给我，或保存到项目里。  
   我可以用 Figma API 拉取该文件的节点、样式、尺寸等，直接按设计生成/整改 React + Tailwind 组件。

这样就不存在 400 问题，且能按设计稿精确落地。

---

### 方案 B：从 Figma Make 导出设计/代码，再交给我落地

如果必须用当前 **Figma Make** 项目、且暂时没有 Design 文件：

1. **复制到 Design（便于后续用 API）**  
   - 在 Make 的预览里，切到要整改的界面。  
   - 使用 **「Copy design」** 把当前视图的图层复制到剪贴板。  
   - 在 **Figma Design** 里新建文件并粘贴。  
   - 保存后，用 Design 的链接（`figma.com/design/...`）按 **方案 A** 对接。

2. **用 Make 的「Code」导出**  
   - 在 Figma Make 里打开你的项目，找到 **Code** 相关入口。  
   - 导出或复制生成的 HTML/CSS/React 代码。  
   - 把导出的代码（或关键片段）发给我，我可以据此改写成与当前项目一致的 React + Tailwind 组件。

3. **截图 + 标注**  
   - 对要整改的页面做截图，并标注：  
     布局（栅格/间距）、字号、颜色、圆角、关键组件层级。  
   - 把截图和标注发给我，我按说明做 UI 整改。

---

## 小结

| 来源 | 能否用 Figma API 拉数据 | 建议做法 |
|------|-------------------------|----------|
| **Figma Design** 链接 | ✅ 可以 | 用 Design 的 file key，我按 API 数据生成/整改组件 |
| **Figma Make** 链接 | ❌ 会 400 | 用方案 B：复制到 Design / 导出 Code / 截图标注 |

你只要提供 **Design 文件链接**，或 **Make 导出的代码/截图+标注**，我就可以按你的设计做 UI 整改，并保持 Tailwind + 现有项目结构一致。
