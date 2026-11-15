# ZIP 下载请求统计运维

本方案只为 `www.instap.net` 版本化 ZIP 增加独立访问日志，不需要应用服务、Cookie、扩展遥测或第三方统计。配置和脚本存在于仓库不代表已部署；实际安装及验收由主 Agent 单独记录。

## 数据与归因边界

`deploy/instap.nginx.conf` 在 `http` 上下文定义 Instap 专属 `map` 和 JSON `log_format`，仅 HTTPS ZIP location 写入 `/var/log/instap-downloads/downloads.jsonl`。该 location 的 `access_log` 覆盖继承的 combined 访问日志；其他页面和其他域名的既有日志配置不变。该专用文件只包含：

- 带时区的服务器时间、版本化 ZIP 路径、HTTP 状态、方法、实际响应正文字节数。
- `source`、`medium`、`campaign`、`content` 四个 UTM 值；各值仅允许 `[A-Za-z0-9._~-]{1,80}`，区分值大小写。不记录 `utm_term`、IP、UA、referrer、完整 URL 或原始 query。

这属于字符及长度白名单，并非可信渠道身份校验。访客可以伪造 UTM；禁止在推广链接的 UTM 中放姓名、联系方式、账号等个人信息。参数缺失或不合规时记录空字符串；同一 UTM 键重复出现时整组归因为空，防止按首值制造确定归因。`utm_source=qa`（汇总时大小写不敏感）归入 QA，其余仅称 `non_qa`，不能据此证明是自然用户流量。

Nginx `$arg_*` 读取原始、未百分号解码的值，参数名匹配不区分大小写；站点 `URLSearchParams` 会解码且键名区分大小写。因此直接请求 ZIP 的编码值（例如 `%71a`）会保守记为无来源；经产品页传播的合法参数会由前端规范化。重复检测同样忽略键名大小写，含无等号的重复键也拒绝。不要从历史 combined 日志、IP 或 referrer 补猜来源。未归因可来自直达、编码、不合规值、丢失参数或缓存等，无法区分。

`escape=json` 处理 JSON 转义，统计脚本再次校验路径、状态、时间、字节与来源格式；不合规来源整组清空，不输出原始坏记录。既有 Nginx `error_log` 在处理文件错误等情况时仍可能写请求信息；本方案的数据最小化声明专指上述独立访问日志，不能扩展为整台服务器的日志承诺。

## 安装、验收与回退

只操作官网 vhost、独立日志目录和独立 logrotate 文件。先记录 `current`、`nginx -t` 与其他域名状态，并备份 `/etc/nginx/sites-available/instap.net` 及 `/etc/logrotate.d/instap-downloads` 原文件/缺失状态。确认 `/etc/nginx/nginx.conf` 的 sites-enabled include 位于 `http`，检查 `nginx -T` 是否对该 ZIP location 另有 logging 覆盖；不要将带私钥或其他域名信息的完整输出提交仓库。

上传已审查的配置至 `/tmp` 后，在服务器逐步执行，检查每步返回值：

```sh
sudo install -d -o root -g adm -m 0750 /var/log/instap-downloads
# 仅首次创建，若文件已存在则保留它，不能用install空文件覆盖历史日志。
sudo test -e /var/log/instap-downloads/downloads.jsonl || sudo install -o www-data -g adm -m 0640 /dev/null /var/log/instap-downloads/downloads.jsonl
sudo install -o root -g root -m 0644 /tmp/instap.nginx.conf /etc/nginx/sites-available/instap.net
sudo nginx -t
# 上一步通过后才执行：
sudo systemctl reload nginx
```

管理员可读，Nginx master 以 root 打开文件并向 worker 传递描述符；不要授予站点部署账号整个 `/var/log` 权限。日常汇总使用 `sudo` 或管理员准备的 0600 私有快照，不把原始日志和报告放入网站根目录、dist 或 Git。

`deploy/instap-downloads.logrotate` 只匹配上述 `.jsonl`，与 Ubuntu 现有 `/var/log/nginx/*.log` 不重叠。安装前检查现有 logrotate 是否另有 `/var/log/instap-downloads/*` 等重叠规则；先备份或记录目标缺失，再安装：

```sh
sudo install -o root -g root -m 0644 /tmp/instap-downloads.logrotate /etc/logrotate.d/instap-downloads
sudo logrotate --debug /etc/logrotate.d/instap-downloads
```

每日轮转，保留最多 30 个归档，加当前文件；归档压缩，最近一次延迟压缩。`maxage 30` 随每日轮转删除超过 30 天的归档；空日志也轮转，避免停流后旧归档长期不触发清理。依赖系统每日 logrotate 正常执行，需要检查 timer/cron；这不是独立的严格到秒删除任务。轮转后发送 Nginx reopen，不做 `copytruncate`，不修改其他日志的轮转规则。reopen 会让 Nginx 重开日志描述符，并不轮转其他站点文件。若制作了离机快照或报告，应按同样的保留期清理，不能靠服务器轮转自动删除离机副本。

