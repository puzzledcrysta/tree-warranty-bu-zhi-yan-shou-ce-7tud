from collections import defaultdict
from app.errors import DataError
from app.evidence import finding
from app.modules.domain.values import whole, instant
from .ledger import REQUISITION_FIELDS, MISSING, _rows


def parse_requisitions(payload):
    """解析领用 CSV，坏行隔离；返回结构化行与隔离行。"""
    parsed, rejected = [], []
    for line, raw in _rows(payload, REQUISITION_FIELDS):
        if not raw or not any(value.strip() for value in raw):
            continue
        if len(raw) != len(REQUISITION_FIELDS):
            rejected.append(finding({'line': line, 'raw': raw}, 'WIDTH',
                                    f'{len(raw)} 列，应为 {len(REQUISITION_FIELDS)} 列'))
            continue
        order, revision, stamp, key, tree, species, raw_qty, note = (value.strip() for value in raw)
        record = {'line': line, 'raw': raw, 'order': order, 'revision': None,
                  'key': key, 'tree': tree, 'species': species, 'note': note}
        try:
            if (order in MISSING or tree in MISSING or raw_qty in MISSING
                    or key in MISSING or species in MISSING):
                raise DataError('REQUIRED', '领用单号、街段验收单、树位号、树种和数量均须填写')
            if revision.casefold() in MISSING:
                raise DataError('REQUIRED', '修订号须填写，重传需按版本仲裁')
            record['revision'] = whole(revision, 1, 10 ** 9)
            if stamp.casefold() in MISSING:
                raise DataError('REQUIRED', '提交时间须填写')
            record['time'] = instant(stamp).isoformat()
            record['qty'] = whole(raw_qty, 1, 10 ** 9)
        except DataError as error:
            rejected.append(finding(record, error.code, str(error)))
            continue
        parsed.append(record)
    if not parsed and not rejected:
        raise DataError('HEADER_ONLY', '领用册没有数据行')
    return parsed, rejected


def split_requisitions(records):
    """按领用单号做版本仲裁，规则与来源质量模块一致：
    同版重复只保留最早行，旧版抑制，最高版同树位内容冲突只隔离该树位。
    一张领用单可含多个树位、跨多个街段。"""
    groups = defaultdict(list)
    for record in records:
        groups[record['order']].append(record)
    ready, suppressed, conflicts = [], [], []
    for order, group in sorted(groups.items()):
        latest = max(row['revision'] for row in group)
        candidates = sorted((row for row in group if row['revision'] == latest),
                            key=lambda row: row['line'])
        older = [row for row in group if row['revision'] != latest]
        suppressed.extend(finding(row, 'SUPERSEDED', f'修订 {latest} 取代旧版本') for row in older)
        identities = [(row['key'], row['tree']) for row in candidates]
        if len(set(identities)) == len(identities):
            ready.extend(candidates)
            continue
        # 同版重传：同树位同内容只保留最早行；内容不同则该树位隔离，其余树位照常采信。
        by_tree = defaultdict(list)
        for row in candidates:
            by_tree[(row['key'], row['tree'])].append(row)
        for rows in by_tree.values():
            if len(rows) == 1:
                ready.extend(rows)
            elif len({(row['species'], row['qty']) for row in rows}) > 1:
                conflicts.extend(finding(row, 'REQ_CONFLICT',
                                         f'{order} 最高修订 {latest} 同树位内容冲突')
                                 for row in rows)
            else:
                ready.append(rows[0])
                suppressed.extend(finding(row, 'EXACT_DUP',
                                          f'{order} 同为修订 {latest}，保留第 {rows[0]["line"]} 行')
                                  for row in rows[1:])
    return ready, suppressed, conflicts
