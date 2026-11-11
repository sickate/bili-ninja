# Instap 官网部署与验收

## 实际发布结果（2026-11-12，Asia/Shanghai）

以下是已执行结果；后文保留部署前调查与可复用操作流程，不代表所有人工验收均已完成。

| 项目 | 结果 |
| --- | --- |
| 公司首页 / 产品页 | `https://www.instap.net/` / `https://www.instap.net/bili-ninja/` |
| 线上代码提交 | `5adcf42d87e765cf5886b5dd1f798be4007934cd`，已推送至 origin/main |
| 发布目录 | `/var/www/instap.net/releases/20261111T144444Z-5adcf42d87e7` |
| 当前指向 | `/var/www/instap.net/current` → 上述版本目录 |
| Nginx 配置 | `/etc/nginx/sites-available/instap.net`，同名 sites-enabled 软链 |
| 备份 | `/var/backups/instap-20261111/`，包含发布前不存在标记、站点基线、HTTP 临时配置及原 www DNS 记录 |
| www A | 已通过阿里云 CLI OAuth/API 从 `106.15.154.30` 更正为 `47.116.75.216`；原 default 线路、TTL 600 保留 |
| DNS 验证 | maru 的权威响应包含 `aa` 且为新地址；最终本机普通 DNS 也已更新，无解析覆盖的线上验收通过 |
| HTTPS | www 独立证书，SAN 仅 www.instap.net，到期时间 2027-02-09 14:49:25 UTC；TLS 校验未关闭 |
| 自动续期 | Certbot timer active；www 的 staging 续期演练成功；独立 deploy hook 已实际检查配置并重载 Nginx，HTTP ACME 挑战路径已公网验证并清理 probe |
| 续期 hook 提交 | `03c52a3`，root:root / 0755；服务器 SHA-256 与已推送文件一致；只匹配 www 证书 |
| 扩展发布包 | v1.2.1，22,283 字节，SHA-256 `f35dd3c1542a266057ac3b24e46b4207059c84c10b0dbb8d08f235c9daf5a3ea` |
| 下载地址 | `https://www.instap.net/downloads/bili-ninja/bili-ninja-1.2.1.zip` |
| 线上校验 | 2026-11-11 16:06 UTC：五页及 14 项资源通过；实际 ZIP 内容、版本、大小、SHA-256、CRC 与本地扩展一致 |
| HTTP 跳转 | 301 至 HTTPS，保留路径和 UTM 查询参数；ZIP 为 application/zip、attachment，使用版本化 immutable 缓存 |
| 既有站点 | read-ai 200、reports 200、vellt 404，与部署前一致 |
| 本地测试 | 扩展测试 22 通过、2 项真实样本跳过；来源传递/复制行为、隐私正文与发布回退检查通过 |
| 远端 CI | GitHub 查询成功，该提交无 Actions 运行记录；未宣称 CI 通过 |
| 桌面浏览器 | 原生 Chrome 已实看公司首页和产品首屏；实际页面的 ZIP、教程和产品链接均携带本次 UTM 参数 |

本机原 DNS 缓存曾短时指向旧 IP；早期指定新 IP 的报告单独记录了解析覆盖条件，最终 `artifacts/website-online-verification.json` 是普通解析的结果。报告和 DNS 备份在忽略的 artifacts/ 中，服务器亦保留原 DNS 备份，凭据未提交。

手机视觉与复制交互、Windows/macOS 真实安装截图、干净 Chrome 安装与真实导出、国内多运营商网络仍待验收，详情见[开发计划的未完成验收](website-implementation-plan.md)。官网教程明确标注现有操作示意，不能将这些未执行项目报告为完成。

## 范围与当前证据

本流程只操作 `www.instap.net` 的静态官网、独立发布目录与独立 Nginx 配置。DNS、证书和 Nginx 的初次配置由主 Agent 在核对后执行；部署脚本不会修改它们。生产凭据、私钥、账号文件不进入源码或静态产物。

2026-11-11 的只读调查：

