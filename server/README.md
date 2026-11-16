# 临时网页下载后台

Python 3.9+ 标准库服务，依赖系统 `ffmpeg` / `ffprobe`，不安装 Python 包。仅监听 `127.0.0.1:9014`，通过同站 Nginx `/api/bili-download/` 发布。API 与前端契约见 [实施计划](../docs/web-download-plan.md)。默认源站是 `https://www.instap.net`，部署时必须与前端真实 origin 一致。

## 运行与验证

```sh
PYTHONPYCACHEPREFIX=/tmp/bili-ninja-pycache python3 -m unittest discover -s tests/server -v
python3 -B server/bili_download.py --state-dir /tmp/bili-download-private-cache --origin https://www.instap.net --ffmpeg /usr/bin/ffmpeg --ffprobe /usr/bin/ffprobe
curl --fail http://127.0.0.1:9014/api/bili-download/health
```

macOS 可用 `--ffmpeg /opt/homebrew/bin/ffmpeg --ffprobe /opt/homebrew/bin/ffprobe`。HTTP 测试会绑定临时 loopback 端口；受限沙箱须允许本地监听。测试包括 URL/DNS 固定与重定向、媒体大小上限、能力令牌、排队、磁盘/缓存预留、过期和重启清理、HTTP 附件，以及真实 H.264/AAC 合成、重封装和完整解码。真实 B 站样本测试须另行进行，单测通过不代表上游或线上可用。

POST 必须包含单个精确 `Origin` 与 `Content-Type: application/json`，拒绝跨站 `Sec-Fetch-Site`。支持普通 BV URL 的 `p=1..9999` 与 `b23.tv/[A-Za-z0-9]{4,32}`；提交时只将已知输入站点的 HTTP 转为 HTTPS，丢弃 fragment 和 b23 分享 query。实际每一次上游请求始终限定 HTTPS、无端口/用户信息，且逐跳域名与 DNS 校验。短链最终必须落在合法 BV 页面；不会请求这个最终页面。元信息取公开 `x/player/pagelist`，播放地址取匿名 `x/player/playurl`，不使用账号、Cookie、代理环境或挑战绕过。仅接受非试看 H.264/AAC DASH，或上游明确返回的单段 MP4 durl；不合并多个 durl。

## 默认资源与隐私边界

- 2 个工作线程，最多 4 个等待位，活动加排队的硬上限为 6。每个任务保守预留输入 512MiB + 输出 512MiB；缓存总上限 3GiB，因此实际同时接纳数量也受此预留限制（空缓存最多 3 个任务）。磁盘额外保留 512MiB，任务上限 512 条。
- 单流 256MiB，单任务输入合计 512MiB，输出严格小于 512MiB。输出用独立 Python 子进程设置 `RLIMIT_FSIZE` 后 exec ffmpeg，超过限制报错，不以截断文件视为成功。系统服务再限制内存 768MiB、96 个任务/线程和 192 个 FD。
- 每个任务从提交开始最多 240 秒，包含排队、DNS、下载和处理。DNS 用受期限约束的短命子进程执行；HTTP 每次底层读取检查任务 deadline。连接/单次读取最多 12 秒，重定向最多 4 次，最多尝试 4 个可信媒体候选。
- 成功文件 15 分钟有效；失败记录 5 分钟后清理；每 5 秒及 API 访问时清理。重启不恢复任务，清空专用缓存中全部遗留项（包括符号链接本身，不跟随链接）。`--state-dir` 必须是**专用可丢弃目录**，禁止指向共享数据目录。
- 提交令牌桶为每客户端突发 4 次、每 600 秒补满；读取为突发 180 次、每分钟补满；文件领取另限突发 6 次、每 600 秒补满。桶表上限 4096；最多 24 个 HTTP 处理线程，连接输入 10 秒超时，文件传输总时限 120 秒。
- 不记录请求路径、请求 URL、媒体签名或异常详情。URL 只存在未结束任务内存，结束即丢弃。私有任务目录权限 0700，文件默认 0600；媒体不进入 Git/网站发布目录。
- 192 bit 随机任务 ID 与独立 256 bit 下载令牌；持有链接者可读取状态或下载。API 全部 `no-store`；文件强制 attachment，标题经文件名清理和 RFC5987 编码。无 CORS、Cookie 或持久浏览器身份。不要分享临时链接。
- 可信媒体后缀只有 `bilivideo.com/.cn/.tv`。DNS 所有答案都须公网地址，实际连接固定该答案并保持原 TLS 主机名校验，忽略系统代理变量。IPv6 排除映射私网、6to4、Teredo 与非全球单播范围。ffprobe 与 ffmpeg 只接触本地文件，并强制 MOV/MP4 demuxer 与 `file,pipe` 协议，不将远端签名 URL 交给它们。
- 服务只信任 loopback 连接里的单个有效 `X-Real-IP`；专属 Nginx location 必须用 `$remote_addr` **覆盖**该头并清空 XFF。后台端口禁止公网暴露。同机用户可以访问 loopback，部署账号与主机权限仍须可信。

## 安装与回退

以下步骤由主 Agent 按项目部署授权执行，后台开发任务本身不操作生产环境。

1. 先记录当前网站 release、完整 Nginx 配置、已有同名 service 和后台目录。保持前一版可回退；新服务不修改既有统计 service。
2. 创建无登录专用系统账号 `instap-bili`，将本文件夹的 `bili_download.py` 安装到 `/usr/local/lib/instap-bili-download/releases/<gitrev>/` 并原子切换 `current` 链接，root 拥有且后台账号只读；不需要 venv、凭据或任何媒体初始化。systemd `StateDirectory` 创建可写状态根，后台在其中创建并清理独立 `cache` 子目录。
3. 安装 [独立 service](../deploy/instap-bili-download.service)，核对 origin、Python 与 ffmpeg 路径；`systemd-analyze verify`、`systemctl daemon-reload` 后启动，先仅 loopback 健康与非法 URL 验证。确认监听地址只有 127.0.0.1。
4. 安装 snippet 为 `/etc/nginx/snippets/instap-bili-download.conf`，只在 www HTTPS server 内 include [API location](../deploy/instap-bili-download.nginx.conf)。不能将 API 并入其他站点或开启路径日志。`nginx -t` 后 reload；网站按既有 release 流程 stage/activate。
5. 经公网 HTTPS 验证 health、错误 POST、真实 MP4/M4A 下载、ffprobe 轨道、完整解码、有效期、旧站点和 ZIP。用实际浏览器 Origin 测试；纯 curl 提交需明确 `Origin: https://www.instap.net`。检查 service journal 仅含系统生命周期信息、不含原始链接。启用开机启动前完成真实下载验收。
6. 任一关键验收失败，恢复保存的 Nginx 配置并 `nginx -t`/reload，回退网站 current，停止/禁用新 service；必要时恢复上一版后台文件并启动。新任务和文件是临时数据，重启即作废。保留备份和验收证据，不改 DNS/证书/邻居站点。

`health` 仅证明 HTTP 进程存活，不证明 B 站可达或下载能力。412/风控、媒体拒绝、匿名不可播放、任务超限都会成为安全中文错误；没有成功文件时绝不返回 ready。交付报告应分别记录本地单测、远端 CI、线上真实下载状态。
