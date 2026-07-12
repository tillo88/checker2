from __future__ import annotations

import random
import re
import threading
import time

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


class BrowserManager:
    def __init__(self, logger=None, headless: bool = True):
        self.logger = logger
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self._browser:
                return True
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )
                if self.logger:
                    self.logger.info("🌐", "Browser Playwright avviato")
                return True
            except ImportError:
                if self.logger:
                    self.logger.error("Playwright non installato. Esegui: pip install playwright && playwright install chromium")
                return False
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Errore avvio browser: {e}")
                return False

    def stop(self) -> None:
        with self._lock:
            had_browser = bool(self._browser or self._playwright)
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            if had_browser and self.logger:
                self.logger.info("🌐", "Browser Playwright chiuso")

    def new_context(self):
        if not self._browser and not self.start():
            return None
        context = self._browser.new_context(
            user_agent=get_random_user_agent(),
            locale="it-IT",
            timezone_id=random.choice(["Europe/Rome", "Europe/Berlin", "Europe/Paris", "Europe/Madrid"]),
            viewport={
                "width": random.choice([1920, 1680, 1440, 1366]),
                "height": random.choice([1080, 900, 768]),
            },
            extra_http_headers={
                "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
                "DNT": "1",
            },
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['it-IT', 'it', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        return context

    @staticmethod
    def safe_goto(page, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded", logger=None) -> bool:
        """
        Navigazione robusta usata da Vinted/Wallapop:
        - primo tentativo normale
        - fallback più permissivo con wait_until='commit'
        - ritorna False invece di far esplodere la piattaforma
        """
        try:
            page.goto(url, timeout=timeout, wait_until=wait_until)
            return True
        except Exception as e:
            if logger:
                try:
                    logger.warning(f"goto non completato: {str(e)[:180]}")
                except Exception:
                    pass

        try:
            page.goto(url, timeout=max(5000, min(10000, int(timeout / 2))), wait_until="commit")
            return False
        except Exception as e:
            if logger:
                try:
                    logger.warning(f"goto fallback fallito: {str(e)[:180]}")
                except Exception:
                    pass
            return False

    @staticmethod
    def block_heavy_resources(page, allow_images: bool = False) -> None:
        blocked = ["stylesheet", "font", "media"]
        if not allow_images:
            blocked.append("image")

        def handler(route):
            try:
                if route.request.resource_type in blocked:
                    route.abort()
                else:
                    route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass

        try:
            page.route("**/*", handler)
        except Exception:
            pass

    @staticmethod
    def human_delay(min_s: float = 0.5, max_s: float = 2.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    @staticmethod
    def dismiss_cookie_banner(page, logger=None) -> None:
        labels = [
            "Accetta tutto",
            "Rifiuta tutto",
            "Accetta",
            "Accetto",
            "Accept all",
            "Reject all",
            "OK",
        ]

        for label in labels:
            try:
                page.get_by_role("button", name=re.compile(label, re.I)).click(timeout=1500)
                if logger:
                    logger.think(f"🍪 Cookie banner chiuso: {label}")
                return
            except Exception:
                pass

        selectors = [
            "button:has-text('Accetta tutto')",
            "button:has-text('Rifiuta tutto')",
            "button:has-text('Accetta')",
            "button:has-text('Accetto')",
            "button:has-text('OK')",
            "[id*='cookie'] button",
            "[class*='cookie'] button",
            "[id*='cmp'] button",
            "[class*='cmp'] button",
            "[data-testid='cookie-banner-accept']",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible(timeout=1000):
                    btn.click(timeout=2000)
                    if logger:
                        logger.think("🍪 Cookie banner chiuso")
                    return
            except Exception:
                continue

        try:
            clicked = page.evaluate(
                """(labels) => {
                    const lower = labels.map(x => x.toLowerCase());
                    for (const el of Array.from(document.querySelectorAll('button, [role="button"]'))) {
                        const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if (lower.some(l => txt.includes(l))) {
                            el.click();
                            return txt;
                        }
                    }
                    return '';
                }""",
                labels,
            )
            if clicked and logger:
                logger.think(f"🍪 Cookie banner chiuso via JS: {clicked}")
        except Exception:
            pass
