import json
from app.modules.runs.service import get
from .decisions import timeline


def bundle(run_id):
    history = timeline(run_id)
    run = get(run_id)
    # The export carries source line evidence and the applicable decision version.
    payload = {'manifest':run['manifest'],'counts':run['counts'],'results':run['accepted'],
               'quarantine':run['quarantine'],'suppressed':run['suppressed'],
               'reconciliation':run['book'],'review':history}
    if 'writeoff' in run:
        payload['writeoff'] = run['writeoff']
    return json.dumps(payload,ensure_ascii=False,indent=2)
