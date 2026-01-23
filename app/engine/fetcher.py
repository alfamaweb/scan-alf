from __future__ import annotations
from playwright.async_api import async_playwright


class PlaywrightFetcher:
    def __init__(self, timeout_ms: int = 20000):
        self.timeout_ms = timeout_ms

    async def fetch_html(self, url: str) -> tuple[int, str]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            status = resp.status if resp else 0
            html = await page.content()
            await browser.close()
            return status, html
