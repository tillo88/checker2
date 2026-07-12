from __future__ import annotations

import os
import requests


class TelegramNotifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None, dry_run: bool = False, logger=None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
        self.dry_run = dry_run
        self.logger = logger

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, message: str) -> bool:
        if self.dry_run:
            print("[DRY-RUN TELEGRAM]")
            print(message)
            return True

        if not self.token or not self.chat_id:
            if self.logger:
                self.logger.warning("Telegram non configurato: TELEGRAM_TOKEN o TELEGRAM_CHAT_ID mancanti")
            return False

        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if r.status_code != 200:
                if self.logger:
                    self.logger.warning(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
                return False
            return True
        except requests.RequestException as e:
            if self.logger:
                self.logger.warning(f"Telegram errore rete: {e}")
            return False
