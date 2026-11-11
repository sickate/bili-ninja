#!/usr/bin/env python3
"""Stage verified static files, then explicitly activate or roll back a release.

This tool never changes DNS, Nginx, certificates, other applications or services.
The site root must already exist and be owned by the SSH deployment account.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile

REPO = Path(__file__).resolve().parents[1]
REMOTE = r'''
import hashlib, io, json, os
from pathlib import Path, PurePosixPath
import sys, tarfile, time, uuid
request = json.loads(sys.argv[1])
root = Path(request['root'])
if not root.is_absolute() or '..' in root.parts or 'instap' not in root.name.lower() or root.is_symlink() or not root.is_dir():
    raise SystemExit('Site root must be an existing real directory dedicated to Instap')
action = request['action']
if action != 'status':
    import fcntl
    lock = (root / '.deployment.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX)
releases = root / 'releases'
current = root / 'current'
if current.exists() and not current.is_symlink():
    raise SystemExit('Refusing to replace a real current directory')
previous = os.readlink(current) if current.is_symlink() else None
if previous and (not previous.startswith('releases/') or len(PurePosixPath(previous).parts) != 2):
    raise SystemExit('Current symlink points outside the release layout')
if action == 'status':
    print(json.dumps({'current': previous, 'releases': sorted(p.name for p in releases.iterdir() if p.is_dir()) if releases.exists() else []}))
    raise SystemExit(0)
release = request['release']
if not release or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in release):
    raise SystemExit('Invalid release ID')
releases.mkdir(exist_ok=True)
if releases.is_symlink():
    raise SystemExit('Releases directory must not be a symlink')
target = releases / release
if action == 'stage':
    if target.exists():
        raise SystemExit('Release already exists; never overwrite immutable releases')
    payload = sys.stdin.buffer.read(128 * 1024 * 1024 + 1)
    if len(payload) > 128 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != request['archive_sha256']:
        raise SystemExit('Upload hash or size validation failed')
    stage = releases / ('.incoming-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o755)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
            members = archive.getmembers()
            seen = set()
            for entry in members:
                path = PurePosixPath(entry.name)
                if not entry.isfile() or path.is_absolute() or '..' in path.parts or any(p.startswith('.') for p in path.parts) or entry.name in seen:
                    raise ValueError('Unsafe archive entry')
                seen.add(entry.name)
            for entry in members:
                destination = stage / entry.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.extractfile(entry).read())
                destination.chmod(0o644)
        manifest = json.loads((stage / 'deployment-manifest.json').read_text())
        actual = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()} - {'deployment-manifest.json'}
        if actual != set(manifest['files']):
            raise ValueError('Uploaded file list differs from manifest')
        for name, expected in manifest['files'].items():
            if hashlib.sha256((stage / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Uploaded content hash mismatch')
        for directory in stage.rglob('*'):
            if directory.is_dir(): directory.chmod(0o755)
        stage.rename(target)
    except BaseException:
        import shutil
        shutil.rmtree(stage)
        raise
    print(json.dumps({'staged': release, 'current': previous, 'revision': manifest['revision'], 'files': len(actual)}))
elif action in ('activate', 'rollback'):
    if target.is_symlink() or not target.is_dir() or not (target / 'deployment-manifest.json').is_file():
        raise SystemExit('Target is not a staged release')
    manifest = json.loads((target / 'deployment-manifest.json').read_text())
    entries = list(target.rglob('*'))
    actual = {p.relative_to(target).as_posix() for p in entries if p.is_file()} - {'deployment-manifest.json'}
    if any(p.is_symlink() for p in entries) or actual != set(manifest['files']):
        raise SystemExit('Staged release file list mismatch; refusing activation')
    for name, expected in manifest['files'].items():
        if hashlib.sha256((target / name).read_bytes()).hexdigest() != expected:
            raise SystemExit('Staged release hash mismatch; refusing activation')
    link = root / ('.current-' + uuid.uuid4().hex)
    link.symlink_to('releases/' + release)
    os.replace(link, current)
    event = {'time': int(time.time()), 'action': action, 'previous': previous, 'current': 'releases/' + release, 'revision': manifest['revision']}
    with (root / 'deployment-events.jsonl').open('a') as log: log.write(json.dumps(event) + '\n')
    print(json.dumps(event))
else:
    raise SystemExit('Unknown action')
'''


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'stage', 'activate', 'rollback'))
    parser.add_argument('--host', required=True, help='Explicit SSH destination; uses normal SSH authentication')
    parser.add_argument('--root', required=True, help='Existing Instap-only absolute directory, e.g. /var/www/instap.net')
    parser.add_argument('--release', help='Required existing release ID for activate/rollback; optional for stage')
    parser.add_argument('--dist', type=Path, default=REPO / 'dist')
    parser.add_argument('--remote-ref', default='origin/main', help='Already fetched published Git ref required by stage')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@:-]*', args.host):
        parser.error('invalid SSH host')
    root = Path(args.root)
    if not root.is_absolute() or '..' in root.parts or 'instap' not in root.name.lower():
        parser.error('--root must be a dedicated Instap directory')
    if args.action in ('activate', 'rollback') and not args.release:
        parser.error('--release is required for activate/rollback')
    request = {'action': args.action, 'root': args.root, 'release': args.release}
    payload = None
    if args.action == 'stage':
        if git('status', '--porcelain'):
            parser.error('commit and push the clean working tree before staging')
        revision = git('rev-parse', 'HEAD')
        subprocess.run(['git', 'merge-base', '--is-ancestor', revision, args.remote_ref], cwd=REPO, check=True)
        subprocess.run([sys.executable, str(REPO / 'scripts/verify-website.py'), '--dist', str(args.dist)], check=True)
        release = args.release or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + revision[:12]
        request['release'] = release
        dist = args.dist.resolve()
        files = {}
        for path in sorted(dist.rglob('*')):
            if path.is_symlink():
                parser.error('build must not contain symlinks')
            if path.is_file():
                name = path.relative_to(dist).as_posix()
                if any(part.startswith('.') for part in Path(name).parts) or name == 'deployment-manifest.json':
                    parser.error('build contains a hidden/reserved file')
                files[name] = path.read_bytes()
        manifest = {'revision': revision, 'release': release, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        files['deployment-manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                archive.addfile(info, io.BytesIO(data))
        payload = buffer.getvalue()
        request['archive_sha256'] = hashlib.sha256(payload).hexdigest()
    if request.get('release') and not re.fullmatch(r'[A-Za-z0-9_-]+', request['release']):
        parser.error('release ID may contain letters, numbers, underscore and hyphen')
    command = 'python3 -c ' + shlex.quote(REMOTE) + ' ' + shlex.quote(json.dumps(request))
    subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', args.host, command], input=payload, check=True)

if __name__ == '__main__':
    main()
