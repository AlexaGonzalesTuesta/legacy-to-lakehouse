"""Capture site/screenshot.png and site/demo.gif from the built board (run in the Pages workflow).
Needs: pip install playwright pillow && python -m playwright install chromium"""
from __future__ import annotations

import functools
import http.server
import io
import sys
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parent.parent / "site"


def main(chrome: str = "") -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    frames = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome or None)
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".kpis")
        page.screenshot(path=str(SITE / "screenshot.png"))

        def frame() -> None:
            frames.append(Image.open(io.BytesIO(page.screenshot())).convert("P", palette=Image.ADAPTIVE, colors=128))

        frame()
        for tab in ("Nightly loads", "Recall completion", "Pipeline"):
            page.click(f"#nav a:has-text('{tab}')")
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(200)
            frame()
        browser.close()
    httpd.shutdown()
    durations = [1800] + [1300] * (len(frames) - 2) + [2200]
    frames[0].save(SITE / "demo.gif", save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"Wrote screenshot.png and demo.gif ({len(frames)} frames)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
