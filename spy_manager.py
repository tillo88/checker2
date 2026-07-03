#!/usr/bin/env python3
"""
Spy Manager v6.3 - Orchestratore multi-spy con llama.cpp server auto-start.
"""
import os
import sys
import time
import threading
import glob
import subprocess
import signal
from datetime import datetime

from ollama_queue import OllamaQueue
from spy_engine import SpyEngine


class SpyManager:
    """Gestisce N spy paralleli con llama.cpp server auto-avvio."""

    LLAMA_MODEL = "./Qwen3.5-14B-A3B-Claude-Opus-Reasoning-Distilled-4.6-MXFP4_MOE.gguf"
    LLAMA_MMPROJ = "./Qwen3.5-35B-A3B-Claude-Opus-Reasoning-Distilled-4.6-mmproj-q8_0.gguf"
    LLAMA_PORT = 8080
    LLAMA_ALIAS = "qwen3.5-14b-spy"
    LLAMA_CTX = 4096

    def __init__(self, configs_dir="configs"):
        self.configs_dir = configs_dir
        self.llama_proc = None
        self.ollama_queue = None
        self.engines = []
        self.threads = []
        self._stop_event = threading.Event()
        self._monitor_thread = None

    def _ensure_llama_running(self):
        """Verifica se llama-server è attivo, altrimenti lo avvia."""
        import requests
        try:
            r = requests.get(f"http://127.0.0.1:{self.LLAMA_PORT}/health", timeout=3)
            if r.status_code == 200:
                print(f"[Manager] llama-server già attivo su porta {self.LLAMA_PORT}")
                return
        except:
            pass

        print(f"[Manager] Avvio llama-server...")
        print(f"  Modello: {self.LLAMA_MODEL}")
        print(f"  mmproj: {self.LLAMA_MMPROJ}")

        # Trova llama-server nel PATH o in directory comuni
        llama_path = self._find_llama_server()
        if not llama_path:
            print("[Manager] ❌ llama-server non trovato!")
            print("[Manager] Cercato in: PATH, ~/llama.cpp/build/bin, /usr/local/bin")
            print("[Manager] Installa llama.cpp o specifica il path completo.")
            sys.exit(1)

        print(f"[Manager] Trovato llama-server: {llama_path}")

        cmd = [
            llama_path,
            "-m", os.path.abspath(self.LLAMA_MODEL),
            "--mmproj", os.path.abspath(self.LLAMA_MMPROJ),
            "-c", str(self.LLAMA_CTX),
            "--host", "127.0.0.1",
            "--port", str(self.LLAMA_PORT),
            "-ngl", "99",
            "--temp", "0.3",
            "--top-p", "0.8"
        ]

        try:
            self.llama_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Leggi output in background per debug
            def read_output():
                for line in self.llama_proc.stdout:
                    print(f"[llama] {line.rstrip()}")

            threading.Thread(target=read_output, daemon=True).start()

            # Attendi che il server sia pronto
            print("[Manager] Attendo che llama-server sia pronto...")
            for i in range(60):
                time.sleep(1)
                if self.llama_proc.poll() is not None:
                    print(f"[Manager] ❌ llama-server è crashato (exit code {self.llama_proc.returncode})")
                    sys.exit(1)
                try:
                    r = requests.get(f"http://127.0.0.1:{self.LLAMA_PORT}/health", timeout=2)
                    if r.status_code == 200:
                        print(f"[Manager] ✅ llama-server pronto!")
                        return
                except:
                    pass
                if i % 10 == 0:
                    print(f"[Manager]   ...attendo da {i}s")

            print("[Manager] ⚠️ llama-server non risponde dopo 60s")
            self._kill_llama()
            sys.exit(1)

        except Exception as e:
            print(f"[Manager] ❌ Errore avvio llama-server: {e}")
            sys.exit(1)

    def _find_llama_server(self):
        """Trova l'eseguibile llama-server."""
        import shutil

        # Cerca nel PATH
        path = shutil.which("llama-server")
        if path:
            return path

        # Directory comuni
        common_paths = [
            os.path.expanduser("~/llama.cpp/build/bin/llama-server"),
            os.path.expanduser("~/llama.cpp/llama-server"),
            "/usr/local/bin/llama-server",
            "/usr/bin/llama-server",
            "./llama-server",
        ]

        for p in common_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p

        return None

    def _kill_llama(self):
        """Termina llama-server se l'abbiamo avviato noi."""
        if self.llama_proc:
            print("[Manager] Arresto llama-server...")
            self.llama_proc.terminate()
            try:
                self.llama_proc.wait(timeout=5)
            except:
                self.llama_proc.kill()
            self.llama_proc = None

    def _ensure_dir(self):
        if not os.path.exists(self.configs_dir):
            os.makedirs(self.configs_dir)

    def discover_configs(self):
        """Trova tutte le configurazioni spy."""
        self._ensure_dir()
        pattern = os.path.join(self.configs_dir, "spy_config_*.json")
        configs = sorted(glob.glob(pattern))

        if not configs and os.path.exists("spy_config.json"):
            print("[Manager] Nessun multi-config trovato, uso spy_config.json legacy")
            configs = ["spy_config.json"]
        return configs

    def start(self):
        """Avvia tutti i componenti."""
        configs = self.discover_configs()
        if not configs:
            print("[Manager] Nessuna configurazione trovata.")
            print("[Manager] Esegui: python configure_spy.py")
            sys.exit(1)

        print(f"[Manager] {len(configs)} spy trovati:")
        for c in configs:
            print(f"  • {os.path.basename(c)}")

        # Avvia llama-server
        self._ensure_llama_running()

        # Avvia coda
        self.ollama_queue = OllamaQueue(
            host="127.0.0.1",
            port=self.LLAMA_PORT,
            model=self.LLAMA_ALIAS,
            min_interval=1.0
        )
        self.ollama_queue.start()

        healthy = self.ollama_queue.is_healthy()
        if not healthy:
            print("[Manager] ⚠️ llama.cpp server non trovato. Verifica che sia avviato.")
            sys.exit(1)
        else:
            print(f"[Manager] llama.cpp connesso | Queue min_interval: 1.0s")

        # Crea e avvia engine
        for cfg_path in configs:
            try:
                engine = SpyEngine(cfg_path, self.ollama_queue)
                self.engines.append(engine)

                t = threading.Thread(
                    target=self._run_engine, 
                    args=(engine,), 
                    name=f"Spy-{engine.name}"
                )
                t.daemon = True
                t.start()
                self.threads.append(t)

                engine.startup_message()
                time.sleep(2)

            except Exception as e:
                print(f"[Manager] ❌ Errore avvio {os.path.basename(cfg_path)}: {e}")

        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        print(f"\n[Manager] ✅ {len(self.engines)} spy attivi. Ctrl+C per terminare.\n")
        print("=" * 60)

        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Manager] 🛑 Stop richiesto da utente...")
            self.stop()

    def _run_engine(self, engine):
        try:
            engine.run_cycle()
        except Exception as e:
            print(f"[{engine.name}] ❌ Errore primo ciclo: {e}")

        while not self._stop_event.is_set():
            for _ in range(engine.interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)
            if self._stop_event.is_set():
                break
            try:
                engine.run_cycle()
            except Exception as e:
                print(f"[{engine.name}] ❌ Errore ciclo: {e}")

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            time.sleep(30)
            if self._stop_event.is_set():
                break
            qsize = self.ollama_queue.queue_size()
            if qsize > 0:
                print(f"[Manager] 📊 llama.cpp queue: {qsize} jobs in attesa")

    def stop(self):
        print("[Manager] Arresto in corso...")
        self._stop_event.set()
        if self.ollama_queue:
            self.ollama_queue.stop()

        for t in self.threads:
            t.join(timeout=10)

        self._kill_llama()

        print(f"[Manager] 👋 Terminato. Spy eseguiti: {len(self.engines)}")
        print("=" * 60)


if __name__ == "__main__":
    manager = SpyManager()
    manager.start()