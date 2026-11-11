#!/usr/bin/env python3
"""Verify a built or published Instap site using only Python's standard library."""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[1]
PAGES = ('/', '/bili-ninja/', '/bili-ninja/install/', '/bili-ninja/privacy/', '/bili-ninja/changelog/')

class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.ids, self.embeds = [], set(), []
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        for key in ('href', 'src', 'poster'):
            if attrs.get(key):
                self.links.append(attrs[key])
                if key != 'href' or (tag == 'link' and attrs.get('rel') == 'stylesheet'):
                    self.embeds.append(attrs[key])
        if attrs.get('srcset'):
            for item in attrs['srcset'].split(','):
                self.links.append(item.strip().split()[0])
                self.embeds.append(item.strip().split()[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group()
    location.add_argument('--dist', type=Path, default=None)
    location.add_argument('--url', help='HTTPS origin, e.g. https://www.instap.net')
    parser.add_argument('--report', type=Path, help='Write a JSON verification report')
    args = parser.parse_args()
    origin = (args.url or 'https://www.instap.net').rstrip('/')
    if urlsplit(origin).scheme != 'https' or urlsplit(origin).path:
        parser.error('--url must be an HTTPS origin without a path')
    dist = (args.dist or REPO / 'dist').resolve()
    errors, cache, documents = [], {}, {}

    def fetch(path):
        parsed = urlsplit(path)
        clean = unquote(parsed.path)
        if not clean.startswith('/') or '..' in PurePosixPath(clean).parts:
            raise ValueError('unsafe path: ' + path)
        if clean in cache:
            return cache[clean]
        if args.url:
            with urlopen(Request(origin + clean, headers={'User-Agent': 'Instap-release-verifier/1'}), timeout=20) as response:
                if response.status != 200:
                    raise ValueError('HTTP ' + str(response.status))
                final = urlsplit(response.url)
                if final.scheme != 'https' or final.netloc != urlsplit(origin).netloc:
                    raise ValueError('unexpected redirect: ' + response.url)
                content = response.read(64 * 1024 * 1024 + 1)
                if len(content) > 64 * 1024 * 1024:
                    raise ValueError('resource exceeds verification limit')
        else:
            local = dist / clean.lstrip('/')
            if local.is_dir():
                local /= 'index.html'
            if not local.resolve().is_relative_to(dist):
                raise ValueError('resource escapes build directory')
            content = local.read_bytes()
        cache[clean] = content
        return content

    def attempt(path):
        try:
            return fetch(path)
        except Exception as exc:
            errors.append(path + ': ' + str(exc))
            return None

    queue = list(PAGES)
    visited = set()
    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        content = attempt(path)
        if content is None:
            continue
        html = path.endswith('/') or path.endswith('.html')
        if html:
            doc = Document(content.decode('utf-8'))
            documents[path] = doc
            links = doc.links
            for embed in doc.embeds:
                if urlsplit(urljoin(origin + path, embed)).netloc != urlsplit(origin).netloc:
                    errors.append(path + ': external embedded resource ' + embed)
        elif path.endswith('.css'):
            links = re.findall(r'url\(\s*[\'\"]?([^\'\")\s]+)', content.decode('utf-8'))
        else:
            links = []
        for link in links:
            target = urlsplit(urljoin(origin + path, link))
            if target.scheme not in ('http', 'https') or target.netloc != urlsplit(origin).netloc:
                continue
            if target.scheme != 'https':
                errors.append(path + ': insecure internal link ' + link)
            target_path = target.path or '/'
            if target_path not in visited:
                queue.append(target_path)
            if target.fragment and (target_path.endswith('/') or target_path.endswith('.html')):
                body = attempt(target_path)
                if body is not None:
                    target_doc = documents.setdefault(target_path, Document(body.decode('utf-8')))
                    if unquote(target.fragment) not in target_doc.ids:
                        errors.append(path + ': missing fragment ' + link)
    release = None
    try:
        release = json.loads(fetch('/release.json'))
        required = {'version', 'download', 'size', 'sha256'}
        if not required <= release.keys():
            raise ValueError('release.json missing required fields')
        expected_path = f"/downloads/bili-ninja/bili-ninja-{release['version']}.zip"
        if release['download'] != expected_path:
            raise ValueError('download must be a versioned same-origin ZIP path')
        if json.loads(fetch('/downloads/bili-ninja/release.json')) != release:
            raise ValueError('download release metadata differs from root release.json')
        package = fetch(expected_path)
        if len(package) != release['size']:
            raise ValueError('ZIP size differs from release.json')
        if hashlib.sha256(package).hexdigest() != release['sha256']:
            raise ValueError('ZIP SHA-256 differs from release.json')
        with ZipFile(io.BytesIO(package)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise ValueError('ZIP needs unique entries and a root manifest.json')
            expected = {p.relative_to(REPO / 'extension').as_posix(): p for p in (REPO / 'extension').rglob('*') if p.is_file() and not any(part.startswith('.') for part in p.relative_to(REPO / 'extension').parts)}
            if set(names) != set(expected):
                raise ValueError('ZIP files differ from extension-only allowlist')
            for name, source in expected.items():
                if archive.read(name) != source.read_bytes():
                    raise ValueError('ZIP content differs from extension/' + name)
            manifest = json.loads(archive.read('manifest.json'))
            if manifest['version'] != release['version']:
                raise ValueError('ZIP manifest version differs from release.json')
            if archive.testzip():
                raise ValueError('ZIP CRC check failed')
        product = fetch('/bili-ninja/').decode('utf-8')
        for value in (release['version'], release['sha256'], f"{release['size']:,}"):
            if str(value) not in product:
                raise ValueError('product page does not display ' + str(value))
    except Exception as exc:
        errors.append('release: ' + str(exc))
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'mode': 'online' if args.url else 'local', 'target': origin if args.url else str(dist), 'passed': not errors, 'pages': list(PAGES), 'resources_checked': len(cache), 'release': release, 'errors': errors}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
