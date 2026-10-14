"""Validate the staged source tree without printing credentials."""
from pathlib import Path
import subprocess
import sys
import argparse

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from pris.privacy import is_sensitive_name
parser = argparse.ArgumentParser()
parser.add_argument('--all', action='store_true')
parser.add_argument('--history', action='store_true')
args = parser.parse_args()
def git(*args):
    return subprocess.check_output(["git", *args], cwd=root)

paths = (git("ls-files", "-z") if args.all else git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")).decode("utf-8").split("\0")
paths = [p for p in paths if p]
def private_path(path):
    name = Path(path).name.lower()
    return (name == 'config.toml' or (name.startswith('.env') and name != '.env.example')
            or any(p in {'data', 'vault', 'tmp', 'node_modules'} for p in Path(path).parts)
            or name.endswith(('.pdf', '.db', '.sqlite', '.sqlite3', '.log', '.pem', '.key')))
blocked = [p for p in paths if private_path(p)]
secrets = []
envfile = root / ".env"
if envfile.exists():
    for line in envfile.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            if is_sensitive_name(name.strip()):
                value = value.strip().strip('"').strip("'")
                if len(value) >= 5:
                    secrets.append(value.encode())
try:
    from pris.config import load_settings
    from pris.connections import SECRET_NAMES
    settings = load_settings(root)
    secrets.extend(settings.secret(name).encode() for name in SECRET_NAMES if len(settings.secret(name)) >= 5)
except Exception:
    print('Publish check blocked: cannot safely inspect the local credential store.')
    sys.exit(1)
for path in paths:
    content = git("show", ":" + path)
    if any(secret in content for secret in secrets):
        blocked.append(path)
history_count = 0
if args.history:
    for commit in git('rev-list', '--all').decode().splitlines():
        blocked.extend(p for p in git('ls-tree', '-r', '--name-only', '-z', commit).decode('utf-8').split('\0') if p and private_path(p))
    objects = git('rev-list', '--objects', '--all').splitlines()
    proc = subprocess.run(['git', 'cat-file', '--batch'], cwd=root,
                          input=b'\n'.join(line.split(b' ', 1)[0] for line in objects)+b'\n',
                          stdout=subprocess.PIPE, check=True)
    stream = proc.stdout
    pos = 0
    for _ in objects:
        end = stream.index(b'\n', pos)
        header = stream[pos:end].split()
        size = int(header[2])
        content = stream[end+1:end+1+size]
        if header[1] == b'blob':
            history_count += 1
            if any(secret in content for secret in secrets):
                blocked.append('[historical blob containing a configured credential]')
        pos = end + 1 + size + 1
if blocked:
    print("Publish check blocked files: " + ", ".join(set(blocked)))
    sys.exit(1)
print(f"Publish check passed: {len(paths)} source files, {history_count} history blobs; no private files or configured credentials found.")
