# Bili Ninja

极简 Chrome 插件：从 Bilibili BV 视频页导出带声音的完整 `.mp4` 视频，或提取原始 AAC 音轨，将所选分 P 按原顺序无损合并成一个 `.m4a` 文件。

纯 JavaScript、零运行时依赖、无需构建、无需安装 FFmpeg，无服务端。支持音频/视频切换、清晰度选择、进度、取消和本机预览。

下载界面显示在 Chrome 原生侧边栏，浏览视频时无需切换到新标签页。Bilibili 页面上的工具栏图标为粉色，其他网站为灰色且不可用。

[产品官网](https://www.instap.net/bili-ninja/) · [隐私政策](PRIVACY.md) · [问题反馈](https://github.com/sickate/bili-ninja/issues) · [官网与推广计划](docs/promotion-plan.md)

## 安装

1. 使用 Chrome 116 或更新版本，在地址栏输入 `chrome://extensions`。
2. 打开右上角的「开发者模式」。
3. 点击「加载已解压的扩展程序」，选择本项目的 **`extension` 文件夹**。
4. 在 Chrome 的扩展菜单中固定 Bili Ninja，便于使用。

下载并解压本项目后，选择其中的 `extension/` 目录。直接加载即可，无需运行 npm 命令。

## 使用

1. 打开普通 BV 视频页，例如 <https://www.bilibili.com/video/BV1RANn6bEAW>，确认视频可以正常播放。
2. 点击工具栏中高亮的 Bili Ninja 图标，下载界面会在当前标签页的侧边栏展开，不创建新标签页。再次点击可收起侧边栏。
3. 「仅音频」默认选中该稿件的全部分 P；取消不需要的分 P，点击「合并并导出音频」。
4. 导出画面时切换到「完整视频」，选择一个分 P 和清晰度，点击「导出完整视频」。插件会下载画面和声音，合并为一个有声 MP4。
5. 选择保存位置。完成后可直接播放/试听，或点击「再次保存视频/音频」。

视频模式每次导出一个完整分 P，默认选择原页面正在看的分 P；音频模式可以合并多个分 P。清晰度列表只来自实际返回的 H.264 视频流，默认优先 1080P 或更低的最高档，可手动选择其他档位；刷新或导出时若该清晰度不可用，会提示错误，不会静默降低画质。

更新已有插件：在 `chrome://extensions` 中找到 Bili Ninja，点击刷新按钮，再从原视频页重新打开插件。若通过 ZIP 安装，先用新版文件替换原目录。

v1.2 新增 `sidePanel` 权限及 Bilibili 站点访问权限，用于自动识别 B 站标签页、更新图标和加载侧栏中的视频信息。更新时如 Chrome 提示接受新增权限，接受后即可使用。

侧边栏按标签页区分，进入另一个 BV 视频或切换分 P 后自动加载对应内容，视频的跟踪参数变化不会重置界面。在 B 站首页、动态等页面会提示打开视频；切换到其他网站时侧边栏隐藏。

处理期间保持视频页和侧边栏打开。无需播放或等待视频播完。可取消任务并重新导出；关闭侧边栏、刷新或导航到另一视频时，尚未完成的任务可能中断。

这里的「合并」包括一个音轨内的 DASH 片段，以及同一 BV 稿件下选中的多个分 P；不包含推荐列表或 UP 主合集中的其他 BV 视频。

## 范围与限制

- 音频输出为原音质 AAC / M4A；视频输出为 H.264 + AAC / MP4，保留原始压缩数据，不重新编码。
- 支持普通 BV 视频的独立 DASH 流；视频模式目前只列出 H.264（AVC）清晰度，不支持 HEVC/H.265、AV1、直播、番剧、DRM、FLV 内嵌轨道及付费试看。
- 清晰度受当前登录账号的播放权限限制；需要的档位未出现时，先在原视频页确认账号可以正常播放该档位，再刷新清晰度列表。
- 多 P 无损合并要求采样率、声道和 AAC 配置相同；不兼容时会报错，可分别导出。
- 支持 Bilibili 常见的音频零偏移编辑列表与 H.264 B 帧补偿偏移；其他裁剪、延迟、变速或绝对片段偏移的特殊轨道会明确报错。
- 单个画面流/音频流上限 512 MB，单次导出合计上限 1 GB。浏览器需要暂存下载和输出数据；超限时降低清晰度，音频导出可减少所选分 P。
- Bilibili 的媒体 URL 带短期签名。插件每次导出实时获取地址，并在 CDN 失败时尝试备用线路；失败时可刷新原视频页并重新点击插件。

## 权限与实现

- `sidePanel`：通过工具栏图标展开 Chrome 原生侧边栏。
- `scripting` 和 `https://*.bilibili.com/*` 站点访问权限：识别 B 站标签页 URL、更新图标和侧栏；在 BV 视频页的现有会话中调用视频信息与播放接口，沿用用户已有的播放权限。
- `downloads`：保存生成的本地音频/视频文件。
- `declarativeNetRequestWithHostAccess` 和三个 Bilibili CDN 域名：下载媒体流，并只为插件自身的 CDN 请求设置 Bilibili Referer。规则不影响正常网页请求。
- 不申请 `tabs`、cookies、浏览历史或全站访问权限。无遥测，无第三方脚本，不上传音频、账号信息或视频 URL。

合并器解析 MP4 的初始化信息与 `moof` / `mdat`。音频模式验证兼容性并连续排列多个分 P 的解码时间轴。视频模式构造包含两个轨道的初始化头，统一改写轨道 ID 与片段序号，按时间交错排列画面和音频分段，保留原始 PTS/DTS、B 帧补偿编辑列表和压缩采样字节，再更新总时长。

Chrome API 依据：[脚本执行](https://developer.chrome.com/docs/extensions/reference/api/scripting)、[扩展跨域请求](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)、[声明式请求头规则](https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest)。

侧边栏行为使用 [Chrome Side Panel API](https://developer.chrome.com/docs/extensions/reference/api/sidePanel) 的 `setPanelBehavior` 与按 `tabId` 设置的 `setOptions`；标签页 URL 访问由 Bilibili 站点权限限定，参考 [Tabs API 权限说明](https://developer.chrome.com/docs/extensions/reference/api/tabs)。

MP4 初始化段和媒体段结构参考 [W3C ISO BMFF Byte Stream Format](https://www.w3.org/TR/mse-byte-stream-format-isobmff/)。

## 开发与验证

```sh
npm test
```

测试需本机有 Node.js 20+、FFmpeg 和 ffprobe，仅作为开发验证工具，插件运行不需要它们。测试会生成两个不同频率的 AAC 片段，合并后检查单音轨、总时长、全部采样的连续时间戳、原始 AAC 数据完全一致，以及完整解码无错误，同时验证不兼容配置与损坏输入的拒绝路径。

可通过 `BILI_AUDIO_FIXTURE=/绝对路径/音轨.m4s npm test` 加跑真实音轨验证。已用示例 `BV1RANn6bEAW` 的完整 AAC 音轨验证：单段 713.258667 秒，重复合并两段 1426.517333 秒，完整解码无错误。真实音轨不包含在插件分发包内。

同时设置 `BILI_VIDEO_FIXTURE=/绝对路径/画面.m4s` 和 `BILI_AUDIO_FIXTURE=/绝对路径/音轨.m4s` 可加跑真实音视频合成验证。视频测试检查两条轨道的唯一 ID、全部原始压缩数据和 PTS/DTS 完全一致、片段序号连续、B 帧编辑偏移保留，以及完整音画解码无错误。

本地界面测试：运行 `node tests/preview-server.mjs`，访问 `http://127.0.0.1:8765/?source=1`。此开发页面模拟 Chrome API，使用生成的测试音画验证两种模式、分 P、清晰度、合并和预览；添加 `&slow=1` 可验证取消与异步切换，不执行扩展安装或真实下载保存对话框。

`tests/sidebar.test.js` 使用模拟 Chrome API 验证图标、侧栏配置、启动恢复、标签页切换、同页导航与快速跳转；原生侧栏的实际开关需要加载扩展后在 Chrome 中验证。

打包：`npm run package`。工具栏 PNG 图标可用 `python3 scripts/generate-icons.py` 重新生成，无第三方依赖。

`extension/` 是可独立加载的插件；`tests/` 仅用于开发，不需要安装到 Chrome。

## Instap 官网

`website/` 包含公司首页、Bili Ninja 产品页和安装教程；隐私正文从本仓库 `PRIVACY.md` 生成。官网 ZIP 安装应选择直接包含 `manifest.json` 的解压目录，与源码安装的 `extension/` 目录不同。公司联系邮箱为 `tzhu@instap.net`。

```sh
npm run build:website
python3 scripts/verify-website.py --dist dist
npm run preview:website
```

本地预览地址为 `http://127.0.0.1:4173`。构建产物在忽略的 `dist/`，包含同站图片、样式、脚本、版本化 ZIP 和 `release.json`；版本、大小及 SHA-256 自动取自实际发布包。打包使用固定文件元数据，避免文件修改时间改变相同源代码的 ZIP 校验值。

来源参数通过站内产品链接显式传递到下载请求，允许五个 UTM 字段和受限字符，不使用 Cookie、本地存储或统计 SDK。访问与下载日志不代表安装或实际使用。Chrome 应用商店条目在真实公开链接确认前显示待上线。

官网部署到 maru 的独立静态目录，与 read-ai 等站点分开；发布要求已提交、已推送的干净工作区，支持暂存、原子切换和回退。操作、验收范围与限制见[部署文档](docs/website-deployment.md)。
