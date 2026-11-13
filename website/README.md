# Instap 静态官网

构建：`npm run build:website`。这会先打包扩展，核对 ZIP 内 manifest、版本和每个文件字节，再生成 `dist/`。只有 `extension/` 资源进入扩展 ZIP；网站资源与扩展包分别处理。没有安装依赖或外部运行时资源。

本地预览：`npm run preview:website`，访问 `http://127.0.0.1:4173/`。完整路径需要通过 HTTP 预览，不要直接双击 HTML。部署只需发布 `dist/` 内容，并让 Web 服务按目录提供 index.html。

- `template.html` 提供公共页头、页脚和资源引用。
- `home.html` 和 `product.html` 分别是公司首页及产品页正文。
- `content/install.html` 是安装页正文片段；安装教程配有 2026-11-12 与 2026-11-13 拍摄的 macOS Chrome/Finder 部分步骤截图，并提供原图链接。Windows 安装截图仍待实测补充；截图不代表完整安装流程已验收。
- 隐私政策正文直接来自根目录 `PRIVACY.md`，构建器仅渲染其中使用的标题、段落、列表、链接、粗体和行内代码；另附官网日志说明。
- 版本、包大小、SHA-256 与 UTC 构建日期由构建器计算，输出在 `dist/release.json` 与 `dist/downloads/bili-ninja/release.json`。`released` 指官网包构建日，页面不将其称作扩展首次发布日期。
- ZIP 路径为 `/downloads/bili-ninja/bili-ninja-<version>.zip`。扩展资源变化时应增加 manifest/package 版本，避免复用版本 URL。打包器固定文件排序、时间和权限，使相同输入的构建可重复。
- `site.js` 只负责复制地址、移动设备提示与允许的 UTM 链接传递；不存储来源，不上报事件。来源只接受五个标准 utm 键，值为 1–80 个 ASCII 字母、数字或 `._~-`。下载链接显式携带这些参数；没有 JS 时仍可直接下载，但不会传递来源。
- 产品示例封面位于 `website/assets/examples/`，程序生成的测试媒体演示来自仓库 `store/assets/`；安装实测截图位于 `website/assets/install/`。页面标注测试媒体演示，不暗示创作者背书。Chrome Web Store 未取得真实条目地址，显示禁用的待上线状态。

不通过 Sites 托管；生产部署与回退由仓库部署流程管理。
