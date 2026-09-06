"""Final capture after stopping the fixed-population pilot's owned producers."""
import concurrent.futures
import json
import re
import time


def identity_text(value):
    if isinstance(value, list) and len(value) == 1:
        return identity_text(value[0])
    if isinstance(value, dict) and set(value) == {"__identity__"}:
        return identity_text(value["__identity__"])
    if isinstance(value, str):
        value = value.removeprefix("0x").lower()
        if re.fullmatch(r"[0-9a-f]{64}", value):
            return value
    raise ValueError("invalid authority grant identity")


def finalize_fixed_run(run, *, stop_host, control, call, state, record):
    """Stop host, pause, revoke this run's grants, and capture one audit cutoff.

    Every authority operation uses the caller's existing finite CLI deadline.
    No retry, clock advancement, or grant in another run is permitted here.
    ``record`` persists each completed boundary even if a later step fails.
    """
    if not isinstance(run, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run):
        raise ValueError("invalid finalization run identifier")
    proof = dict(protocol="sao-fixed-run-finalization-v1", run=run,
                 started_at=time.time(), phase="stopping_host")

    def boundary(phase, **values):
        proof.update(phase=phase, **values)
        record(proof)

    def sql(query):
        result = json.loads(control("sql", query, "--format", "json"))
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0].get("rows"), list):
            raise ValueError("invalid finalization query result")
        return result[0]["rows"]

    def clocks():
        rows = sql(f"SELECT run, paused FROM sim_client_clock WHERE run = '{run}'")
        if rows != [[run, True]]:
            raise ValueError("final run clock is not confirmed paused")
        return rows

    record(proof)
    try:
        host_error = None
        try:
            stopped = stop_host()
            if not isinstance(stopped, dict) or stopped.get("stopped") is not True:
                raise ValueError("owned host stop was not confirmed")
            boundary("host_stopped", host=stopped, host_stopped_at=time.time())
        except Exception as error:
            host_error = str(error)
            boundary("host_stop_failed", host_error=host_error)
        # A producer shutdown failure must not leave this run advancing with
        # usable participant grants. Retain failure and attempt scoped cleanup;
        # a still-live producer prevents acceptance of a final capture.
        call("sim_operator_pause", run)
        boundary("paused", clocks=clocks(), paused_at=time.time())
        rows = sql(f"SELECT identity, run, observer, actor FROM sim_client_access WHERE run = '{run}'")
        identities = []
        for row in rows:
            if (not isinstance(row, list) or len(row) != 4 or row[1] != run
                    or type(row[2]) is not bool or type(row[3]) is not int or row[3] < 0):
                raise ValueError("invalid finalization grant scope")
            identities.append(identity_text(row[0]))
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate finalization grant identity")
        boundary("revoking", grants_before=rows, revoke_results=[])
        failures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(identities)))) as pool:
            tasks = {pool.submit(call, "sim_revoke_client", identity): identity for identity in identities}
            for task in concurrent.futures.as_completed(tasks):
                error = None
                try:
                    task.result()
                except Exception as exception:
                    error = str(exception)
                    failures.append(error)
                proof["revoke_results"].append(dict(identity=tasks[task], error=error))
                record(proof)
        if failures:
            raise RuntimeError("one or more final grant revocations failed; no retry")
        remaining = sql(f"SELECT identity, run, observer, actor FROM sim_client_access WHERE run = '{run}'")
        if remaining:
            raise ValueError("final run still has grants")
        boundary("grants_revoked", grants_after=remaining, clocks=clocks(), revoked_at=time.time())
        if host_error is not None:
            raise RuntimeError(f"owned host stop was not confirmed: {host_error}")
        world = state()
        if world.get("run") != run or type(world.get("next_event")) is not int or world["next_event"] < 1:
            raise ValueError("invalid final World identity or event cutoff")
        cutoff = world["next_event"]
        audit = sql(f"SELECT json FROM sim_audit WHERE run = '{run}' AND event_id < {cutoff}")
        if any(not isinstance(row, list) or len(row) != 1 or not isinstance(row[0], str) for row in audit):
            raise ValueError("invalid final audit rows")
        events = sorted((json.loads(row[0]) for row in audit), key=lambda event: event["id"])
        if (any(event.get("run") != run or type(event.get("id")) is not int for event in events)
                or [event["id"] for event in events] != list(range(1, cutoff))):
            raise ValueError("final audit is not exactly contiguous for its World")
        boundary("captured", clocks=clocks(), next_event=cutoff, event_count=len(events),
                 world_exports=1, finished_at=time.time())
        return world, events
    except Exception as error:
        boundary("failed", error=str(error), failed_at=time.time())
        raise
