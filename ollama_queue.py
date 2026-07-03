#!/usr/bin/env python3
"""
LlamaQueue - Coda prioritaria thread-safe per llama.cpp server (OpenAI-compatible API).
Drop-in replacement di OllamaQueue. Supporta vision via mmproj.
"""
import queue
import threading
import time
import requests
import json
import re
from typing import Callable, Optional, List


class OllamaJob:
    """Singolo job nella coda prioritaria."""
    def __init__(self, priority, prompt, images, timeout, callback, job_id):
        self.priority = priority
        self.prompt = prompt
        self.images = images
        self.timeout = timeout
        self.callback = callback
        self.job_id = job_id
        self.timestamp = time.time()

    def __lt__(self, other):
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.timestamp < other.timestamp


class OllamaQueue:
    """Coda prioritaria con worker thread dedicato per llama.cpp server."""

    PRIORITY_VISION = 0
    PRIORITY_CONTEXT = 1
    PRIORITY_WIZARD = 2

    def __init__(self, host="127.0.0.1", port=8080, model="qwen3.5-14b-spy", min_interval=1.0):
        self.host = host
        self.port = port
        self.model = model
        self.min_interval = min_interval
        self.base_url = f"http://{host}:{port}"
        self.queue = queue.PriorityQueue()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.active = False
        self._lock = threading.Lock()
        self._last_request_time = 0
        self._job_counter = 0
        self._stats = {"processed": 0, "errors": 0}

    def start(self):
        """Avvia il worker thread."""
        self.active = True
        healthy = self._healthcheck()
        self.worker_thread.start()
        status = "ONLINE" if healthy else "OFFLINE"
        print(f"[LlamaQueue] Avviata ({status}) | endpoint={self.base_url} | model={self.model} | min_interval={self.min_interval}s")

    def stop(self):
        """Ferma il worker in modo pulito."""
        self.active = False
        self.queue.put(OllamaJob(0, "", None, 0, None, -1))
        self.worker_thread.join(timeout=5)
        print(f"[LlamaQueue] Fermata. Jobs: {self._stats['processed']}, errori: {self._stats['errors']}")

    def _healthcheck(self):
        """Verifica che llama.cpp server risponda."""
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5)
            if r.status_code == 200:
                return True
        except:
            pass
        try:
            r = requests.get(f"{self.base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                return True
        except:
            pass
        return False

    def _worker(self):
        """Loop principale del worker thread."""
        while self.active:
            try:
                job = self.queue.get(timeout=1)
                if job.job_id == -1:
                    break
                self._process_job(job)
            except queue.Empty:
                continue

    def _process_job(self, job):
        """Processa un singolo job con rate limiting."""
        with self._lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)

        # Costruisci messaggi OpenAI-compatibili
        content = []

        # Aggiungi immagini prima del testo (llama.cpp le processa in ordine)
        if job.images:
            for img_b64 in job.images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })

        content.append({"type": "text", "text": job.prompt})

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "temperature": 0.3,
            "top_p": 0.8
        }

        try:
            r = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=job.timeout
            )
            if r.status_code == 200:
                data = r.json()
                result = data["choices"][0]["message"]["content"]
                with self._lock:
                    self._last_request_time = time.time()
                    self._stats["processed"] += 1
                if job.callback:
                    job.callback(result, None)
            else:
                with self._lock:
                    self._stats["errors"] += 1
                if job.callback:
                    job.callback(None, f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            with self._lock:
                self._stats["errors"] += 1
            if job.callback:
                job.callback(None, str(e))

    def submit(self, prompt, images=None, priority=1, timeout=60, callback=None) -> str:
        with self._lock:
            self._job_counter += 1
            job_id = self._job_counter
        job = OllamaJob(priority, prompt, images, timeout, callback, job_id)
        self.queue.put(job)
        return job_id

    def is_healthy(self):
        return self._healthcheck()

    def queue_size(self):
        return self.queue.qsize()


if __name__ == "__main__":
    lq = OllamaQueue(port=8080)
    lq.start()

    def cb(resp, err):
        if err:
            print(f"Errore: {err}")
        else:
            print(f"Risposta: {resp[:100]}...")

    lq.submit("Ciao, rispondi con un JSON: {\"ok\": true}", priority=0, callback=cb)
    time.sleep(5)
    lq.stop()
