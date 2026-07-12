from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from typing import Optional


DEFAULT_MODEL = "./Qwen3.5-14B-A3B-Claude-Opus-Reasoning-Distilled-4.6-MXFP4_MOE.gguf"
DEFAULT_MMPROJ = "./Qwen3.5-35B-A3B-Claude-Opus-Reasoning-Distilled-4.6-mmproj-q8_0.gguf"


def _env_str(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def _env_int(name: str, default: int | None = None) -> int | None:
    value = _env_str(name)
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _env_float(name: str, default: float | None = None) -> float | None:
    value = _env_str(name)
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def _path_exists_or_empty(value: str | None) -> bool:
    if not value:
        return True
    if value.startswith("http://") or value.startswith("https://"):
        return True
    return Path(value).exists()



def resolve_llama_server_bin(value: str | None) -> str:
    """
    Resolve llama-server executable.

    Supports:
    - explicit absolute/relative path
    - binary in PATH: llama-server
    - common llama.cpp build locations
    - fallback from bad ./llama-server env value to PATH search
    """
    requested = (value or "").strip() or "llama-server"

    if ("/" in requested or "\\" in requested) and Path(requested).exists():
        return requested

    name = Path(requested).name or "llama-server"

    for candidate_name in [requested, name, "llama-server"]:
        found = shutil.which(candidate_name)
        if found:
            return found

    candidates = [
        Path("./llama-server"),
        Path("./llama.cpp/build/bin/llama-server"),
        Path("./llama.cpp/build/bin/Release/llama-server"),
        Path("./llama.cpp/build/bin/Debug/llama-server"),
        Path("../llama.cpp/build/bin/llama-server"),
        Path.home() / "llama.cpp/build/bin/llama-server",
        Path.home() / "llama.cpp/build/bin/Release/llama-server",
        Path("/usr/local/bin/llama-server"),
        Path("/usr/bin/llama-server"),
    ]

    for p in candidates:
        if p.exists():
            return str(p)

    return requested


@dataclass
class LlamaServerConfig:
    executable: str
    model: str
    mmproj: str | None
    host: str
    port: int

    ctx_size: int | None
    parallel: int | None
    batch_size: int | None
    ubatch_size: int | None
    gpu_layers: int | None
    threads: int | None
    flash_attn: bool
    no_mmap: bool
    cache_ram: int | None

    temp: float | None
    top_p: float | None
    repeat_penalty: float | None
    presence_penalty: float | None

    extra_args: list[str]
    log_file: Path
    pid_file: Path

    @classmethod
    def from_env(cls, port: int | None = None) -> "LlamaServerConfig":
        selected_port = port or _env_int("LLAMA_PORT", 8080) or 8080

        extra_raw = _env_str("LLAMA_EXTRA_ARGS", "") or ""
        extra_args = extra_raw.split() if extra_raw else []

        return cls(
            executable=resolve_llama_server_bin(_env_str("LLAMA_SERVER_BIN", "llama-server")),
            model=_env_str("LLAMA_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
            mmproj=_env_str("LLAMA_MMPROJ", DEFAULT_MMPROJ),
            host=_env_str("LLAMA_HOST", "127.0.0.1") or "127.0.0.1",
            port=selected_port,
            ctx_size=_env_int("LLAMA_CTX", _env_int("LLAMA_CTX_SIZE", 4096)),
            parallel=_env_int("LLAMA_PARALLEL", 1),
            batch_size=_env_int("LLAMA_BATCH", _env_int("LLAMA_BATCH_SIZE", 512)),
            ubatch_size=_env_int("LLAMA_UBATCH", _env_int("LLAMA_UBATCH_SIZE", 256)),
            gpu_layers=_env_int("LLAMA_GPU_LAYERS", _env_int("LLAMA_N_GPU_LAYERS", -1)),
            threads=_env_int("LLAMA_THREADS", None),
            flash_attn=_env_bool("LLAMA_FLASH_ATTN", True),
            no_mmap=_env_bool("LLAMA_NO_MMAP", False),
            cache_ram=_env_int("LLAMA_CACHE_RAM", None),
            temp=_env_float("LLAMA_TEMP", None),
            top_p=_env_float("LLAMA_TOP_P", None),
            repeat_penalty=_env_float("LLAMA_REPEAT_PENALTY", None),
            presence_penalty=_env_float("LLAMA_PRESENCE_PENALTY", None),
            extra_args=extra_args,
            log_file=Path(_env_str("LLAMA_LOG_FILE", "llama_server.log") or "llama_server.log"),
            pid_file=Path(_env_str("LLAMA_PID_FILE", "llama_server.pid") or "llama_server.pid"),
        )

    def validate_paths(self) -> list[str]:
        warnings: list[str] = []

        if not _path_exists_or_empty(self.executable):
            warnings.append(f"LLAMA_SERVER_BIN non trovato: {self.executable} — imposta LLAMA_SERVER_BIN al percorso reale del binario llama-server")

        if not _path_exists_or_empty(self.model):
            warnings.append(f"LLAMA_MODEL non trovato: {self.model}")

        if self.mmproj and not _path_exists_or_empty(self.mmproj):
            warnings.append(f"LLAMA_MMPROJ non trovato: {self.mmproj}")

        return warnings

    def command(self) -> list[str]:
        cmd = [
            self.executable,
            "-m",
            self.model,
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]

        if self.mmproj:
            # llama.cpp recenti accettano --mmproj; se il tuo binario usa altro,
            # puoi bypassare con LLAMA_EXTRA_ARGS.
            cmd += ["--mmproj", self.mmproj]

        if self.ctx_size:
            cmd += ["--ctx-size", str(self.ctx_size)]

        if self.parallel:
            cmd += ["--parallel", str(self.parallel)]

        if self.batch_size:
            cmd += ["--batch-size", str(self.batch_size)]

        if self.ubatch_size:
            cmd += ["--ubatch-size", str(self.ubatch_size)]

        if self.gpu_layers is not None:
            cmd += ["--n-gpu-layers", str(self.gpu_layers)]

        if self.threads:
            cmd += ["--threads", str(self.threads)]

        if self.flash_attn:
            cmd += ["--flash-attn", "on"]

        if self.no_mmap:
            cmd += ["--no-mmap"]

        if self.cache_ram is not None:
            cmd += ["--cache-ram", str(self.cache_ram)]

        # Sampling defaults lato server: utili per wizard/modelli che loopano.
        # Le singole chiamate API possono comunque sovrascriverli.
        if self.temp is not None:
            cmd += ["--temp", str(self.temp)]

        if self.top_p is not None:
            cmd += ["--top-p", str(self.top_p)]

        if self.repeat_penalty is not None:
            cmd += ["--repeat-penalty", str(self.repeat_penalty)]

        if self.presence_penalty is not None:
            # Alcuni build di llama.cpp potrebbero non supportarlo.
            # Se dà errore, togli LLAMA_PRESENCE_PENALTY o mettilo in LLAMA_EXTRA_ARGS solo se supportato.
            cmd += ["--presence-penalty", str(self.presence_penalty)]

        cmd.extend(self.extra_args)
        return cmd


class LlamaAutoStarter:
    def __init__(self, config: LlamaServerConfig):
        self.config = config

    @classmethod
    def from_env(cls, port: int | None = None) -> "LlamaAutoStarter":
        return cls(LlamaServerConfig.from_env(port=port))

    def is_port_open(self) -> bool:
        try:
            with socket.create_connection((self.config.host, self.config.port), timeout=1.5):
                return True
        except OSError:
            return False

    def health_ok(self) -> bool:
        try:
            import requests

            r = requests.get(f"http://{self.config.host}:{self.config.port}/health", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def ensure_running(self, wait: bool = True, timeout: int | None = None) -> bool:
        if self.health_ok() or self.is_port_open():
            print(f"[LlamaAutoStarter] llama-server già attivo su porta {self.config.port}", flush=True)
            return True

        return self.start(wait=wait, timeout=timeout)

    def start(self, wait: bool = True, timeout: int | None = None) -> bool:
        warnings = self.config.validate_paths()
        for warning in warnings:
            print(f"[LlamaAutoStarter] ⚠️  {warning}", flush=True)

        cmd = self.config.command()

        print("[LlamaAutoStarter] Avvio llama-server...", flush=True)
        print(f"[LlamaAutoStarter] Binario: {self.config.executable}", flush=True)
        print(f"[LlamaAutoStarter] Modello: {self.config.model}", flush=True)
        if self.config.mmproj:
            print(f"[LlamaAutoStarter] mmproj: {self.config.mmproj}", flush=True)
        print(
            "[LlamaAutoStarter] Parametri: "
            f"port={self.config.port} ctx={self.config.ctx_size} parallel={self.config.parallel} "
            f"batch={self.config.batch_size} ubatch={self.config.ubatch_size} "
            f"gpu_layers={self.config.gpu_layers}",
            flush=True,
        )
        if self.config.extra_args:
            print(f"[LlamaAutoStarter] Extra args: {' '.join(self.config.extra_args)}", flush=True)

        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.pid_file.parent.mkdir(parents=True, exist_ok=True)

        log = open(self.config.log_file, "a", encoding="utf-8")
        log.write("\n\n===== llama-server start =====\n")
        log.write("CMD: " + " ".join(cmd) + "\n")
        log.flush()

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=os.getcwd(),
                start_new_session=True,
            )
        except Exception as e:
            print(f"[LlamaAutoStarter] ❌ Errore avvio llama-server: {e}", flush=True)
            return False

        self.config.pid_file.write_text(str(proc.pid), encoding="utf-8")

        if not wait:
            return True

        max_wait = timeout or _env_int("LLAMA_START_TIMEOUT", 180) or 180
        started = time.time()
        while time.time() - started < max_wait:
            if proc.poll() is not None:
                print(f"[LlamaAutoStarter] ❌ llama-server terminato subito, exit={proc.returncode}", flush=True)
                return False

            if self.health_ok() or self.is_port_open():
                print("[LlamaAutoStarter] ✅ llama-server pronto", flush=True)
                return True

            time.sleep(1)

        print(f"[LlamaAutoStarter] ⚠️  timeout attesa llama-server ({max_wait}s)", flush=True)
        return False

    def stop(self, timeout: int = 10) -> bool:
        pid_file = self.config.pid_file
        if not pid_file.exists():
            print("[LlamaAutoStarter] PID file assente, niente da fermare", flush=True)
            return True

        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            pid_file.unlink(missing_ok=True)
            print("[LlamaAutoStarter] PID file non valido, rimosso", flush=True)
            return False

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pid_file.unlink(missing_ok=True)
            print("[LlamaAutoStarter] processo già terminato", flush=True)
            return True
        except Exception as e:
            print(f"[LlamaAutoStarter] errore SIGTERM: {e}", flush=True)
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                pid_file.unlink(missing_ok=True)
                print("[LlamaAutoStarter] stop completato", flush=True)
                return True

        try:
            os.kill(pid, signal.SIGKILL)
            pid_file.unlink(missing_ok=True)
            print("[LlamaAutoStarter] stop forzato completato", flush=True)
            return True
        except Exception as e:
            print(f"[LlamaAutoStarter] errore SIGKILL: {e}", flush=True)
            return False


def main() -> int:
    # Piccolo entrypoint utile anche se lanci:
    # python -m spyengine.services.llama_autostart --no-wait
    wait = "--no-wait" not in sys.argv
    stop = "--stop" in sys.argv

    starter = LlamaAutoStarter.from_env()

    if stop:
        return 0 if starter.stop() else 1

    return 0 if starter.ensure_running(wait=wait) else 1


if __name__ == "__main__":
    raise SystemExit(main())
