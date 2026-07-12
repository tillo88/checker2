#!/usr/bin/env python3
from __future__ import annotations
import glob, time, argparse, signal
from spyengine.utils.env import load_env
from spyengine.core.config import load_config
from spyengine.core.engine import SpyEngineApp
from spyengine.ai.ollama_queue import OllamaQueue


class SpyManagerV3:
    def __init__(self, configs_dir="configs", dry_run=False, notification_dry_run=False, no_ai=False):
        self.configs_dir = configs_dir
        self.dry_run = dry_run
        self.notification_dry_run = notification_dry_run
        self.no_ai = no_ai
        self.stop = False
        signal.signal(signal.SIGINT, self._signal)
        signal.signal(signal.SIGTERM, self._signal)

    def _signal(self, *_):
        self.stop = True

    def run(self):
        load_env()
        paths = sorted(glob.glob(f"{self.configs_dir}/spy_config_*.json"))
        queue = OllamaQueue(port=8080)
        queue.start()
        try:
            apps = []
            for p in paths:
                cfg = load_config(p)
                if self.no_ai:
                    cfg.context_check_enabled = False
                    cfg.vision_enabled = False
                apps.append(
                    SpyEngineApp(
                        cfg, queue, dry_run=self.dry_run,
                        notification_dry_run=self.notification_dry_run,
                    )
                )

            while not self.stop:
                for app in apps:
                    app.run_once()
                if not apps:
                    print("Nessuna config trovata")
                    break
                interval = min(app.config.interval_seconds for app in apps)
                for _ in range(interval):
                    if self.stop:
                        break
                    time.sleep(1)
        finally:
            queue.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs-dir", default="configs")
    dry_group = ap.add_mutually_exclusive_group()
    dry_group.add_argument("--dry-run", action="store_true")
    dry_group.add_argument("--notification-dry-run", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()
    SpyManagerV3(args.configs_dir, args.dry_run, args.notification_dry_run, args.no_ai).run()
