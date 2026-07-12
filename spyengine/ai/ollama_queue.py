from __future__ import annotations
import queue, threading, time, requests


class OllamaJob:
    def __init__(self, priority, prompt, images, timeout, callback, job_id, counter):
        self.priority = priority
        self.prompt = prompt
        self.images = images or []
        self.timeout = timeout
        self.callback = callback
        self.job_id = job_id
        self.counter = counter
        self.retries = 0
        self.max_retries = 2

    def as_queue_item(self):
        return (self.priority, self.counter, self)


class OllamaQueue:
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
        self.active = False
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._lock = threading.Lock()
        self._last_request_time = 0.0
        self._job_counter = 0
        self._queue_counter = 0
        self._stats = {"processed": 0, "errors": 0, "retried": 0}
        self._shutdown_sentinel = object()

    def start(self):
        if self.active:
            return
        self.active = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def stop(self):
        self.active = False
        with self._lock:
            self._queue_counter += 1
            counter = self._queue_counter
        self.queue.put((999, counter, self._shutdown_sentinel))
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=10)

    def _healthcheck(self, timeout=5):
        for ep in ["/health", "/v1/models"]:
            try:
                r = requests.get(f"{self.base_url}{ep}", timeout=timeout)
                if r.status_code == 200:
                    return True
            except requests.exceptions.RequestException:
                continue
        return False

    def is_healthy(self):
        return self._healthcheck(timeout=3)

    def _worker(self):
        while self.active:
            try:
                _, _, job = self.queue.get(timeout=1)
                if job is self._shutdown_sentinel:
                    break
                self._process_job(job)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[OllamaQueue] Worker error: {e}")

    def _process_job(self, job: OllamaJob):
        with self._lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_time = time.time()

        content = []
        for img_b64 in job.images:
            url = img_b64 if str(img_b64).startswith("data:image") else f"data:image/jpeg;base64,{img_b64}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        content.append({"type": "text", "text": job.prompt})
        payload = {"model": self.model, "messages": [{"role": "user", "content": content}], "stream": False, "temperature": 0.3, "top_p": 0.8}

        try:
            r = requests.post(f"{self.base_url}/v1/chat/completions", json=payload, timeout=job.timeout)
            if r.status_code == 200:
                result = r.json()["choices"][0]["message"]["content"]
                with self._lock:
                    self._stats["processed"] += 1
                if job.callback:
                    job.callback(result, None)
            else:
                self._handle_error(job, f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.exceptions.Timeout:
            self._handle_error(job, "Request timeout")
        except requests.exceptions.ConnectionError:
            self._handle_error(job, "Connection refused - llama.cpp down?")
        except Exception as e:
            self._handle_error(job, str(e))

    def _handle_error(self, job: OllamaJob, error_msg: str):
        job.retries += 1
        if job.retries <= job.max_retries:
            backoff = 2 ** job.retries
            print(f"[OllamaQueue] Retry {job.retries}/{job.max_retries} in {backoff}s: {error_msg[:80]}")
            time.sleep(backoff)
            self.queue.put(job.as_queue_item())
            with self._lock:
                self._stats["retried"] += 1
        else:
            with self._lock:
                self._stats["errors"] += 1
            if job.callback:
                job.callback(None, error_msg)

    def submit(self, prompt, images=None, priority=1, timeout=60, callback=None) -> str:
        with self._lock:
            self._job_counter += 1
            self._queue_counter += 1
            job_id = self._job_counter
            counter = self._queue_counter
        job = OllamaJob(priority, prompt, images, timeout, callback, job_id, counter)
        self.queue.put(job.as_queue_item())
        return str(job_id)

    def queue_size(self):
        return self.queue.qsize()

    def get_stats(self):
        with self._lock:
            return dict(self._stats)
