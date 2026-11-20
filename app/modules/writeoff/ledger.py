from app.errors import DataError
from app.modules.domain.values import calendar, whole
from app.modules.intake.reader import decode, records

STOCK_FIELDS = ('苗批号', '树种', '进场日', '进场数量')
REQUISITION_FIELDS = ('领用单号', '修订号', '提交时间', '街段验收单', '树位号', '树种', '数量', '原始备注')
MISSING = {'', '-', 'n/a', 'null', '未知'}
MAX_LOT_QTY = 10 ** 9


def _rows(payload, expected):
    text, encoding = decode(payload)
    if not text.strip():
        raise DataError('BLANK_FILE', '文件只有空白')
    rows = iter(records(text))
    _, header = next(rows, (0, []))
    if header != list(expected):
        raise DataError('HEADER', f'表头须为 {",".join(expected)}')
    return rows


def stock(payload):
    """苗批进场账：同批不允许重复登记，数量为正整数。"""
    lots = {}
    for line, row in _rows(payload, STOCK_FIELDS):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != len(STOCK_FIELDS):
            raise DataError('WIDTH', f'苗批账第 {line} 行列数不符')
        lot_id, species, raw_day, raw_qty = (value.strip() for value in row)
        if lot_id in MISSING or species in MISSING or raw_day in MISSING or raw_qty in MISSING:
            raise DataError('REQUIRED', f'苗批账第 {line} 行存在必填空缺')
        if lot_id in lots:
            raise DataError('LOT_CONFLICT', f'苗批 {lot_id} 重复登记')
        day = calendar(raw_day)
        qty = whole(raw_qty, 1, MAX_LOT_QTY)
        lots[lot_id] = {'lot': lot_id, 'species': species, 'arrived': day.isoformat(),
                        'quantity': qty, 'line': line}
    if not lots:
        raise DataError('HEADER_ONLY', '苗批账没有数据行')
    return lots
