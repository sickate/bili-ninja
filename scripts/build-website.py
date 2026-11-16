# -*- coding: utf-8 -*-
"""Build Instap's dependency-free static website from verified extension assets."""
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import shutil
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'website'
OUT = ROOT / 'dist'
ISSUES = 'https://github.com/sickate/bili-ninja/issues'


def inline_markdown(text):
    """Render the small, explicit Markdown subset used by the privacy policy."""
    text = escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    return re.sub(r'\[([^]]+)\]\((https://[^\s)]+)\)', r'<a href="\2">\1</a>', text)


def markdown(text):
    blocks = []
    paragraph = []
    in_list = False

    def flush():
        if paragraph:
            blocks.append('<p>' + inline_markdown(' '.join(paragraph)) + '</p>')
            paragraph.clear()

    for line in text.splitlines():
        if line.startswith('# '):
            flush()  # The policy title is already the page's h1.
            continue
        if line.startswith('## '):
            flush()
            if in_list:
                blocks.append('</ul>')
                in_list = False
            blocks.append('<h2>' + inline_markdown(line[3:]) + '</h2>')
        elif line.startswith('- '):
            flush()
            if not in_list:
                blocks.append('<ul>')
                in_list = True
            blocks.append('<li>' + inline_markdown(line[2:]) + '</li>')
        elif not line.strip():
            flush()
            if in_list:
                blocks.append('</ul>')
                in_list = False
        else:
            paragraph.append(line)
    flush()
    if in_list:
        blocks.append('</ul>')
    return '\n'.join(blocks)


archive_path = ROOT / 'bili-ninja.zip'
if not archive_path.is_file():
    raise SystemExit('Missing bili-ninja.zip. Run npm run package first.')
manifest = json.loads((ROOT / 'extension/manifest.json').read_text())
package = json.loads((ROOT / 'package.json').read_text())
with ZipFile(archive_path) as archive:
    packed_manifest = json.loads(archive.read('manifest.json'))
    if packed_manifest != manifest:
        raise SystemExit('ZIP manifest differs from extension/manifest.json; run npm run package.')
    expected = {p.relative_to(ROOT / 'extension').as_posix(): p for p in (ROOT / 'extension').rglob('*') if p.is_file() and not any(part.startswith('.') for part in p.relative_to(ROOT / 'extension').parts)}
    if len(archive.namelist()) != len(set(archive.namelist())):
        raise SystemExit('ZIP contains duplicate entries; run npm run package.')
    if set(archive.namelist()) != set(expected):
        raise SystemExit('ZIP file list differs from extension assets; run npm run package.')
    for name, path in expected.items():
        if archive.read(name) != path.read_bytes():
            raise SystemExit(f'ZIP asset differs: {name}; run npm run package.')
version = manifest['version']
if package['version'] != version or not re.fullmatch(r'\d+(?:\.\d+){1,3}', version):
    raise SystemExit('Package and manifest versions must match and use numeric dot notation.')
blob = archive_path.read_bytes()
released = datetime.now(timezone.utc).date().isoformat()
filename = f'bili-ninja-{version}.zip'
download = f'/downloads/bili-ninja/{filename}'
release = {'version': version, 'filename': filename, 'download': download, 'size': len(blob), 'sha256': sha256(blob).hexdigest(), 'released': released}
values = {'VERSION': version, 'DOWNLOAD_URL': download, 'SIZE': f'{len(blob) / 1024:.1f} KB', 'SIZE_BYTES': f'{len(blob):,}', 'BUILD_DATE': released, 'SHA256': release['sha256'], 'YEAR': released[:4]}
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir()
shutil.copytree(SOURCE / 'assets', OUT / 'assets')
(OUT / 'downloads/bili-ninja').mkdir(parents=True)
(OUT / download.lstrip('/')).write_bytes(blob)
for path in (OUT / 'release.json', OUT / 'downloads/bili-ninja/release.json'):
    path.write_text(json.dumps(release, ensure_ascii=False, indent=2) + '\n')


