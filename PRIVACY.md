# Bili Ninja Privacy Policy / 隐私政策

Effective date / 生效日期：2026-11-10

Bili Ninja is a Chrome extension for saving Bilibili BV video or audio that the user chooses and already has permission to play. It processes media on the user's device. It has no developer-operated backend, analytics, advertising, or tracking SDK.

Bili Ninja 用于保存用户选择且已有播放权限的 Bilibili BV 视频或音频。媒体处理在用户设备上完成；扩展没有开发者运营的服务器、统计分析、广告或追踪 SDK。

## Data accessed and why / 访问哪些数据

- **Bilibili page URLs:** the extension checks Bilibili tab URLs to highlight its icon and display the current video or part in the side panel. It does not request browser-history access or record a browsing history.
- **Video information and website content:** when the user opens the side panel or requests an export, the extension reads the video's identifier, title, part list, available streams, and the selected media bytes. These are used to name the output, show download choices, and create the requested MP4 or M4A file.
- **Existing Bilibili session:** requests for playback information use the browser's existing Bilibili session. The browser may send its Bilibili-managed authentication cookies directly to Bilibili. The extension does not read, copy, store, or send cookie values, passwords, or tokens to the developer.

扩展访问 B 站标签页网址，用于图标状态及当前视频识别；访问视频编号、标题、分 P、可用媒体流和用户选择的音画内容，用于显示下载选项、命名及生成文件。不读取浏览历史，不保存浏览记录。播放接口沿用浏览器现有的 B 站登录会话；认证 Cookie 由浏览器直接发给 B 站，扩展不读取、复制或保存 Cookie 值、密码或令牌，也不将其发送给开发者。

## Network requests and sharing / 网络请求与共享

The extension connects to Bilibili and its `bilivideo.com`, `bilivideo.cn`, or `bilivideo.tv` media servers only as needed to retrieve the requested video information and media. Those services receive the network information inherent in an HTTPS request, such as the user's IP address; Bilibili's own privacy terms govern its service. Audio/video is merged locally and is not uploaded to the developer or an unrelated service.

No user data is sold, rented, used for advertising, or shared with data brokers. Opening the optional GitHub help/privacy links is a normal user-initiated visit to GitHub and is governed by GitHub's privacy policy.

扩展仅为获取所需信息和媒体而连接 Bilibili 及其媒体服务器。相关服务会收到 HTTPS 请求固有的信息，例如 IP 地址；其服务适用 B 站自身隐私条款。音视频在本机合并，不上传到开发者或无关服务。不出售、出租用户数据，不用于广告，不向数据经纪商共享。用户主动打开 GitHub 帮助或隐私链接时，属于访问 GitHub 网站，适用 GitHub 的隐私政策。

## Retention and deletion / 保留与删除

Video metadata, stream URLs, and downloaded bytes are used transiently in the side-panel document's memory for as long as Chrome keeps that document alive. The extension does not maintain a database or cloud account for this information. State is released when that document is unloaded, reloaded, or discarded by Chrome; switching tabs can retain each tab's panel state. Saved media remains in the location chosen by the user until the user deletes it. Chrome manages its own downloads list under the user's browser settings.

视频信息、媒体地址及下载字节仅在 Chrome 保留的侧栏文档内存中临时存在，不建立数据库或云端账号。文档被卸载、刷新或丢弃后释放其状态；切换标签页可能保留各标签页的侧栏状态。已保存文件由用户自行保留和删除；浏览器的下载列表由 Chrome 管理。

## Permissions / 权限

- `sidePanel`: displays the download interface beside the current tab.
- `scripting` and Bilibili host access: identify Bilibili pages and request playback data within the current Bilibili session.
- `downloads`: save the locally generated file at a user-chosen location.
- Bilibili media-host access and `declarativeNetRequestWithHostAccess`: fetch media and set the Bilibili Referer for this extension's own media requests. The rule does not alter unrelated browsing traffic.

## Limited use / 有限使用

Bili Ninja uses accessed data only to provide its stated media-export functionality. It follows the Chrome Web Store User Data Policy, including its Limited Use requirements. There is no advertising use, sale of data, or developer access to a user's media or browsing activity.

Bili Ninja 仅为所声明的音视频导出功能使用所访问的数据，遵守 Chrome Web Store 用户数据政策及其有限使用要求。不将数据用于广告、不出售数据，开发者无法通过扩展访问用户的媒体或浏览活动。

## Contact and changes / 联系与变更

Questions can be raised through the project's public [GitHub issues](https://github.com/sickate/bili-ninja/issues). The policy and effective date will be updated if the extension's data practices change.

隐私问题可通过项目的公开 [GitHub Issues](https://github.com/sickate/bili-ninja/issues) 联系。若数据处理方式发生变化，将更新本政策及生效日期。
