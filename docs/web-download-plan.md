# 免插件网页下载实施计划

日期：2026-11-16（Asia/Shanghai）。主 Agent 先审计旧任务，再实施本轮功能。

## 旧任务核查

- 工作区干净，HEAD/origin/main 为 3b60eaf；maru current 为 releases/20261115T125912Z-3b60eaf20c57，公开统计 timer active。2026-11-15 在线报告记录六页、31 资源和 v1.2.1 ZIP 验证通过；本轮仍需重新验证线上状态。
- 下载统计、四渠道分享、中文首页、实机截图已交付。GitHub CI 历史无运行记录，不称 CI 通过。
- 尚未完成：真实多 P 保存/解码、三个页面示例的扩展导出、干净 Chrome 完整流程、Windows、真实手机及多运营商。此前推广留言仅本人页面可见；连续五分钟监测有断档，效果和逐 BV 归因未证实。昨日限时监测不自动续到今日，不追加留言。

## 目标与范围

用户在 /bili-ninja/ 粘贴 Bilibili 普通视频 URL，选择有声 MP4 或音频 M4A，生成同站临时文件链接，点击可直接保存，无需扩展。支持 BV 视频 URL 的 p 参数及 b23.tv 短链接的严格受控解析；首版每次处理一个分 P。匿名公开播放权限内获取 H.264/AAC，不提供账号输入、登录代理、付费/试看绕过、直播或番剧解析。不影响现有扩展包。

## 方案与接口约定

沿用 maru/Nginx；Python 3 标准库独立后台绑定 127.0.0.1:9014，通过 Nginx 精确的 /api/bili-download/ 前缀转发。服务器已有 ffmpeg，仅输入后台下载到独立私有目录的本地文件，stream copy 生成完整 MP4/M4A。媒体不进入 Git、dist 或长期公开目录。

- POST /api/bili-download/jobs：JSON {url, format: "mp4" | "m4a"}，返回 202 和任务对象。
- GET /api/bili-download/jobs/<id>：任务对象含 id、status、status_url；status 为 queued/resolving/downloading/processing/ready/error；可选 title、message、download_url、filename、expires_at（ISO UTC）。ready 必含下载链接和过期时间，error 含安全中文错误。
- GET /api/bili-download/files/<token>：只有准备完毕且未过期的随机令牌可下载，Content-Disposition attachment、正确 MIME、no-store。链接不含原始 URL 或上游媒体签名。
- 无 Cookie/本地存储/第三方 SDK；URL 在 POST body 中提交，代理不记录 API 路径中的令牌，后台不记录原始 URL/签名/账号。状态及文件使用不可猜测 ID。
- HTTPS 域名白名单、DNS 公网校验并固定连接地址、逐跳校验重定向、端口/用户信息拒绝，防任意代理及内网访问。仅服务器生成 API 路径和可信媒体候选。
- 默认两条处理任务、有限等待队列、请求频率限制、每流 256MiB、单任务输入合计 512MiB，输出与缓存总量受限，任务处理超时；成功文件 15 分钟过期，失败/到期清理，重启不恢复未完成任务并清理旧缓存。拒绝队列溢出与磁盘不足。

## 分工与依赖

| 任务 | 模型 / effort | 范围 | 依赖 |
| --- | --- | --- | --- |
| backend | gpt-6.1-sol / high | server/ 后台、SSRF/资源边界、任务生命周期、真实媒体处理、Python 测试、deploy 独立 service 与 API location、运维说明 | 本接口与 maru Python3/ffmpeg；不提交/部署，不改网站 |
| frontend | gpt-6-luna / medium | website/content/web-download.html、assets/web-download.js/css 与交互测试；输入/选择/轮询/错误/下载/到期与移动无障碍 | 接口；不改 build/product/privacy/共享样式，主 Agent 集成 |
| 主 Agent | 当前会话 | 审计与计划、接口协调、构建/产品页/隐私集成、独立代码审查和功能安全验证、真实 B 站样本、浏览器、提交推送和部署验收 | 两子任务；必要修正交回各负责人 |

先并行开发两部分，主 Agent 同时核对真实匿名 API 可用性与服务部署条件。服务若被平台拒绝，明确报错，不以假链接或仅画面 URL 代替成功。

## 验收与验证

1. 主 Agent 独立复审 URL/重定向/DNS 固定、请求来源与频率、令牌/路径、资源上限、TTL、并发、失败与重启清理、ffmpeg 参数和服务权限；检查 SSRF/命令注入/路径穿越拒绝测试。
2. 使用生成的短音视频验证队列、真实文件下载、ffprobe 两轨/音轨、完整解码、过期/错误/大小与并发；真实匿名 BV 样本分别验证 MP4/M4A，若上游风控准确记录环境限制。
3. 页面验证粘贴/提交、重复提交、选择格式、轮询终态、服务失败重试、超时/过期提示、链接只允许同站预期路径、键盘与窄屏。状态文字用 textContent。
4. npm test、Python 全部相关测试、官网构建和 verify、git diff --check；扩展 ZIP 必须保持 v1.2.1 / 22,283 bytes / SHA256 f35dd3c1542a266057ac3b24e46b4207059c84c10b0dbb8d08f235c9daf5a3ea。

## 部署与回退

复审通过后提交推送并从干净提交构建。记录原 current、Nginx www 配置和独立服务缺失状态；仅 www 新增 API 转发，独立服务使用专用无登录账号、StateDirectory 和加固 systemd，运行目录按版本部署。先安装后台并在 loopback 验证健康/拒绝路径，再 nginx -t/reload；stage/activate 官网并通过普通公网 HTTPS 验证页面、ZIP、API、真实下载和既有三个站点。远端 CI 单独查询并如实记录。