def page(path, title, description, content, extra_head=""):
    social_image = "https://www.instap.net/assets/screenshots/bili-ninja-video-quality-20261115.png"
    social = (f'<meta property="og:type" content="website">\n<meta property="og:locale" content="zh_CN">\n<meta property="og:site_name" content="Instap">\n'
              f'<meta property="og:title" content="{escape(title, quote=True)}">\n<meta property="og:description" content="{escape(description, quote=True)}">\n'
              f'<meta property="og:url" content="https://www.instap.net{path}">\n')
    if path == "/bili-ninja/":
        social += (f'<meta property="og:image" content="{social_image}">\n<meta property="og:image:width" content="2494">\n<meta property="og:image:height" content="1534">\n<meta property="og:image:alt" content="Bili Ninja 在 B 站视频页的实际界面">\n'
                   f'<meta name="twitter:card" content="summary_large_image">\n<meta name="twitter:title" content="{escape(title, quote=True)}">\n<meta name="twitter:description" content="{escape(description, quote=True)}">\n<meta name="twitter:image" content="{social_image}">\n')
    substitutions = values | {'TITLE': escape(title), 'DESCRIPTION': escape(description, quote=True), 'PATH': path, 'CONTENT': content, 'EXTRA_HEAD': social + extra_head, 'PRODUCT_ACTIVE': 'aria-current="page"' if path == '/bili-ninja/' else ''}
    result = (SOURCE / 'template.html').read_text()
    for key in ('CONTENT', *[key for key in substitutions if key != 'CONTENT']):
        result = result.replace('{{' + key + '}}', substitutions[key])
    if re.search(r'\{\{[A-Z_]+\}\}', result):
        raise SystemExit(f'Unresolved template variable in {path}')
    destination = OUT / path.lstrip('/') / 'index.html'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(result)


def document(title, subtitle, body):
    return f'<main id="main"><div class="wrap page-heading"><div class="breadcrumbs"><a href="/">Instap</a> / <a href="/bili-ninja/">Bili Ninja</a> / {title}</div><span class="eyebrow">BILI NINJA / DOCUMENTATION</span><h1>{title}</h1><p>{subtitle}</p></div><article class="document-layout prose">{body}</article></main>'


page('/', 'Instap — 软件与硬件定制开发', 'Instap 提供软件和硬件的定制设计与开发服务，包括需求梳理、原型设计与产品开发。了解 Bili Ninja 音视频工具及项目合作方式。', (SOURCE / 'home.html').read_text())
product = ((SOURCE / 'product.html').read_text()
           .replace('{{WEB_DOWNLOAD}}', (SOURCE / 'content/web-download.html').read_text())
           .replace('{{SHARE}}', (SOURCE / 'content/share.html').read_text()))
page('/bili-ninja/', 'Bili Ninja — B 站视频下载与音频提取', '粘贴 B 站视频链接，免插件生成 MP4 视频或 M4A 音频下载链接。另提供 Chrome 侧边栏插件，支持本机处理与多 P 音频合并。', product, '<link rel="stylesheet" href="/assets/share.css">\n<link rel="stylesheet" href="/assets/web-download.css">\n<script defer src="/assets/vendor/qrcodegen.js"></script>\n<script defer src="/assets/share.js"></script>\n<script defer src="/assets/web-download.js"></script>')
page('/bili-ninja/stats/', '下载请求统计 — Bili Ninja', '查看官网插件包近30天的下载请求和渠道汇总，测试流量单独列出。', (SOURCE / 'content/stats.html').read_text(), '<link rel="stylesheet" href="/assets/stats.css">\n<script defer src="/assets/stats.js"></script>')
install = SOURCE / 'content/install.html'
if not install.is_file():
    raise SystemExit('Missing website/content/install.html')
