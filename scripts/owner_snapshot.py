"""One-shot owner snapshots using the caller's existing configured CLI wrapper.

The pinned server's HTTP/CLI procedure result is an untyped SATS sum:
``[0, payload]`` or ``[1, error]``. HTTP 200/CLI exit zero alone is not success.
No SQL fallback, transport retry, timeout change, or authority call occurs here
unless inventory/export_json/export_world is explicitly invoked with a callable.
"""
import json

INVENTORY_PROCEDURE = 'sim_owned_run_ids'
EXPORT_PROCEDURE = 'sim_export_owned_run'


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


def _nonfinite(_):
    raise ValueError('nonfinite JSON number')


def _json(text, error):
    if not isinstance(text, str):
        raise ValueError(error)
    try:
        return json.loads(text, object_pairs_hook=_object, parse_constant=_nonfinite)
    except (ValueError, TypeError, RecursionError):
        raise ValueError(error) from None


def _result(raw):
    value = _json(raw, 'invalid owner procedure response')
    if (not isinstance(value, list) or len(value) != 2
            or type(value[0]) is not int or value[0] not in (0, 1)):
        raise ValueError('invalid owner procedure result')
    tag, payload = value
    if tag == 1:
        if not isinstance(payload, str):
            raise ValueError('invalid owner procedure error')
        raise ValueError('run unavailable' if payload == 'run unavailable'
                         else 'owner procedure failed')
    return payload


def parse_inventory(raw):
    """Return the procedure's strictly sorted, unique owner run IDs."""
    ids = _result(raw)
    if (not isinstance(ids, list) or any(not isinstance(run, str) or not run for run in ids)
            or ids != sorted(set(ids))):
        raise ValueError('invalid owner inventory')
    return ids


def _export(raw, run):
    body = _result(raw)
    world = _json(body, 'invalid owner world payload')
    if (not isinstance(world, dict) or not isinstance(world.get('run'), str)
            or not world['run'] or (run is not None and world['run'] != run)):
        raise ValueError('invalid owner world identity')
    if type(world.get('next_event')) is not int or not 0 < world['next_event'] < 2**64:
        raise ValueError('invalid owner world event cursor')
    return body, world


def parse_export(raw, run=None):
    """Return the decoded World after checking its identity and event cutoff."""
    return _export(raw, run)[1]


def parse_export_json(raw, run=None):
    """Return the exact inner World JSON for export fidelity and byte counts."""
    return _export(raw, run)[0]


def inventory(call):
    """call(name, *arguments) must return stdout using its existing deadline."""
    return parse_inventory(call(INVENTORY_PROCEDURE))


def export_json(call, run):
    return parse_export_json(call(EXPORT_PROCEDURE, run), run)


def export_world(call, run):
    return parse_export(call(EXPORT_PROCEDURE, run), run)
