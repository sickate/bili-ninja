# Chrome Web Store listing

## Name

Bili Ninja · 音视频提取

## Short description

在 Chrome 侧边栏保存有权播放的 Bilibili 视频或音频，支持 MP4 导出与多分 P 音频无损合并。

## Detailed description

Bili Ninja 是一个极简的 Bilibili BV 视频音画保存工具，下载选项直接显示在 Chrome 侧边栏。

主要功能：
- 完整视频：选择当前账号可用的清晰度，将画面和声音合并为一个 MP4 文件。
- 仅音频：提取 AAC 音轨，按原顺序将所选分 P 合并为一个 M4A 文件。
- 侧边栏：B 站页面上的图标高亮，其他网站变灰；进入另一视频或分 P 时自动更新。
- 支持下载进度、取消和本机预览。
- 无需额外安装软件，媒体合并在本机完成，保留原始压缩音画数据。

使用：在 Bilibili BV 视频页点击扩展图标，选择「仅音频」或「完整视频」，再选择分 P、清晰度并导出。

隐私与数据：扩展访问 B 站标签页网址、视频标题、分 P 和所选媒体，以提供下载功能。视频内容不上传给开发者；没有统计分析或广告。播放接口沿用浏览器已有 B 站会话，扩展不读取或保存密码、Cookie 值或令牌。详细说明见隐私政策。

范围：完整视频每次导出一个分 P；多分 P 合并适用于音频。当前支持 H.264 + AAC 的 MP4 与 AAC 的 M4A。单个媒体流上限 512 MB，单次导出合计上限 1 GB。处理时请保持视频页和侧边栏打开。

仅保存您有权下载或复制的内容。扩展不绕过付费试看、DRM、地区或账号播放权限限制，不支持直播和番剧。Bili Ninja 是独立项目，与 Bilibili 没有隶属或官方合作关系。

## Links

- Homepage: https://github.com/sickate/bili-ninja
- Support: https://github.com/sickate/bili-ninja/issues
- Privacy: https://github.com/sickate/bili-ninja/blob/main/PRIVACY.md

## Suggested category and language

- Category: Tools / 工具 (select the matching current dashboard category)
- Language: 简体中文
- Price: Free

## Single purpose

在用户已有播放权限范围内，将其选择的 Bilibili BV 视频或音频在本机保存为 MP4 或 M4A 文件。

## Permission justifications

- `sidePanel`: 在当前 B 站标签页旁显示视频、分 P、清晰度、下载进度及导出界面。
- `scripting`: 在 B 站视频页的现有会话中执行随扩展打包的固定函数，读取视频信息及播放接口返回值。不会下载或执行远程代码。
- `downloads`: 将本机合并生成的 MP4/M4A 保存到用户选择的位置。
- `declarativeNetRequestWithHostAccess`: 仅为本扩展发往 Bilibili 媒体 CDN 的请求设置 B 站 Referer，以取得所选媒体。规则限定扩展自身的 initiator，不修改普通网页请求。
- `https://*.bilibili.com/*`: 自动识别 B 站标签页、显示图标和侧栏状态，并在 BV 视频页内获取播放信息。无需其他网站的页面访问权限。
- `https://*.bilivideo.com/*`, `https://*.bilivideo.cn/*`, `https://*.bilivideo.tv/*`: 下载 Bilibili 播放接口返回的独立音频和画面流。地址会在这些 CDN 子域及备用线路间变化；代码只接受这些域的 HTTPS 地址。

## Remote code

No. All executable JavaScript is included in the uploaded extension package. Network responses are JSON metadata and media bytes, not executable code. The test harness and developer tests are not included in the package.

## Data handling declarations to transfer to the dashboard

Do not claim the extension handles no user data solely because processing is local. Website content (video metadata/media) and Bilibili browsing activity (current page URL) are accessed to provide the disclosed single purpose. No such data is sent to a developer backend, sold, or used for advertising. The browser sends its existing Bilibili authentication cookies directly to Bilibili when making authenticated playback requests; cookie values are not read or stored by the extension.

Complete the current dashboard's data-use fields consistently with PRIVACY.md and the actual definitions shown there. Any registration agreement, payment, identity verification, or legally binding declaration requires the publisher's participation or confirmation.
