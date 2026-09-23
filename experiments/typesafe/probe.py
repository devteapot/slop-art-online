#!/usr/bin/env python3
"""Bounded TypeSafe API research probe. No simulator or game mutations."""
import argparse
import concurrent.futures
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import threading
import time

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
LOCAL = threading.local()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_key(env_file):
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key and env_file:
        for line in Path(env_file).read_text().splitlines():
            name, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and name.strip() == "TYPESAFE_API_KEY":
                key = value.strip()
                if key[:1] in ("'", '"') and key[-1:] == key[:1]:
                    key = key[1:-1]
                break
    if not key or any(c.isspace() for c in key):
        raise ValueError("A nonempty TYPESAFE_API_KEY is required (environment or --env-file).")
    return key


def number(x, lo, hi):
    return type(x) in (int, float) and math.isfinite(x) and lo <= x <= hi


def validate(body, questions):
    if not isinstance(body, dict) or not isinstance(body.get("model"), str):
        raise ValueError("response lacks model")
    answers = body.get("answers", {})
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("answer IDs do not match request")
    for qid, q in questions.items():
        a = answers[qid]
        if not isinstance(a, dict) or a.get("type") != q["type"]:
            raise ValueError("answer type mismatch")
        if q["type"] == "noul":
            if not number(a.get("noul"), 0, 1):
                raise ValueError("invalid noul")
            continue
        keys = set(q["criteria"]) if q["type"] == "choice" else {str(n) for n in range(len(q["criteria"]))}
        probs = a.get("probabilities", {})
        if not isinstance(probs, dict) or set(probs) != keys or not all(number(p, 0, 1) for p in probs.values()):
            raise ValueError("invalid probability support")
        if not math.isclose(sum(probs.values()), 1, abs_tol=0.02) or not number(a.get("confidence"), 0, 1):
            raise ValueError("invalid distribution/confidence")
        if q["type"] == "choice":
            if a.get("choice") not in keys:
                raise ValueError("choice outside candidate set")
        elif not number(a.get("score"), 0, len(keys)-1) or set(a.get("legend", {})) != keys:
            raise ValueError("invalid score/legend")
    usage = body.get("usage", {})
    if any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")):
        raise ValueError("missing token accounting")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    suite = json.loads(args.cases.read_text())
    if not (1 <= args.repeats <= 4 and 1 <= args.concurrency <= 8 and 0 < args.timeout <= 30):
        parser.error("require repeats 1..4, concurrency 1..8, timeout (0,30]")
    jobs = [(r, c) for r in range(args.repeats) for c in suite["cases"]]
    if not 1 <= len(jobs) <= 64:
        parser.error("probe is bounded to 64 requests")
    random.Random(173).shuffle(jobs)
    key = load_key(args.env_file) if args.live else ""
    args.out.mkdir(parents=True, exist_ok=False)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    manifest = {"suite": suite, "endpoint": ENDPOINT, "model_requested": args.model,
                "live": args.live, "repeats": args.repeats, "concurrency": args.concurrency,
                "request_count": len(jobs), "socket_timeout_seconds": args.timeout,
                "retries": 0, "order_seed": 173, "git_head": revision,
                "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "python": platform.python_version(), "host_platform": platform.platform(),
                "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "scope": "Synthetic fixtures only; zero game population, subscriptions, observer load or physical effects. HTTP connection reused per worker, first request includes connection establishment. Closed-loop bounded concurrency, not an open-loop capacity test."}
    write(args.out / "manifest.json", manifest)
    stop = threading.Event()

    def run(job):
        repeat, case = job
        stem = f"{repeat:02}-{case['id']}"
        request = {"model": args.model, "state": case["state"], "questions": suite["question_sets"][case["set"]]}
        write(args.out / (stem + ".request.json"), request)
        if not args.live or stop.is_set():
            result = {"case": case["id"], "repeat": repeat, "status": "dry_run" if not args.live else "not_dispatched_after_failure"}
            write(args.out / (stem + ".result.json"), result)
            return result
        result = {"case": case["id"], "set": case["set"], "repeat": repeat, "status": "started"}
        write(args.out / (stem + ".result.json"), result)
        started = time.perf_counter()
        try:
            if not hasattr(LOCAL, "connection"):
                LOCAL.connection = http.client.HTTPSConnection("api.typesafe.ai", timeout=args.timeout)
            connection = LOCAL.connection
            connection.request("POST", "/v1/systemone", body=json.dumps(request).encode(), headers={
                "Authorization": "Bearer " + key, "Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(1048577)
            result["elapsed_ms"] = (time.perf_counter() - started) * 1000
            result["http_status"] = response.status
            result["response_headers"] = {k: v for k, v in response.getheaders() if k.lower() in ("content-type", "retry-after", "x-request-id")}
            # Never retain a credential reflected by an upstream error.
            text = raw.decode("utf-8", errors="replace").replace(key, "[REDACTED]")
            (args.out / (stem + ".response.txt")).write_text(text)
            if len(raw) > 1048576:
                raise ValueError("response exceeded 1 MiB; retained prefix only")
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}; no retry")
            body = json.loads(text)
            validate(body, request["questions"])
            result.update(status="ok", served_model=body["model"], usage=body["usage"], answers=body["answers"])
            checks = {}
            for qid, expected in case["expected"].items():
                a = body["answers"][qid]
                actual = a["noul"] >= 0.5 if type(expected) is bool else a["choice"]
                checks[qid] = {"expected": expected, "actual": actual, "matches": actual == expected}
            result["fixture_checks"] = checks
        except Exception as exc:
            result.update(status="error", error=str(exc).replace(key, "[REDACTED]"), elapsed_ms=(time.perf_counter()-started)*1000)
            result["delivery_and_cost_may_be_unknown"] = True
            stop.set()
        write(args.out / (stem + ".result.json"), result)
        return result

    begin = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(run, jobs))
    ok = [r for r in results if r["status"] == "ok"]
    latencies = sorted(r["elapsed_ms"] for r in ok)
    quantiles = {str(p): latencies[max(0, math.ceil(p/100*len(latencies))-1)] for p in (50,95,99)} if ok else {}
    checks = [c for r in ok for c in r["fixture_checks"].values()]
    input_tokens = sum(r["usage"]["input_tokens"] for r in ok)
    summary = {"live": args.live, "completed": len(ok), "planned": len(jobs),
               "errors": [r for r in results if r["status"] == "error"],
               "not_dispatched": sum(r["status"] == "not_dispatched_after_failure" for r in results),
               "wall_seconds": time.perf_counter()-begin, "successful_http_ms_nearest_rank": quantiles,
               "max_successful_http_ms": max(latencies) if ok else None,
               "matches": sum(c["matches"] for c in checks), "fixture_checks": len(checks),
               "input_tokens": input_tokens, "output_tokens": sum(r["usage"]["output_tokens"] for r in ok),
               "estimated_successful_input_cost_usd": input_tokens * 0.042 / 1e6,
               "price_assumption": "2026-09-17 public rate $0.042/M input; output free. Failed/unknown usage excluded, estimate is not an invoice.",
               "limits": "Small synthetic screen; no inference of calibration, full cognition, game effects or population capacity. Noul 0.5 used only for fixture reporting. Socket timeout is not a whole-request deadline. No retries, fallback or credential logging."}
    write(args.out / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
