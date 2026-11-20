import json
from datetime import datetime, timezone
from time import perf_counter
from app.manifest import manifest
from app.pipeline import execute
from .repository import fetch, fetch_extra, persist


def run(source,book,stock=None,requisitions=None,mode='partial'):
    proof = manifest(source,book,stock,requisitions,mode)
    started = perf_counter()
    result = execute(source,book,stock,requisitions,mode)
    created = datetime.now(timezone.utc).isoformat()
    proof.update(elapsed_ms=round((perf_counter()-started)*1000,2),created=created)
    result['manifest'] = proof
    stored = persist(proof['run_id'],source,book,result,created,stock,requisitions,mode)
    return json.loads(stored['result'])


def replay(run_id):
    old = fetch(run_id)
    more = fetch_extra(run_id)
    if more is None:
        return run(old['source'],old['book'])
    return run(old['source'],old['book'],more['stock'],more['requisitions'],more['mode'])


def get(run_id):
    return json.loads(fetch(run_id)['result'])
