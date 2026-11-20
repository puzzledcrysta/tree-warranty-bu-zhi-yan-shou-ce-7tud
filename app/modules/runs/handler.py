from base64 import b64encode
from fastapi import APIRouter
from app.inputs import WriteoffPair
from .repository import fetch, fetch_extra, history
from .service import run, replay, get

router = APIRouter()

@router.post('/api/runs')
def create(source: WriteoffPair):
    if source.stock is None and source.requisitions is None:
        return run(source.raw(),source.ledger())
    return run(source.raw(),source.ledger(),source.stock_bytes(),
               source.requisition_bytes(),source.mode)

@router.get('/api/runs')
def list_runs():
    return history()

@router.get('/api/runs/{run_id}')
def detail(run_id: str):
    return get(run_id)

@router.post('/api/runs/{run_id}/replay')
def again(run_id: str):
    return replay(run_id)


@router.get('/api/runs/{run_id}/source')
def source_inputs(run_id: str):
    record = fetch(run_id)
    payload = {'data_base64': b64encode(record['source']).decode(),
               'book_base64': b64encode(record['book']).decode()}
    more = fetch_extra(run_id)
    if more is not None:
        payload['stock_base64'] = b64encode(more['stock']).decode()
        payload['requisitions_base64'] = b64encode(more['requisitions']).decode()
        payload['mode'] = more['mode']
    return payload
