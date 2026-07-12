from __future__ import annotations
from datetime import datetime
from pathlib import Path
from threading import Lock


class SpyLogger:
    VERBOSE_BRIEF = 0
    VERBOSE_NORMAL = 1
    VERBOSE_CHATTY = 2

    def __init__(self, name: str, log_dir: str = "data/logs", verbose: int = VERBOSE_CHATTY):
        self.name = name
        self.verbose = verbose
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"spy_{name}.log"
        self._lock = Lock()

    def _write(self, emoji: str, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        indent = "   " if level == "DETAIL" else ""
        line = f"[{timestamp}] {indent}{emoji}  {message}"
        print(line)
        with self._lock:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def info(self, emoji: str, message: str) -> None:
        self._write(emoji, message)

    def action(self, message: str) -> None:
        self._write("🎯", message)

    def think(self, message: str) -> None:
        if self.verbose >= self.VERBOSE_CHATTY:
            self._write("💭", message, "DETAIL")

    def decide(self, decision: str, reason: str = "") -> None:
        if self.verbose < self.VERBOSE_NORMAL:
            return
        emoji = "✅" if ("ACCETTO" in decision or "NOTIFICO" in decision) else "❌" if ("RIFIUTO" in decision or "SKIP" in decision) else "⚠️"
        self._write(emoji, decision if not reason else f"{decision} -> {reason}")

    def warning(self, message: str) -> None:
        self._write("⚠️", message, "WARN")

    def error(self, message: str) -> None:
        self._write("🔥", message, "ERROR")