- `../read-ai/fabfile.py` 确认连接为 `tzhu@maru`；本机没有将 maru 映射到公网 IP 的 SSH Host 配置，但主机名可通过本机网络解析并连通。公网地址 `106.15.154.30:22` 当次连接在 SSH banner 阶段超时，不能据此判定服务器或服务离线。
- 登录后的 hostname 为 `maru`，Nginx 为 Ubuntu 1.18.0，Python 为 3.10.12。`sudo -n` 可用，`/var/www` 所在卷当时约有 21 GB 可用。
- 活跃 Nginx 配置为 `read-ai.instap.net`、`reports.instap.net`、`vellt.instap.net`，分别已有自己的证书；未找到 `www.instap.net` 或 `instap.net` 的活跃 server_name 或证书。read-ai 历史安装脚本包含主域，但现行配置已经使用 read-ai 子域，不应重新执行该旧脚本。
- 本机只读公网 DNS 查询得到 `www.instap.net → 106.15.154.30`，裸域当次未返回地址。www 的公网 HTTP/TLS 请求超时；在 maru 上以 www Host 请求本机 Nginx 得到 404。以上均是部署前快照，不能当成上线结果。

已确认网站联系邮箱为 `tzhu@instap.net`。只为 www 配置站点与证书；裸域没有解析，不能未经单独核对就将其加入证书申请。后续只读查询 maru 的阿里云元数据 `eipv4` 已直接确认其公网地址为 `47.116.75.216`，三个现有子域的 A 记录也均为此值。因此调查时 www A 记录与 maru 不符，实际发布时已在保存原记录后更正，结果见首节。元数据字段依据[阿里云 ECS 官方资料](https://help.aliyun.com/en/ecs/user-guide/view-instance-metadata/)，仅查询公开 IP 字段，不读取角色凭据。

补充基线（同日只读）：Certbot 为 1.21.0，已有一个生产 Let’s Encrypt 账号，`certbot.timer` 已启用定期执行。以下为在 maru 上以 `--resolve 域名:443:127.0.0.1` 通过真实 TLS 校验取得的部署前结果，vellt 的现有 404 不能误判为本次回归失败：

| 子域 | 原首页状态 | 证书到期（UTC） |
| --- | --- | --- |
| read-ai.instap.net | 200 | 2027-02-03 03:00:18 |
| reports.instap.net | 200 | 2026-12-19 17:56:15 |
| vellt.instap.net | 404 | 2026-12-30 14:22:06 |

每张证书的 SAN 仅包含自身域名，没有 www；新官网需要独立证书。

## 目录、版本与权限

建议独立使用下列目录，首次需由管理员创建并将官网根目录交给部署账号：

```text
/var/www/instap.net/
  acme/                         # 仅 ACME HTTP challenge webroot
  releases/<UTC时间>-<commit>/  # 完整、不可覆盖的静态版本
  current -> releases/<版本>/  # 同文件系统内原子替换软链
  deployment-events.jsonl       # 切换记录与原指向，不由 Nginx 静态暴露
```

Nginx 只把 `current` 作为网站根目录，ACME 使用单独 location。部署脚本要求根目录已存在且为真实目录；拒绝覆盖真实 `current` 目录、站外软链和已存在的版本。仅使用 SSH 正常认证，不在命令行或文件中存密码。文件 0644、目录 0755，确保 Nginx worker 可读及可遍历。

## 发布前本地验收

在仓库根目录执行：

```sh
npm test
npm run package
npm run build:website
python3 scripts/verify-website.py --dist dist --report artifacts/website-local-verification.json
```

`verify-website.py` 使用标准库，检查五个页面及递归站内链接、锚点、图片/样式/脚本资源；拒绝页面外部嵌入资源与 HTTP 内链；下载发行 ZIP，核对根 manifest、版本、字节数、SHA-256、CRC、文件清单及每个文件与 `extension/` 的实际内容。ZIP 不得包含 extension 之外的文件。产品页必须显示版本与完整 SHA-256。

图形布局、下载点击、手机提示/复制、UTM 参数传播、干净 Chrome 安装与真实音视频导出仍需浏览器或人工验收，脚本通过不代表这些项目已验证。公网线上验证也不等于国内不同运营商网络验证。

主 Agent 完成本地复审后，先提交并推送，再从该提交重新构建。`stage` 要求工作区干净且 HEAD 已包含在已获取的 `origin/main` 中；可通过 `--remote-ref` 指定经过审查的其他已推送分支。运行前先 `git fetch origin`，防止远端跟踪信息过期。

## 首次 Nginx 和证书配置

此部分不是自动部署脚本的一部分。执行前确认只新增当前不存在的官网配置，不修改 read-ai/reports/vellt，不停止其他进程，也不运行邻居项目的旧安装脚本。

1. 在服务器记录 `date -u`、`sudo nginx -t`、现有 `sites-enabled` 软链列表。将准备修改的官网配置、原软链目标和缺失状态保存到仅管理员可读的 `/var/backups/instap-<UTC时间>/`。首次没有旧官网配置时记录“原文件不存在”；不要把其他站点证书或运行时密钥带回仓库。
2. 建立官网根目录、`releases`、`acme`，保证部署账号可写、Nginx worker 可读。通过下节 stage/activate 发布已提交构建。
3. 先创建仅监听 80、仅匹配 `www.instap.net` 的独立配置；ACME location 指向 `acme` 目录。通过 `sudo nginx -t` 才 reload。以 `curl --resolve www.instap.net:80:127.0.0.1 http://www.instap.net/` 检查专属路由。确认公开 80 可达后才申请证书。
4. 使用现有 Certbot 的 webroot 方式，只申请 www 的证书；证书联系邮箱使用已确认的 `tzhu@instap.net`。不要将现有子域添加到同一证书，也不要让插件重写其他 vhost。若公网 80 不可达，先排查实例安全组/公网入口；不要关闭防火墙来试错。
5. 配置独立 HTTPS vhost，使用新签发的 www 证书与本机已有 Certbot TLS 公共参数；HTTP 保留 ACME location，其余请求 301 到 `https://www.instap.net$request_uri`。`nginx -t` 通过后 reload，再分别验证 HTTP 跳转与 TLS。

仓库内提供两个可审查配置：`deploy/instap-http.nginx.conf` 为申请证书前的 HTTP 配置，`deploy/instap.nginx.conf` 为签发后的最终配置。最终配置只包含 www 的 HTTP 跳转与 HTTPS，保留 ACME webroot，下载 ZIP 使用 attachment 与版本化长期缓存，页面和发布元数据要求重新验证缓存。

首次 bootstrap 的具体顺序（由主 Agent 执行，目标文件已存在时先备份，不能直接覆盖）：

```sh
# 服务器：建立独立目录，不碰任何现有应用目录。
sudo install -d -o tzhu -g www-data -m 0755 /var/www/instap.net /var/www/instap.net/releases /var/www/instap.net/acme
# 本地：按下节 stage/activate 已提交版本；随后上传已审查的初始配置到临时文件。
scp deploy/instap-http.nginx.conf tzhu@maru:/tmp/instap-http.nginx.conf
# 服务器：确认目标尚不存在；若已存在，停止并审查/备份。
sudo test ! -e /etc/nginx/sites-available/instap.net
sudo test ! -e /etc/nginx/sites-enabled/instap.net
sudo install -o root -g root -m 0644 /tmp/instap-http.nginx.conf /etc/nginx/sites-available/instap.net
sudo ln -s /etc/nginx/sites-available/instap.net /etc/nginx/sites-enabled/instap.net
sudo nginx -t
sudo systemctl reload nginx
# 公开80及挑战路径验证可达后，才执行申请；仅申请www域，不改变其他vhost。
sudo certbot certonly --webroot -w /var/www/instap.net/acme -d www.instap.net --cert-name www.instap.net --email tzhu@instap.net --keep-until-expiring --non-interactive
# 本地：上传最终配置；服务器备份上述HTTP配置后，以最终配置替换此同名官网文件。
scp deploy/instap.nginx.conf tzhu@maru:/tmp/instap.nginx.conf
# 服务器：先检查签发后的实际证书名称与配置一致，再安装最终配置。
sudo install -o root -g root -m 0644 /tmp/instap.nginx.conf /etc/nginx/sites-available/instap.net
sudo nginx -t
sudo systemctl reload nginx
```

上述命令使用已存在的 Certbot 账号，需逐步检查退出状态执行，`nginx -t` 失败时不得执行 reload。若需新注册账号，先由账号持有人处理相应协议。Certbot 若签发了带 `-0001` 的名称，应审查原因并将最终配置路径与实际证书匹配，不能猜测路径。证书签发与续期使用现有 Certbot 机制，完成后检查其 timer/cron 与新证书 webroot，不能只验证首次签发。

### 续期后加载新证书

Certbot 1.21 的 webroot `certonly` 配置仅续期磁盘文件，Nginx 还需重载才能使用新证书。`deploy/renew-instap-certificate.sh` 作为 root 所有、0755 的脚本安装到 `/etc/letsencrypt/renewal-hooks/deploy/50-instap-nginx-reload`。它只匹配 `/etc/letsencrypt/live/www.instap.net` 的 `RENEWED_LINEAGE`，先 `/usr/sbin/nginx -t`，通过后 `/usr/bin/systemctl reload nginx`；其他证书不触发。无需编辑其他证书、全局 cli.ini 或定时器。

先审查、提交并推送脚本；初次安装应确认目标不存在，保留缺失状态供回退。分别执行：

```sh
# 续期演练：使用 staging CA，不替换现有生产证书。
sudo certbot renew --cert-name www.instap.net --dry-run --non-interactive
# 实际 hook 验证：先检查配置，然后温和重载 Nginx。
sudo env RENEWED_LINEAGE=/etc/letsencrypt/live/www.instap.net /etc/letsencrypt/renewal-hooks/deploy/50-instap-nginx-reload
```

该版本的 dry-run 会跳过 deploy hook，不支持新版的 `--run-deploy-hooks`，因此两项结果必须分别记录；只看到续期命令退出 0 也不能代替 hook 输出和最终 TLS 验证。参见 [Certbot v1.21 命令说明](https://github.com/certbot/certbot/blob/v1.21.0/certbot/docs/cli-help.txt)。安装后还应验证 HTTP 的 ACME 路径直接返回挑战内容，并回归其他站点。回退此项仅移除本次新增的 hook，不修改其他续期任务。

目录页的 `index.html` 内部跳转会命中 HTML location。ZIP 文件名不可复用为不同字节内容。部署版本目录保留旧包用于回退；若未来需要跨版本长期下载入口，构建时需显式带入旧版已验证 ZIP，不要默认 current 会包含所有历史包。

## 分阶段上传、切换与线上验收

```sh
python3 scripts/deploy-website.py status --host tzhu@maru --root /var/www/instap.net
python3 scripts/deploy-website.py stage --host tzhu@maru --root /var/www/instap.net
# stage 返回 staged 版本ID，并保持 current 不变；检查返回的revision。
python3 scripts/deploy-website.py activate --host tzhu@maru --root /var/www/instap.net --release <stage返回的版本ID>
python3 scripts/verify-website.py --url https://www.instap.net --report artifacts/website-online-verification.json
```

`stage` 再执行本地验收，仅打包 dist 普通文件；上传归档先核对传输 SHA-256，再逐文件核对部署 manifest，成功后才形成不可覆盖的发布目录。归档拒绝绝对路径、`..`、软链、重复和隐藏条目。`activate` 重算逐文件 hash 后，使用 `os.replace` 原子切换 `current`。切换操作有独占锁；脚本不清理任何旧版本。

线上脚本通过系统 TLS 信任验证证书，实际下载并逐文件核对 ZIP 与本地 extension。另需记录 `http://www.instap.net/` 301 跳转结果、独立 HTTPS/TLS 检查、浏览器验收与公网访问证据。先前存在的三个子域应做简短只读回归，保证未受官网新增配置影响。访问日志只能描述页面与 ZIP 请求，不能视为独立用户、安装或导出成功。

## 回退

- 发布内容失败：使用切换事件中的 `previous` 或 `status` 的历史版本 ID，执行 `rollback`；该动作与 activate 一样验证目标 hash 并原子切换。首次发布没有旧版本时不要伪造回退目标；移除本次新增 vhost 并恢复发布前默认行为。
- 配置失败：恢复该次备份的官网配置和原软链（原来不存在则移除本次新增文件/软链）；先 `sudo nginx -t` 再 reload。不要恢复或编辑邻居站点配置，也不要停止其服务。
- DNS 本次若未修改则无需回退。若后续确需修改，先记录原记录 ID、值、线路和 TTL，失败按该记录原样恢复。
- 回退后重新运行线上验收和子域回归，保留失败发布目录与事件记录以供排查，不自动删除证据或证书。

示例：

```sh
python3 scripts/deploy-website.py rollback --host tzhu@maru --root /var/www/instap.net --release <上一版本ID>
python3 scripts/verify-website.py --url https://www.instap.net --report artifacts/website-rollback-verification.json
```

交付明确分别记录本地验证、Git 提交/推送、远端 CI、maru 发布、线上验收和浏览器安装/导出验收。任何未执行或受阻项目保持待验收状态。
