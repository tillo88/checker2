from __future__ import annotations
import json
from pathlib import Path
from threading import Lock
from datetime import datetime


class JsonStore:
    def __init__(self, path: str | Path, default, *, read_only: bool = False):
        self.path = Path(path)
        self.default = default
        self.read_only = bool(read_only)
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def load(self):
        if not self.path.exists():
            return self.default.copy() if hasattr(self.default, "copy") else self.default
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return self.default.copy() if hasattr(self.default, "copy") else self.default

    def save(self, data) -> None:
        if self.read_only:
            return
        with self._lock:
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class MemoryManager:
    def __init__(self, spy_name: str, max_history: int = 200, data_dir: str = "data", *, read_only: bool = False):
        self.spy_name = spy_name
        self.max_history = max_history
        self.max_seen = max_history * 5
        self.seen_store = JsonStore(Path(data_dir) / "seen" / f"seen_ads_{spy_name}.json", [], read_only=read_only)
        self.history_store = JsonStore(Path(data_dir) / "history" / f"price_history_{spy_name}.json", [], read_only=read_only)
        self.uncertain_store = JsonStore(Path(data_dir) / "uncertain" / f"incerti_{spy_name}.json", [], read_only=read_only)
        self.seen = set(self.seen_store.load())
        self.price_history = self.history_store.load()

    def is_seen(self, listing_id: str) -> bool:
        return listing_id in self.seen

    def mark_seen(self, listing_id: str) -> None:
        self.seen.add(listing_id)
        if len(self.seen) > self.max_seen:
            self.seen = set(list(self.seen)[-self.max_seen:])
        self.seen_store.save(list(self.seen))

    def register_price(self, price: float, config: str) -> None:
        self.price_history.append({"prezzo": float(price), "config": config, "timestamp": datetime.now().isoformat(timespec="seconds")})
        self.price_history = self.price_history[-self.max_history:]
        self.history_store.save(self.price_history)
