"""Loopback-only spend watcher for the bystanders-1 paid A/B."""
import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from trials import cost

MODELS = {"deepseek-v4-1-flash-1017", "zai-glm-5-3-flash"}
# Both published prices are <= $0.30/M input and $1.20/M output. At 64 KiB of text JSON
# and 8192 output tokens, $0.10 per admission leaves room for chat framing and unknown usage.
# Charge the reservation before forwarding, including retries and failed in-flight requests.
RESERVATION = 0.10
CALL_LIMIT = 24
PAID_END = 1795071600  # 2026-11-19 08:00 CET


@contextmanager
def watch(envfile, audit):
    key = next((line.partition("=")[2].strip().strip('"\'') for line in envfile.read_text().splitlines()
                if line.startswith("MISTRAL_API_KEY=")), "")
    if not key:
        raise RuntimeError("MISTRAL_API_KEY unavailable in the trial checkout")
    lock = threading.Lock()
    calls = 0
    spent = 0.0

    class Forwarder(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def do_POST(self):
            nonlocal calls, spent
            size = int(self.headers.get("Content-Length", "0"))
            if self.path != "/v1/chat/completions" or not 0 < size <= 65536:
                return self.reply(400, b'{"error":"request outside trial limits"}')
            body = self.rfile.read(size)
            data = json.loads(body)
            if (data.get("model") not in MODELS or data.get("stream")
                    or not 0 < data.get("max_tokens", 0) <= 8192):
                return self.reply(400, b'{"error":"model or output outside trial limits"}')
            with lock:
                if calls >= CALL_LIMIT or spent >= 2.4 or time.time() + 45 >= PAID_END:
                    return self.reply(429, b'{"error":"trial spend or time limit reached"}')
                calls += 1
                call = calls
                with audit.open("a") as f:
                    f.write(json.dumps({"call": call, "model": data["model"],
                                        "max_reserved_usd": round(call * RESERVATION, 2)}) + "\n")
            request = urllib.request.Request(
                "https://api.mistral.ai/v1/chat/completions", body,
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=40) as response:
                    status, result = response.status, response.read()
            except urllib.error.HTTPError as error:
                status, result = error.code, error.read()
            except OSError:
                status, result = 502, b'{"error":"upstream did not complete"}'
            usage = json.loads(result).get("usage") if status == 200 else None
            usd = cost(data["model"], usage["prompt_tokens"], usage["completion_tokens"],
                       (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)) if usage else None
            with lock:
                spent += usd if usd is not None else RESERVATION
                with audit.open("a") as f:
                    f.write(json.dumps({"call": call, "status": status, "usage": usage,
                                        "cost_usd": usd, "watched_usd": spent}) + "\n")
            return self.reply(status, result)

    with ThreadingHTTPServer(("127.0.0.1", 0), Forwarder) as server:
        server.daemon_threads = False
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1"
        finally:
            server.shutdown()
            thread.join()
