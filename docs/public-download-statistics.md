# 官网公开下载请求汇总

本文件描述仓库中的实现及安装方法，不表示任务、路由或页面已上线。私有日志说明见 [download-statistics.md](download-statistics.md)。本功能不新增浏览器事件上报、不改 ZIP 的缓存策略、不读取历史 combined 日志、不永久累加历史输出。

## 数据接口与口径

唯一数据 URL 为 `https://www.instap.net/bili-ninja/stats/summary.json`。它通过 Nginx 的 exact location 读取 `/var/lib/instap-downloads/public/summary.json`；该文件在静态站根目录及各 release 目录之外，发布切换不替换它。不要将 `/var/log/instap-downloads` 或整个 `/var/lib/instap-downloads` 暴露为 alias/root，不要把原始日志、私有报告或真实生产汇总作为测试 fixture 提交到仓库。

`schema_version: 1` 的字段全部由生成器显式构造：

| 字段 | 内容 |
| --- | --- |
| `status` | `ok` / `error`；错误信息不含原日志、任意参数、异常文本或服务器路径 |
| `timezone`, `unit` | 固定为 `Asia/Shanghai`、`server_requests` |
| `started_at` | 固定 `2026-11-15T16:15:00+08:00`；更早的记录不计入，启用前未知 |
| `generated_at` | 上次成功汇总的北京时间 ISO 时间；从未成功为 `null` |
| `last_attempt_at` | 最近一次尝试的北京时间 ISO 时间；任务未运行或无法写文件时不会更新 |
| `window` | `start_date` / `end_date` / `retention_days: 30`；成功时仅统计今天及前 29 个北京时间自然日内、启用后的记录 |
| `channels` | 固定顺序 `x`, `xiaohongshu`, `weibo`, `wechat`, `bilibili`, `other`, `unattributed`, `qa` |
| `totals` | 下列四项窗口内汇总；从未成功时为 `null` |
| `rows` | 按 `date`、固定 `channel` 分组，同样只有下列四项计数；成功但无请求为 `[]`，从未成功为 `null` |

四项计数为 `non_qa_get_200`（GET 200）、`non_qa_get_206`（GET 206）、`non_qa_failed`（非 HEAD 的 HTTP 400–599，含 499）、`qa_requests`（QA 的全部方法和状态）。非 QA HEAD、重定向及其他请求不列入这些指标。`qa` 判断沿用私有汇总器，对来源参数大小写不敏感；QA 不是可信身份认证，非 QA 也不能保证没有测试或机器人。

渠道只读取经过私有汇总器校验的 `source`：大小写归一后，五个已知推广渠道映射到对应枚举，`qa` 独立归类，空值归 `unattributed`，其他任何值统一归 `other`。不发布 source 的原值，不发布 medium/campaign/content、版本、路径、状态明细、字节数、IP、UA、无效记录明细或任何访客资料。其他参数不参与公开分组。

页面主指标「下载请求（非测试）」指非 QA GET 200。它不等于独立用户、完整下载或安装：重试、机器人、分段和中止可造成额外请求，浏览器或代理缓存命中不会发服务器请求。请求数据不能补推日志启用前的历史。此接口只有滚动窗口，不能把多次生成的 JSON 相加；原始文件由独立日志轮转控制（最多 30 份归档加当前文件，依赖每日 logrotate 正常执行），不承诺永久累计或完整保留。

## 快照、错误和权限

`publish-download-stats.py` 用 Python 标准库动态加载**同目录**的 `summarize-downloads.py`。先枚举指定完整轮转链（当前文件、`.N`、`.N.gz`），拒绝日志符号链接/非普通文件，以 `O_NOFOLLOW` 打开全部 FD，比较文件名与设备/inode 清单，按各 FD 初始长度复制到 0700 临时目录，复制后再次核对清单。轮转重命名、压缩、清理期间清单变化、短读或最后一行未完成时最多重试三次。新追加记录由下一轮处理，不混入不明确的半行。

