from collections import defaultdict
from app.errors import DataError

MODES = ('partial', 'whole')
MODE_LABELS = {'partial': '按余量核销', 'whole': '整张退回'}
# 行级状态
ALLOCATED = '已核销'
HELD = '挂起'
NO_BASIS = '无补植依据'
UNKNOWN_KEY = '街段未采信'
SPECIES_MISMATCH = '树种不符'
REQ_DUP_TREE = '树位重复领用'
# 汇总/批次级状态
SETTLED = '可签收'
BLOCKED = '暂缓签收'


def _fact_index(accepted):
    facts, cutoff = {}, {}
    for record in accepted:
        cutoff[record['key']] = record['cutoff']
        for item in record['replants']:
            facts[(record['key'], item['tree'])] = item
    return facts, cutoff


def _validate(lines, accepted_keys, facts):
    """把每条可仲裁领用行判定为可参与核销，或给出挂起原因。"""
    valid, held = [], []
    for line in lines:
        reason = None
        if line['key'] not in accepted_keys:
            reason = UNKNOWN_KEY
        elif (line['key'], line['tree']) not in facts:
            reason = NO_BASIS
        elif line['species'] != facts[(line['key'], line['tree'])]['species']:
            reason = SPECIES_MISMATCH
        if reason is None:
            valid.append(line)
        else:
            held.append(_line(line, None, reason, 0))
    return valid, held


def _duplicate_facts(valid):
    """同一补植树位被多张领用单认领时，竞争行全部隔离，交人工裁决。"""
    claimed = defaultdict(list)
    for line in valid:
        claimed[(line['key'], line['tree'])].append(line)
    duplicates, clean = [], []
    for identity, group in claimed.items():
        orders = {row['order'] for row in group}
        if len(orders) > 1:
            duplicates.extend(group)
        else:
            clean.extend(group)
    return clean, duplicates


def _line(line, lot, status, allocated_qty):
    return {'order': line['order'], 'revision': line['revision'], 'key': line['key'],
            'tree': line['tree'], 'line_no': line['line'], 'qty': line['qty'],
            'allocated': allocated_qty, 'status': status, 'lot': lot,
            'species': line['species'], 'raw': line['raw']}


def _eligible_lots(lots, species, replant_day, balances):
    choices = [lot for lot in lots.values()
               if lot['species'] == species and lot['arrived'] <= replant_day
               and balances[lot['lot']] > 0]
    return sorted(choices, key=lambda lot: (lot['arrived'], lot['lot']))


def _allocate(valid, facts, lots, balances, mode):
    """按街段验收日 → 领用单 → 树位的确定顺序核销；余量不得为负。"""
    ordered = sorted(valid, key=lambda row: (facts[(row['key'], row['tree'])]['day'],
                                             row['key'], row['order'], row['tree'], row['line']))
    grouped = defaultdict(list)
    for line in ordered:
        grouped[line['order']].append(line)

    def take(line):
        fact = facts[(line['key'], line['tree'])]
        remaining_need = line['qty']
        placements = []
        for lot in _eligible_lots(lots, line['species'], fact['day'], balances):
            if remaining_need == 0:
                break
            take_qty = min(remaining_need, balances[lot['lot']])
            balances[lot['lot']] -= take_qty
            remaining_need -= take_qty
            placements.append({'lot': lot['lot'], 'qty': take_qty})
        return placements, remaining_need

    allocated, short = [], []
    if mode == 'partial':
        for line in ordered:
            placements, shortage = take(line)
            for placement in placements:
                allocated.append(_line(line, placement['lot'], ALLOCATED, placement['qty']))
            if shortage:
                short.append(line)
    else:
        # 整张退回：先试算整张单，任一树位无法足额则整单不动，已补的树等苗。
        for order, members in sorted(grouped.items()):
            snapshot = dict(balances)
            plan, failed = [], None
            for line in members:
                placements, shortage = take(line)
                plan.append((line, placements, shortage))
                if shortage and failed is None:
                    failed = line
            if failed is None:
                for line, placements, _ in plan:
                    for placement in placements:
                        allocated.append(_line(line, placement['lot'], ALLOCATED, placement['qty']))
            else:
                balances.clear()
                balances.update(snapshot)
                short.extend(line for line, _, _ in plan)
    held = [_line(line, None, HELD, 0) for line in short]
    return allocated, held


