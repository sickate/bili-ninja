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


def page(path, title, description, content):
    substitutions = values | {'TITLE': escape(title), 'DESCRIPTION': escape(description, quote=True), 'PATH': path, 'CONTENT': content, 'PRODUCT_ACTIVE': 'aria-current="page"' if path == '/bili-ninja/' else ''}
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


page('/', 'Instap — 把具体的需求，做成好用的产品', 'Instap 专注于细分需求，提供软件与硬件的定制设计和开发。认识我们的第一个产品 Bili Ninja。', (SOURCE / 'home.html').read_text())
page('/bili-ninja/', 'Bili Ninja — 把声音留下，把画面带走', '在电脑 Chrome 侧边栏导出 B 站有声 MP4，将同一 BV 多个分 P 音频合并为 M4A。本机处理，开源、无遥测。', (SOURCE / 'product.html').read_text())
install = SOURCE / 'content/install.html'
if not install.is_file():
    raise SystemExit('Missing website/content/install.html')
page('/bili-ninja/install/', '安装指南 — Bili Ninja', '从官网 ZIP 在 Windows 或 macOS 的 Chrome 中手动安装 Bili Ninja，了解首次使用和更新方法。', document('安装指南', '从下载到第一次导出。适用于官网 ZIP 安装，需使用电脑 Chrome 116+。', install.read_text()))
privacy = markdown((ROOT / 'PRIVACY.md').read_text())
privacy += '''<section class="site-privacy" aria-labelledby="site-privacy-title"><span class="eyebrow">官网访问说明 / WEBSITE</span><h2 id="site-privacy-title">关于这个网站</h2><p>以上政策适用于 Bili Ninja 扩展。本网站为静态官网，没有统计脚本、广告 SDK 或账号系统，不使用 Cookie 或本地存储进行来源追踪。</p><p>网站由 Nginx 提供服务；服务器访问日志可能记录 IP 地址、访问时间、请求路径和查询参数、响应状态、User-Agent 及 Referer 等请求信息。请勿在网址参数中填写个人资料。扩展的「无遥测」承诺指扩展本身，不表示官网服务器没有访问日志。</p><p>官网只接受 utm_source、utm_medium、utm_campaign、utm_content、utm_term 五个来源参数；每个值须为 1–80 个英文字母、数字或 . _ ~ - 字符。有效参数会显式附加到站内产品页面与 ZIP 下载链接，不写入扩展包。页面访问和 ZIP 请求只能表示请求，不能代表独立用户数、安装成功或导出成功。</p><p>本站资源和 ZIP 均由本站提供。主动点击 GitHub 链接后，访问适用 GitHub 的隐私政策。如需询问官网日志管理或提出隐私问题，可联系 <a href="mailto:tzhu@instap.net">tzhu@instap.net</a>；扩展问题也可通过 <a href="https://github.com/sickate/bili-ninja/issues">GitHub Issues</a> 反馈。</p></section>'''
page('/bili-ninja/privacy/', '隐私说明 — Bili Ninja', 'Bili Ninja 扩展隐私政策与官网访问日志、下载来源参数说明。', document('隐私说明', '扩展政策正文直接由仓库 PRIVACY.md 生成。网站访问说明另列于页尾。', privacy))
changelog = '''<p class="notice">此页记录当前分发包与已经确认的功能。官网包日期为构建日期，不代表历史版本的首次发布日期。</p><section class="release-entry"><div><div class="release-version">v{{VERSION}}</div><div class="release-facts">当前分发版本<br>官网包：{{BUILD_DATE}}</div></div><div><h2>当前版本</h2><p>在 Chrome 原生侧边栏导出 B 站音视频，提供两种保存方式：</p><ul><li>仅音频：将同一 BV 中兼容的所选分 P 按原顺序合并为 M4A。</li><li>完整视频：每次导出一个分 P 的 H.264 + AAC 有声 MP4。</li><li>支持清晰度选择、进度、取消和本机预览；保留原始音画压缩数据，不重新编码。</li></ul><p><a data-download href="{{DOWNLOAD_URL}}" download>下载 v{{VERSION}} ZIP</a> · {{SIZE}}（{{SIZE_BYTES}} 字节）</p><details class="checksum"><summary>SHA-256</summary><code>{{SHA256}}</code></details></div></section><section><h2>v1.2 系列更新提示</h2><p>引入 Chrome 侧边栏以及 Bilibili 站点访问权限，用于自动识别视频标签页、更新图标和加载侧栏中的视频信息。更新时如 Chrome 提示接受新权限，请先查看说明，确认继续使用后接受。</p><p>官网 ZIP 需要手动更新：用新版文件替换原安装目录中的文件，再到 <code>chrome://extensions</code> 重新加载扩展。<a href="/bili-ninja/install/">查看完整更新步骤</a>。</p><p>更详细的实现与提交记录见 <a href="https://github.com/sickate/bili-ninja">GitHub 仓库</a>。</p></section>'''
page('/bili-ninja/changelog/', '版本记录 — Bili Ninja', 'Bili Ninja 当前分发版本、包信息和手动更新提示。', document('版本记录', '当前版本、下载校验与更新提示。', changelog))
(OUT / 'robots.txt').write_text('User-agent: *\nAllow: /\nSitemap: https://www.instap.net/sitemap.xml\n')
(OUT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>https://www.instap.net{p}</loc></url>' for p in ('/', '/bili-ninja/', '/bili-ninja/install/', '/bili-ninja/privacy/', '/bili-ninja/changelog/')) + '</urlset>\n')
print(f'Built dist/: v{version}, {len(blob)} bytes, SHA-256 {release["sha256"]}, {released} UTC')