快照解压后先完整校验，任何损坏 gzip、坏记录、缺少当前日志或读取失败都视为更新失败。先按解压后的**原文件** SHA-256 去重，再按时间窗口过滤；使用现有 `summarize()` 的分类口径，不维护长期计数。相同原文件可以去重，相同文件内部的重复行保留。没有请求 ID 时，不能可靠去重互相重叠的部分采集，也不能区分恰好完全相同的独立文件；不要混入别的服务器/备份链。配置使用 rename/reopen，不能改成 `copytruncate`。

成功时用同目录临时文件、`fsync` 和 `os.replace` 原子替换 JSON，公开文件 0644。失败则保留经白名单校验的上次计数、窗口及成功时间，只改 `status=error` 和尝试时间；首次失败输出 `totals=null, rows=null, generated_at=null`，绝不以零代替未知。写文件本身失败、服务超时/OOM/脚本不可执行时旧 JSON 不变，需靠前端陈旧提示与服务监控发现。页面取数失败保留浏览器当前已读结果，超过 15 分钟未成功更新提示陈旧；没有成功数据与成功读取零请求分开显示。

服务以 root 读取私有日志，但代码和输出目录都必须 root 所有，网页用户只有 JSON 的读取权限。systemd 将整个文件系统设为只读，只允许写公开输出目录和隔离的临时目录，禁用网络地址族（保留 AF_UNIX）及 home 读取。服务日志只输出固定通用失败消息，不包含异常详情或原始输入。`MemoryMax=256M` / 120 秒超时是保护上限；高流量导致资源限制时应调整容量或架构，不能发布部分结果。

## 安装与验证（由主 Agent 审查后执行）

只操作 www vhost、下列独立脚本/任务与状态目录，不修改其他站点、原始统计口径、DNS 或证书。安装前记录 `current`、其他域名状态和本任务是否已经存在。将下列**已有/缺失状态**及已有文件备份到 root 0700 的时间戳目录，不把备份放到站根目录：

- `/etc/nginx/sites-available/instap.net`
- `/etc/systemd/system/instap-download-stats.service`
- `/etc/systemd/system/instap-download-stats.timer`
- `/usr/local/lib/instap-downloads/publish-download-stats.py`
- `/usr/local/lib/instap-downloads/summarize-downloads.py`
- `/var/lib/instap-downloads/public/summary.json`（如已存在，备份也保持私有）

记录 timer 的 enabled/active 状态。若已有本任务，先停 timer 和 service，再替换两个脚本，避免更新过程中执行新旧混用代码。原始日志必须已按私有统计方案安装和轮转；缺少日志应先检查，不能以创建空文件方式修复历史或伪造零请求。

把已审查版本的以下仓库文件放到服务器受限暂存目录（下例 `/tmp/instap-stats-release` 应由 root 建立且 0700）。目录中的两个 Python 文件来自同一次已推送提交；不可从网页可写目录直接执行 root 脚本。逐步执行并检查每步返回值：

```sh
sudo install -d -o root -g root -m 0755 /usr/local/lib/instap-downloads
sudo install -o root -g root -m 0644 /tmp/instap-stats-release/publish-download-stats.py /usr/local/lib/instap-downloads/publish-download-stats.py
sudo install -o root -g root -m 0644 /tmp/instap-stats-release/summarize-downloads.py /usr/local/lib/instap-downloads/summarize-downloads.py
sudo install -d -o root -g root -m 0755 /var/lib/instap-downloads
sudo install -d -o root -g root -m 0755 /var/lib/instap-downloads/public
sudo install -o root -g root -m 0644 /tmp/instap-stats-release/instap-download-stats.service /etc/systemd/system/instap-download-stats.service
sudo install -o root -g root -m 0644 /tmp/instap-stats-release/instap-download-stats.timer /etc/systemd/system/instap-download-stats.timer
sudo systemd-analyze verify /etc/systemd/system/instap-download-stats.service /etc/systemd/system/instap-download-stats.timer
sudo systemctl daemon-reload
sudo systemctl start instap-download-stats.service
sudo systemctl status instap-download-stats.service --no-pager
sudo python3 -m json.tool /var/lib/instap-downloads/public/summary.json
```