任一关键验收失败：恢复原 www 配置（nginx -t 后 reload）、停用本次后台并回退 current 到本轮发布前版本；保留备份和证据，不改 DNS/证书/邻居站点。只在真实线上下载验证通过后称功能上线；本地/CI/线上/浏览器状态分开交付。

## 主 Agent 发布前复审与验收

- 两子任务按指定模型和 effort 完成，主 Agent 独立审查、要求页面修正超时/重复提交/过期隐藏、要求后台强制 MOV demuxer/禁用外部数据引用，并重新运行测试。
- 主 Agent npm test：40 通过、2 既有真实扩展 fixture 跳过；新后台 33 项通过；统计 Python 16 项、监测 Python 11 项通过。官网构建、六页/32资源本地验证、git diff --check 通过；ZIP 字节及 SHA256 保持原值。
- 本机和 maru 临时目录独立处理真实 BV1bKnw6zEsV：M4A 4,457,485 字节、AAC 单轨；MP4 12,154,004 字节、H.264+AAC 双轨；时长约290.134秒，均完整解码退出0、错误输出0。测试媒体自动清理，不进 Git。
- maru 的 view 接口及视频页返回412，但正常公开 pagelist/playurl/CDN 实测可用；实现直接使用后者，无需页面 fallback、账号或挑战处理。真实效果仍以部署后公网完整任务为准。
- 浏览器连接服务 unavailable，原生 Chrome cgWindowNotFound；本轮未取得桌面/窄屏可视检查或浏览器点击下载证据，不能声称已完成此项。交互由节点模拟测试覆盖，最终文件由 HTTP/ffprobe/解码验证。
- 发布前 current 为 releases/20261115T125912Z-3b60eaf20c57；www 配置 SHA256 9b6a0cf2d5ffa588eb55fb481e89fe81f9ba72ebf145b6e27246f70fe19b0fd2，与仓库原文件一致。后台目录、service、snippet、专用用户均不存在，9014未占用；nginx -t通过。
- 最终资源默认值为缓存3GiB、额外磁盘预留512MiB、两处理线程+四名义等待位（受每任务1GiB预留约束，空缓存实际最多接纳3个）、每任务从提交到完成240秒。详见 [后台运维说明](../server/README.md)。

## 生产发布与最终验收

- 功能提交 `f70781e5b8eab322c1cd121f408faa35df093a23` 已推送 origin/main。从干净提交重新构建，官网发布目录 `releases/20261116T020518Z-f70781e5b8ea` 已激活；前版 `releases/20261115T125912Z-3b60eaf20c57` 保留可回退。
- 后台源码安装在 `/usr/local/lib/instap-bili-download/releases/f70781e5b8eab322c1cd121f408faa35df093a23/`，current 指向该版本。专用无登录账号 instap-bili；服务 active/enabled，只监听127.0.0.1:9014。源码、unit、snippet、www配置 SHA256 与提交文件一致；生产ffmpeg4.4.2支持全部最终MOV安全参数。
- Nginx原配置及缺失状态备份 `/var/backups/instap-bili-20261116T020557Z/`。独立service经systemd校验，www API snippet安装后nginx -t与reload通过；未改DNS、证书、邻居站点或统计timer。systemd校验出现既有snapd.service的RestartMode提示，不涉及本服务。
- 普通公网HTTPS完成真实POST→轮询→附件下载：BV1bKnw6zEsV的M4A 4,457,485字节、AAC单轨、SHA256 `0a6d70d3dd6db7fb4c4846707aa0fcc39f7fba524d914a90623775c3f7833c64`；MP4 12,154,004字节、H.264+AAC、SHA256 `e3c8d165f72fed1c0a3e5e4198fe4de1cedb3b857f58a788e26aecd700f6f3be`。两文件约290.133333秒，完整解码退出0/错误0，attachment/MIME/no-store/15分钟有效期均核验。跨站Origin返回403，内网URL返回400。私有证据 `artifacts/web-download-online-media.json` 不含临时令牌/上游签名。
- 服务器真实解析 `https://b23.tv/BV1bKnw6zEsV` 到对应BV的P1通过。真实常规BV下载已验证；并非所有视频、清晰度或分享短链均完成实测，上游限流/权限/过大内容会明确失败。
- 在新表单公开前重启后台，清空本轮QA缓存及限流（实际缓存子目录0），复核health后启用开机启动，再激活网站；未将QA下载令牌交给用户。
- 2026-11-16 02:09 UTC最终线上校验六页、33资源和v1.2.1原ZIP全部通过；产品表单/JS与公开health、stats JSON为200。read-ai/reports为200，vellt保持既有404。统计timer active。后台journal只见系统生命周期信息，没有原始URL/签名/令牌。
- 远端GitHub Actions运行数0，本提交check-runs数0；没有CI结果，不能称CI通过。本地与公网功能验收通过，浏览器可视/点击验收仍因工具不可用待补。此前扩展多P、Windows和真实手机待办未被网页样本验收替代。

具体回退：先按官网脚本rollback到 `20261115T125912Z-3b60eaf20c57`；恢复备份目录的instap.net至 `/etc/nginx/sites-available/instap.net`，nginx -t通过后reload；`systemctl disable --now instap-bili-download.service`。保留本次版本、备份和只读源码用于排查；若移除unit/snippet须仅移除本次新增项并daemon-reload，不删除统计、邻居站点或历史数据。