真实验收分别请求：正常 GET 200、`Range: bytes=0-9` 的 GET 206、HEAD、缺失版本 404；均用 `utm_source=qa`。再检查空来源、非法字符、超长值、重复键、大小写重复键、无等号重复键与编码值。合法示例：

```text
https://www.instap.net/downloads/bili-ninja/bili-ninja-1.2.1.zip?utm_source=qa&utm_medium=browser&utm_campaign=foyege_20261115&utm_content=desktop
```

核对专用日志字段及统计输出，QA 200 与 `non_qa` 200 分开。验证 `Cache-Control`、attachment、ZIP SHA-256 和其他域名原状态，检查 debug 轮转无重复规则；生产语法和实际 map 验收不能由 Python 单元测试代替。用 QA 请求测试轮转时，管理员先评估当日运行状态，只对独立配置演练，不能强制执行全局 logrotate。

`scripts/verify-website.py --url ...` 的线上 ZIP 校验会自动附加 `utm_source=qa&utm_medium=release_verifier&utm_campaign=release_validation`；发布验收下载因此计入 QA，不混入 `non_qa_get_200`。本地 `--dist` 校验不发网络 ZIP 请求。

配置回退：恢复备份官网 vhost，`nginx -t` 通过后 reload；恢复/移除本次新增的独立 logrotate 配置。保留日志证据及权限，不删除其他站点文件，也无需改 DNS 或证书。静态页面内容按官网 release 回退流程单独回退。

## 汇总与口径

Python 3.10+，仅标准库。运行本地回归：

```sh
python3 -m unittest discover -s tests -p 'test_download_statistics.py' -v
```

在服务器的受限目录保存脚本后，可直接由管理员执行（shell glob 展开需有目录读取权限）：

```sh
sudo python3 /path/to/summarize-downloads.py /var/log/instap-downloads/downloads.jsonl /var/log/instap-downloads/downloads.jsonl.1 --date 2026-11-15
# 含压缩历史日志：用管理员shell展开，不把日志复制到公开目录。
sudo sh -c 'umask 077; python3 /path/to/summarize-downloads.py /var/log/instap-downloads/downloads.jsonl* --output /private/report.json'
```

示例中的 `/private/report.json` 代表管理员已建立的私有目录，应替换为实际受限路径。不指定 `--date` 时按所有输入日期分组；日期始终转换为北京时间（UTC+8），不取文件名、mtime 或运行机器时区。输出维度为日期、ZIP 版本、来源/medium/campaign/content、QA 类型、请求类型与 HTTP 状态。

| `request_kind` | 含义 |
| --- | --- |
| `get_200` | GET 返回 200 的服务器请求 |
| `get_206` | GET 返回 206 的分段请求；多段可能来自同一次操作 |
| `head` | HEAD，任何状态；失败 HEAD 可用 status 区分 |
| `failed` | 除 HEAD 外状态 400–599 的请求，包括 499 |
| `other` | 其余方法/状态，例如 GET 302 |

这些类型互斥，合计等于 `totals.requests`。`totals.get_200` 包含 QA；正式观察使用 `totals.non_qa_get_200`，测试使用 `totals.qa_get_200`，其他类型也有这两个前缀的独立计数。`response_bytes` 只累计服务器正文发送字节数。不能把 200、206 或总字节数称为独立用户数、完整下载数、安装数或导出成功数。

脚本对每个输入先制作临时稳定快照，按解压后的完整文件 SHA-256 去重，因此同路径重复传入、普通/压缩轮转副本不会重复累计；同一文件中完全相同的多行仍保留为多个请求。不维护永久累计状态，每次从明确的一组日志重算，不能把历次输出相加。输入应是同一站点一次完整轮转链或稳定快照；轮转移动文件期间请先做管理员快照，再运行汇总。没有请求 ID 的最小日志不能可靠去重互相重叠的部分快照，也不能分辨内容恰好相同的独立完整日志，不能混入不同服务器或重复采集区间。

无效 JSON/模式行计入 `input.invalid_records`，继续产生报告但退出 1，提示数据需检查；文件读取或 gzip 损坏退出 2，不交付部分报告。`attribution_rejected_records` 表示脚本拒绝不安全来源的记录数，仍作为未归因请求统计；Nginx 已过滤为空的值无法再分辨原因。输入空文件是正常情况。

版本 ZIP 使用一年 `immutable` 缓存：浏览器或代理从缓存满足下载时，服务器没有新请求，因此本日志天然漏记这些操作；重试、机器人、分段、下载失败或用户中止又可能产生额外请求。不要为提高数字取消已发布版本的缓存策略，不新增浏览器事件上报。日志启用前没有这些专用字段的历史数据保持未知。
