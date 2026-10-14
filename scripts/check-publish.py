"""Validate the staged source tree without printing credentials."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
def git(*args):
    return subprocess.check_output(["git", *args], cwd=root)

paths = git("diff", "--cached", "--name-only", "-z").decode("utf-8").split("\0")
paths = [p for p in paths if p]
blocked = [p for p in paths if p in (".env", "config.toml") or p.startswith(("data/", "vault/", "tmp/")) or p.endswith((".pdf", ".db", ".log"))]
secrets = []
envfile = root / ".env"
if envfile.exists():
    for line in envfile.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            if name.strip() in ("DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "ZOTERO_API_KEY", "TELEGRAM_CHAT_ID", "ZOTERO_USER_ID"):
                value = value.strip().strip('"').strip("'")
                if len(value) >= 5:
                    secrets.append(value.encode())
for path in paths:
    content = git("show", ":" + path)
    if any(secret in content for secret in secrets):
        blocked.append(path)
if blocked:
    print("Publish check blocked files: " + ", ".join(set(blocked)))
    sys.exit(1)
print(f"Publish check passed: {len(paths)} staged source files; no private data or configured credentials.")
