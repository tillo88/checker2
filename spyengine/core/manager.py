from __future__ import annotations

import glob
import signal
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spyengine.ai.ollama_queue import OllamaQueue
from spyengine.core.config import load_config
from spyengine.core.engine import SpyEngineApp
from spyengine.services.llama_autostart import LlamaAutoStarter


@dataclass
class ManagerOptions:
    configs_dir: str = "configs"
    dry_run: bool = False
    notification_dry_run: bool = False
    platforms: Optional[list[str]] = None
    no_ai: bool = False
    auto_llama: bool = True
    llama_port: int = 8080
    max_total: Optional[int] = None
    max_items_per_keyword: Optional[int] = None
    skip_details: bool = False
    debug_snapshots: bool = False
    debug_api: bool = False
    stagger_seconds: float = 2.0


class SpyManagerV3:
    """
    Orchestratore multi-spy per il core modulare v3.

    Porta nel nuovo progetto le parti sane del vecchio spy_manager:
    - discovery di più configs
    - auto-start llama-server
    - una OllamaQueue condivisa
    - loop ricorrente per ogni spy
    - shutdown pulito con SIGINT/SIGTERM
    - monitor periodico dello stato thread
    """

    def __init__(self, options: ManagerOptions):
        self.options = options
        self.queue: OllamaQueue | None = None
        self.apps: list[SpyEngineApp] = []
        self.threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._signal_received = False
        self._stats_lock = threading.Lock()
        self._stats: dict[str, dict] = {}

    def _install_signal_handlers(self) -> None:
        def handler(signum, frame):
            if not self._signal_received:
                self._signal_received = True
                print(f"\n[Manager] Segnale {signum} ricevuto, arresto in corso...")
                self.stop()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def discover_configs(self) -> list[Path]:
        root = Path(self.options.configs_dir)
        root.mkdir(parents=True, exist_ok=True)
        configs = sorted(Path(p) for p in glob.glob(str(root / "spy_config_*.json")))

        legacy = Path("spy_config.json")
        if not configs and legacy.exists():
            configs = [legacy]

        return configs

    def _load_configs(self) -> list:
        loaded = []
        for path in self.discover_configs():
            try:
                cfg = load_config(path)

                if self.options.no_ai:
                    cfg.context_check_enabled = False
                    cfg.vision_enabled = False

                if self.options.platforms:
                    cfg.platforms = [p.upper() for p in self.options.platforms]

                if self.options.max_total is not None:
                    cfg.max_total_items = self.options.max_total

                if self.options.max_items_per_keyword is not None:
                    cfg.max_items_per_keyword = self.options.max_items_per_keyword

                cfg.skip_details = bool(self.options.skip_details)
                cfg.debug_snapshots = bool(self.options.debug_snapshots)
                cfg.debug_api = bool(self.options.debug_api)

                loaded.append((path, cfg))
            except Exception as e:
                print(f"[Manager] ❌ Config non valida {path}: {e}")

        return loaded

    def _maybe_start_llama(self, configs: list) -> None:
        ai_needed = any(cfg.context_check_enabled or cfg.vision_enabled for _, cfg in configs)
        if not ai_needed:
            print("[Manager] AI disabilitata nelle config: non avvio llama-server")
            return

        if not self.options.auto_llama:
            print("[Manager] Auto llama disabilitato")
            return

        starter = LlamaAutoStarter.from_env(port=self.options.llama_port)
        ok = starter.ensure_running(wait=True)
        if not ok:
            print("[Manager] ⚠️ llama-server non disponibile: gli spy degraderanno ai filtri classici")

    def start(self) -> None:
        self._install_signal_handlers()

        configs = self._load_configs()
        if not configs:
            print("[Manager] Nessuna configurazione trovata.")
            print("[Manager] Metti file spy_config_*.json dentro configs/")
            return

        print(f"[Manager] {len(configs)} spy trovati:")
        for path, cfg in configs:
            ai = "AI ON" if (cfg.context_check_enabled or cfg.vision_enabled) else "AI OFF"
            print(f"  • {path.name} -> {cfg.name} | {', '.join(cfg.platforms)} | {ai}")

        self._maybe_start_llama(configs)

        self.queue = OllamaQueue(port=self.options.llama_port)
        self.queue.start()

        for idx, (path, cfg) in enumerate(configs):
            try:
                app = SpyEngineApp(
                    config=cfg,
                    ollama_queue=self.queue,
                    dry_run=self.options.dry_run,
                    notification_dry_run=self.options.notification_dry_run,
                )
                self.apps.append(app)

                with self._stats_lock:
                    self._stats[cfg.name] = {
                        "cycles": 0,
                        "last_start": None,
                        "last_end": None,
                        "last_error": None,
                        "last_stats": None,
                    }

                t = threading.Thread(
                    target=self._run_app_loop,
                    args=(app,),
                    name=f"Spy-{cfg.name}",
                    daemon=True,
                )
                t.start()
                self.threads.append(t)

                if idx < len(configs) - 1:
                    time.sleep(max(0.0, self.options.stagger_seconds))

            except Exception as e:
                print(f"[Manager] ❌ Errore avvio {path.name}: {e}")
                traceback.print_exc()

        self._monitor_thread = threading.Thread(target=self._monitor_loop, name="SpyManagerMonitor", daemon=True)
        self._monitor_thread.start()

        print(f"\n[Manager] ✅ {len(self.threads)} spy attivi. Ctrl+C per terminare.\n")

        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        finally:
            self.stop()

    def _run_app_loop(self, app: SpyEngineApp) -> None:
        name = app.config.name

        while not self._stop_event.is_set():
            started = time.strftime("%Y-%m-%d %H:%M:%S")
            with self._stats_lock:
                self._stats[name]["last_start"] = started
                self._stats[name]["last_error"] = None

            try:
                stats = app.run_once()
                with self._stats_lock:
                    self._stats[name]["cycles"] += 1
                    self._stats[name]["last_end"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    self._stats[name]["last_stats"] = stats
            except Exception as e:
                with self._stats_lock:
                    self._stats[name]["last_error"] = str(e)
                    self._stats[name]["last_end"] = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[Manager] ❌ Errore ciclo {name}: {e}")
                traceback.print_exc()

            slept = 0
            interval = max(1, int(app.config.interval_seconds or 300))
            while slept < interval and not self._stop_event.is_set():
                time.sleep(1)
                slept += 1

        try:
            app.browser.stop()
        except Exception:
            pass

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(30)
            if self._stop_event.is_set():
                break

            alive = sum(1 for t in self.threads if t.is_alive())
            queue_size = self.queue.queue_size() if self.queue else 0
            q_stats = self.queue.get_stats() if self.queue else {}

            print(f"\n[Manager Monitor] thread vivi={alive}/{len(self.threads)} | queue={queue_size} | ai_stats={q_stats}")

            with self._stats_lock:
                for name, data in self._stats.items():
                    last = data.get("last_stats") or {}
                    err = data.get("last_error")
                    err_txt = f" | errore={err}" if err else ""
                    print(
                        f"  • {name}: cicli={data.get('cycles')} "
                        f"ultimo={data.get('last_end')} stats={last}{err_txt}"
                    )
            print("")

    def stop(self) -> None:
        if self._stop_event.is_set():
            return

        self._stop_event.set()
        print("[Manager] Arresto spy...")

        for t in self.threads:
            t.join(timeout=5)

        if self.queue:
            try:
                self.queue.stop()
            except Exception as e:
                print(f"[Manager] Errore stop queue: {e}")

        print("[Manager] Stop completato.")
