from __future__ import annotations


class LimitTracker:
    def __init__(self, max_total: int = 0):
        self.max_total = max(0, int(max_total or 0))
        self.count = 0

    def allow(self) -> bool:
        if self.max_total <= 0:
            return True
        return self.count < self.max_total

    def seen(self) -> None:
        self.count += 1