page('/bili-ninja/install/', '安装指南 — Bili Ninja', '从官网 ZIP 在 Windows 或 macOS 的 Chrome 中手动安装 Bili Ninja，了解首次使用和更新方法。', document('安装指南', '从下载到第一次导出。适用于官网 ZIP 安装，需使用电脑 Chrome 116+。', install.read_text()))
privacy = markdown((ROOT / 'PRIVACY.md').read_text())
privacy += '''<section class="site-privacy" aria-labelledby="site-privacy-title"><span class="eyebrow">官网访问说明 / WEBSITE</span><h2 id="site-privacy-title">关于这个网站</h2><p>以上政策适用于 Bili Ninja 扩展。本网站提供产品资料及免插件网页下载，没有访客行为上报脚本、广告 SDK 或账号系统，不使用 Cookie 或本地存储进行来源追踪。</p>
<h3>免插件网页下载</h3><p>主动提交视频链接后，本站服务器会接收该 URL、所选格式及请求 IP，向 Bilibili 请求匿名公开可播放的单个分 P，并临时下载、处理成 MP4 或 M4A 文件。此功能与扩展的本机处理方式不同，不需要也不接收你的 B 站登录凭据。所能获取的清晰度以匿名接口实际返回为准，不绕过付费、登录或试看权限。</p>
<p>任务信息仅保存在服务内存中；成功文件和临时下载令牌在生成后 15 分钟过期并清理，失败文件随任务结束清理，服务重启也会清理缓存。下载链接具有随机令牌，任何持有链接的人在有效期内均可下载，请勿公开分享私密文件链接。视频 URL 通过 POST 正文提交，API 不记录请求正文、原始 URL、上游媒体签名或访问路径中的令牌；为限制滥用，仅在内存中短期维护按 IP 的请求频率。服务错误日志只含安全错误分类。Bilibili 会收到本站服务器的内容请求。请仅处理你有权保存的内容。</p>
<p>网站由 Nginx 提供服务；服务器访问日志可能记录 IP 地址、访问时间、请求路径和查询参数、响应状态、User-Agent 及 Referer 等请求信息。请勿在网址参数中填写个人资料。扩展的「无遥测」承诺指扩展本身，不表示官网服务器没有访问日志。</p>
<p>官网只接受 utm_source、utm_medium、utm_campaign、utm_content、utm_term 五个来源参数；每个值须为 1–80 个英文字母、数字或 . _ ~ - 字符。有效参数会显式附加到站内产品页面与 ZIP 下载链接，不写入扩展包。为评估推广效果，服务器会另行汇总 ZIP 下载请求的时间、版本、响应状态、请求方式、响应字节数，以及有效的来源、媒介、活动和内容标识；此专用统计日志不记录 IP、User-Agent、Referer 或完整查询参数，原始日志按日轮转并保留至多 30 份归档。测试来源单独列出。官网公开最近30个北京时间自然日内、统计启用后的下载请求汇总，只展示日期、固定渠道分类与计数，不公开原始日志或任意推广参数。维护者仍可查看受限的详细汇总。页面访问和 ZIP 请求只能表示请求，不能代表独立用户数、完整下载、安装成功或导出成功；浏览器缓存命中的下载可能不会请求服务器，因此不会计入。</p>
<p>本站资源和 ZIP 均由本站提供。分享功能在浏览器中生成可编辑文案、带固定渠道标记的产品链接和二维码，不自动发布、不接入社交账号，也不向第三方发送媒体或二维码请求。点击 X 或微博编辑页后，会将当前文案与产品链接传给相应平台；使用系统分享时，内容交由你选择的应用处理。实际发布由你确认。主动点击第三方链接后，访问适用相应平台的隐私政策。如需询问官网日志管理或提出隐私问题，可联系 <a href="mailto:tzhu@instap.net">tzhu@instap.net</a>；扩展问题也可通过 <a href="https://github.com/sickate/bili-ninja/issues">GitHub Issues</a> 反馈。</p></section>'''
page('/bili-ninja/privacy/', '隐私说明 — Bili Ninja', 'Bili Ninja 扩展隐私政策与官网访问日志、下载来源参数说明。', document('隐私说明', '扩展政策正文直接由仓库 PRIVACY.md 生成。网站访问说明另列于页尾。', privacy))
changelog = '''<p class="notice">此页记录当前分发包与已经确认的功能。官网包日期为构建日期，不代表历史版本的首次发布日期。</p><section class="release-entry"><div><div class="release-version">v{{VERSION}}</div><div class="release-facts">当前分发版本<br>官网包：{{BUILD_DATE}}</div></div><div><h2>当前版本</h2><p>在 Chrome 原生侧边栏导出 B 站音视频，提供两种保存方式：</p><ul><li>仅音频：将同一 BV 中兼容的所选分 P 按原顺序合并为 M4A。</li><li>完整视频：每次导出一个分 P 的 H.264 + AAC 有声 MP4。</li><li>支持清晰度选择、进度、取消和本机预览；保留原始音画压缩数据，不重新编码。</li></ul><p><a data-download href="{{DOWNLOAD_URL}}" download>下载 v{{VERSION}} ZIP</a> · {{SIZE}}（{{SIZE_BYTES}} 字节）</p><details class="checksum"><summary>SHA-256</summary><code>{{SHA256}}</code></details></div></section><section><h2>v1.2 系列更新提示</h2><p>引入 Chrome 侧边栏以及 Bilibili 站点访问权限，用于自动识别视频标签页、更新图标和加载侧栏中的视频信息。更新时如 Chrome 提示接受新权限，请先查看说明，确认继续使用后接受。</p>
<p>官网 ZIP 需要手动更新：用新版文件替换原安装目录中的文件，再到 <code>chrome://extensions</code> 重新加载扩展。<a href="/bili-ninja/install/">查看完整更新步骤</a>。</p>
<p>更详细的实现与提交记录见 <a href="https://github.com/sickate/bili-ninja">GitHub 仓库</a>。</p></section>'''
page('/bili-ninja/changelog/', '版本记录 — Bili Ninja', 'Bili Ninja 当前分发版本、包信息和手动更新提示。', document('版本记录', '当前版本、下载校验与更新提示。', changelog))
(OUT / 'robots.txt').write_text('User-agent: *\nAllow: /\nSitemap: https://www.instap.net/sitemap.xml\n')
(OUT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>https://www.instap.net{p}</loc></url>' for p in ('/', '/bili-ninja/', '/bili-ninja/install/', '/bili-ninja/privacy/', '/bili-ninja/changelog/', '/bili-ninja/stats/')) + '</urlset>\n')
print(f'Built dist/: v{version}, {len(blob)} bytes, SHA-256 {release["sha256"]}, {released} UTC')
