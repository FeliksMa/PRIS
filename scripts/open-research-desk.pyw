"""Start the local desk if needed and open it in the default browser."""
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

root = Path(__file__).resolve().parent.parent
url = "http://127.0.0.1:8765"

def ready():
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200 and b"Research Desk" in response.read(500)
    except Exception:
        return False

if not ready():
    (root / "data").mkdir(exist_ok=True)
    with (root / "data" / "desktop.log").open("ab") as log:
        subprocess.Popen([sys.executable, "-m", "pris.app", "--root", str(root), "ui"], cwd=root,
                         stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(30):
        if ready():
            break
        time.sleep(.3)
webbrowser.open(url)