oneshot 成功执行后状态为 inactive/dead 正常，`Result=success` 与退出码 0 才表示此次汇总成功。检查 JSON schema/时间窗口/渠道白名单，不把真实数据粘进仓库。确认所有路径的 root 所有权、脚本依赖无网页写权限；`sudo -u www-data test -r /var/lib/instap-downloads/public/summary.json` 应成功，`test -w` 应失败，`sudo -u www-data test -r /var/log/instap-downloads/downloads.jsonl` 应失败。不要据此修改已有日志权限。

安装前备份 Nginx www 配置，只更新已审查的 `deploy/instap.nginx.conf`；其中 exact 路由是本任务唯一公开文件出口。通过后才 reload：

```sh
sudo install -o root -g root -m 0644 /tmp/instap-stats-release/instap.nginx.conf /etc/nginx/sites-available/instap.net
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable --now instap-download-stats.timer
sudo systemctl list-timers instap-download-stats.timer --no-pager
```

生产验收必须实际执行，不能用本地单元测试代替：

1. 普通公网 HTTPS 读取公开 JSON，确认 `Content-Type: application/json`、`Cache-Control: no-store, no-cache, must-revalidate`、`nosniff`；成功时间在最近一轮内，计数与管理员私有汇总的同一窗口相符。
2. 等待真实 timer 周期后再读，确认 `generated_at` 改变；检查 service 的固定失败消息、timer 下一次计划及每日 logrotate 正常运行。按共享任务规约持续给用户进度，不用一次超过 60 秒的阻塞等待。
3. `/bili-ninja/stats/downloads.jsonl`、`/bili-ninja/stats/downloads.jsonl.1.gz`、`/bili-ninja/stats/summary.json/anything`、`/var/lib/instap-downloads/public/summary.json`、`/public/summary.json` 都应不可读取（404），没有目录列表。日志目录不在站根且不是公开别名；不能只测 JSON URL 就声称原始日志未暴露。
4. 通过**私有临时测试目录**和 `--log-dir` / `--output` 验证坏行、缺文件、轮转、失败保留旧数、首次失败 null；测试输出不能覆盖生产 JSON，不能故意破坏生产日志或把 QA 当作非 QA。
5. 静态 stats 页面部署后实际检查桌面/窄屏、键盘刷新、加载/错误/陈旧/零数据状态及日期渠道表格；确认只有静态 JS 获取本站同源汇总，无额外 SDK/上报。ZIP、hash、其他站点按官网部署规约复验。

本地回归命令：

```sh
python3 -m unittest discover -s tests -p '*download_statistics.py' -v
node --test tests/public-download-stats.test.js
```

## 回退

先停止本任务 timer 和正在运行的 service，再恢复两个 Python 文件、service/timer、www vhost 的备份或按安装前缺失记录移除本次新增文件。执行 `systemctl daemon-reload`；`nginx -t` 通过后 reload。按记录恢复本任务原 enabled/active 状态；如本次首次安装则保持 disabled/stopped。若移除了 service/timer，先 disable timer 再移除文件，避免悬挂 enable 链接。

公开 `summary.json` 可恢复备份，或在已撤掉 exact 路由且任务停用后删除本次新文件；不要删除整个 `/var/lib`、日志目录、历史日志或其他任务状态。网站 `current` 按静态官网 release 回退流程独立切回。保留本次发布点与私有备份，验证公开路由已恢复预期、原始日志仍私有、其他域名及 ZIP 行为不变。不要把仓库代码存在或本地测试通过描述为服务已经启用、CI 通过或线上已验收。
