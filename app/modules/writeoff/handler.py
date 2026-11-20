from fastapi import APIRouter
from app.settings import SAMPLE_ROOT
from app.pipeline import stages
from app.inputs import WriteoffPair
from app.modules.writeoff.engine import MODES
from app.modules.writeoff.ledger import STOCK_FIELDS, REQUISITION_FIELDS
from app.modules.writeoff.service import settle

router = APIRouter()


@router.get('/api/writeoff/contract')
def contract():
    return {'stock_fields': list(STOCK_FIELDS), 'requisition_fields': list(REQUISITION_FIELDS),
            'modes': list(MODES)}


@router.post('/api/writeoff')
def recalculate(source: WriteoffPair):
    result = stages(source.raw())
    stock = (SAMPLE_ROOT / 'stock.csv').read_bytes() if source.stock is None \
        else source.stock_bytes()
    requisitions = (SAMPLE_ROOT / 'requisitions.csv').read_bytes() if source.requisitions is None \
        else source.requisition_bytes()
    return settle(result['accepted'], stock, requisitions, source.mode)
