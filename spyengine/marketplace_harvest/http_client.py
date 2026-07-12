from __future__ import annotations

import random
import time
import urllib.robotparser
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse, urljoin

import requests


DEFAULT_USER_AGENT = (
    "SpyEngineResearchBot/0.1 "
    "(local personal cache; respectful rate-limit; no login/captcha bypass)"
)


@lru_cache(maxsize=256)
def _robot_parser(root: str, user_agent: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(urljoin(root, "/robots.txt"))
    try:
        rp.read()
    except Exception:
        # If robots cannot be fetched, stay conservative at caller level.
        pass
    return rp


@dataclass
class PoliteHttpClient:
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 20.0
    sleep_min: float = 2.0
    sleep_max: float = 6.0
    respect_robots: bool = True
    last_request_at: float = 0.0

    def _sleep(self) -> None:
        now = time.time()
        gap = max(0.0, self.sleep_min - (now - self.last_request_at))
        if gap:
            time.sleep(gap)
        if self.sleep_max > self.sleep_min:
            time.sleep(random.uniform(0.0, self.sleep_max - self.sleep_min))
        self.last_request_at = time.time()

    def allowed_by_robots(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        root = f"{parsed.scheme}://{parsed.netloc}"
        try:
            rp = _robot_parser(root, self.user_agent)
            return bool(rp.can_fetch(self.user_agent, url))
        except Exception:
            return False

    def get(self, url: str) -> requests.Response:
        if not self.allowed_by_robots(url):
            raise PermissionError(f"robots.txt disallow or unavailable: {url}")
        self._sleep()
        return requests.get(
            url,
            timeout=self.timeout,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
            },
        )
