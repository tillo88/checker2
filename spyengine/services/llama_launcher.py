from __future__ import annotations
import os, shutil, subprocess, time, requests


class LlamaServerLauncher:
    def __init__(self, model_path: str, mmproj_path: str | None = None, port: int = 8080, ctx: int = 4096, log_path: str = "llama_server.log"):
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.port = port
        self.ctx = ctx
        self.log_path = log_path
        self.proc = None

    def find_server(self) -> str | None:
        path = shutil.which("llama-server")
        if path:
            return path
        for p in [
            os.path.expanduser("~/llama.cpp/build/bin/llama-server"),
            os.path.expanduser("~/llama.cpp/llama-server"),
            "/usr/local/bin/llama-server",
            "/usr/bin/llama-server",
            "./llama-server",
        ]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return None

    def is_running(self) -> bool:
        try:
            return requests.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def start(self, wait_seconds: int = 300) -> bool:
        if self.is_running():
            return True
        server = self.find_server()
        if not server:
            raise FileNotFoundError("llama-server non trovato")
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(self.model_path)

        cmd = [server, "-m", os.path.abspath(self.model_path), "-c", str(self.ctx), "--host", "127.0.0.1", "--port", str(self.port), "-ngl", "99", "--temp", "0.3", "--top-p", "0.8"]
        if self.mmproj_path:
            if not os.path.exists(self.mmproj_path):
                raise FileNotFoundError(self.mmproj_path)
            cmd[3:3] = ["--mmproj", os.path.abspath(self.mmproj_path)]

        log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

        for _ in range(wait_seconds):
            time.sleep(1)
            if self.proc.poll() is not None:
                return False
            if self.is_running():
                with open("llama_server.pid", "w", encoding="utf-8") as f:
                    f.write(str(self.proc.pid))
                return True
        self.stop()
        return False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