def _rollup(allocated, invalid_held, short_held, accepted_keys, facts):
    # 同一树位可能同时有核销行与挂起行，先按树位合并成单行视图，再做单据/批次汇总。
    merged = {}
    for row in allocated + invalid_held + short_held:
        identity = (row['order'], row['key'], row['tree'])
        if identity not in merged:
            merged[identity] = dict(row)
        else:
            current = merged[identity]
            current['allocated'] += row['allocated']
            if row['lot'] is not None:
                current['lot'] = f"{current['lot'] or ''}{', ' if current['lot'] else ''}{row['lot']}"
            if current['status'] == ALLOCATED and row['status'] != ALLOCATED:
                current['status'] = row['status']
    lines = sorted(merged.values(),
                   key=lambda row: (row['key'], row['order'], row['tree'], row['line_no']))
    orders, batches = defaultdict(lambda: {'allocated': 0, 'held': 0, 'lines': 0}), \
                      defaultdict(lambda: {'allocated': 0, 'held': 0, 'orders': set()})
    for row in lines:
        order = orders[row['order']]
        order['allocated'] += row['allocated']
        order['held'] += row['qty'] - row['allocated']
        order['lines'] += 1
        # 未采信街段不属于本次验收批次，不纳入批次签收判定。
        if row['status'] == UNKNOWN_KEY:
            continue
        batch = batches[row['key']]
        batch['allocated'] += row['allocated']
        batch['held'] += row['qty'] - row['allocated']
        batch['orders'].add(row['order'])

    order_rows = []
    for order_id, agg in sorted(orders.items()):
        status = SETTLED if agg['held'] == 0 else BLOCKED if agg['allocated'] == 0 else '部分核销欠苗'
        order_rows.append({'order': order_id, 'allocated': agg['allocated'],
                           'held': agg['held'], 'lines': agg['lines'], 'status': status})
    batch_rows = []
    for key in sorted(accepted_keys | batches.keys()):
        agg = batches.get(key, {'allocated': 0, 'held': 0, 'orders': set()})
        replant_count = sum(1 for identity in facts if identity[0] == key)
        batch_rows.append({'key': key, 'replants': replant_count,
                           'allocated': agg['allocated'], 'held': agg['held'],
                           'orders': len(agg['orders']),
                           'signable': agg['held'] == 0,
                           'status': SETTLED if agg['held'] == 0 else BLOCKED})
    return lines, order_rows, batch_rows


def writeoff(accepted, lots, ready, mode, parse_counts):
    if mode not in MODES:
        raise DataError('BUSINESS', f'核销策略须为 {MODES}')
    facts, _ = _fact_index(accepted)
    accepted_keys = {record['key'] for record in accepted}
    valid, invalid_held = _validate(ready, accepted_keys, facts)
    clean, duplicates = _duplicate_facts(valid)
    dup_held = [_line(line, None, REQ_DUP_TREE, 0) for line in duplicates]
    balances = {lot_id: lot['quantity'] for lot_id, lot in lots.items()}
    allocated, short_held = _allocate(clean, facts, lots, balances, mode)
    lines, order_rows, batch_rows = _rollup(allocated, invalid_held + dup_held, short_held,
                                            accepted_keys, facts)

    lot_rows = [{'lot': lot['lot'], 'species': lot['species'], 'arrived': lot['arrived'],
                 'quantity': lot['quantity'], 'remaining': balances[lot['lot']],
                 'used': lot['quantity'] - balances[lot['lot']]}
                for lot in sorted(lots.values(), key=lambda item: (item['arrived'], item['lot']))]
    if any(row['remaining'] < 0 for row in lot_rows):
        raise RuntimeError('苗批余量出现负数')
    requisition_qty = sum(line['qty'] for line in ready)
    settled_qty = sum(row['allocated'] for row in lines)
    held_qty = sum(row['qty'] - row['allocated'] for row in lines)
    if requisition_qty != settled_qty + held_qty:
        raise RuntimeError('领用数量无法闭合')
    if sum(row['used'] for row in lot_rows) != settled_qty:
        raise RuntimeError('苗批核销数量无法闭合')
    blocked = [row['key'] for row in batch_rows if not row['signable']]
    summary = {'mode': mode, 'mode_label': MODE_LABELS[mode],
               'requisition_lines': parse_counts['parsed'],
               'quarantine_lines': parse_counts['rejected'] + parse_counts['conflicts'],
               'suppressed_lines': parse_counts['suppressed'],
               'duplicate_lines': len(dup_held),
               'ready_lines': len(ready), 'requisition_qty': requisition_qty,
               'settled_qty': settled_qty, 'held_qty': held_qty,
               'held_lines': sum(1 for row in lines if row['allocated'] != row['qty']),
               'blocked_batches': blocked, 'signable': bool(ready) and not blocked}
    return {'summary': summary, 'batches': batch_rows, 'orders': order_rows,
            'lines': lines, 'lots': lot_rows}
