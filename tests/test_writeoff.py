import pytest
from concurrent.futures import ThreadPoolExecutor
from app.errors import DataError
from app.pipeline import stages, execute
from app.modules.runs.service import run
from app.modules.writeoff.ledger import stock
from app.modules.writeoff.requisition import parse_requisitions, split_requisitions
from app.modules.writeoff.service import settle

STOCK = """苗批号,树种,进场日,进场数量
MP-01,白蜡,2026-10-20,3
MP-02,白蜡,2026-11-10,1
MP-03,桂花,2026-09-20,2
MP-04,桂花,2026-11-15,4
""".encode()


def writeoff(source, requisitions, mode='partial', stock_payload=STOCK):
    accepted = stages(source)['accepted']
    return settle(accepted, stock_payload, requisitions.encode(), mode)


def test_fifo_allocates_arrived_lots_only(source):
    # 补植日 2026-11-03：MP-02 在 11-10 才进场，不得追溯扣减。
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,3,
"""
    report = writeoff(source, req)
    lots = {row['lot']: row for row in report['lots']}
    assert (lots['MP-01']['used'], lots['MP-01']['remaining']) == (3, 0)
    assert lots['MP-02']['used'] == 0
    line, = [row for row in report['lines'] if row['order'] == 'LL-1']
    assert line['status'] == '已核销' and line['lot'] == 'MP-01'


def test_balance_never_negative_and_partial_split(source):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,4,
"""
    report = writeoff(source, req)
    assert all(row['remaining'] >= 0 for row in report['lots'])
    line, = [row for row in report['lines'] if row['order'] == 'LL-1']
    assert (line['allocated'], line['status']) == (3, '挂起')
    assert report['summary']['settled_qty'] == 3 and report['summary']['held_qty'] == 1


def test_whole_order_rolls_back_to_keep_order_intact(source):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00107,白蜡07,白蜡,1,
LL-1,1,2026-11-19T09:00:00+08:00,00113,白蜡07,白蜡,1,
LL-2,1,2026-11-19T09:00:00+08:00,00119,白蜡07,白蜡,3,
"""
    partial = writeoff(source, req, 'partial')
    whole = writeoff(source, req, 'whole')
    # partial：LL-1 两株足额，LL-2 在 MP-01 余量上拆成 1 核销 2 挂起
    p_order = {row['order']: row for row in partial['orders']}
    assert (p_order['LL-1']['allocated'], p_order['LL-2']['allocated']) == (2, 1)
    # whole：LL-2 整单退回，MP-01 三株完整留给 LL-1
    w_order = {row['order']: row for row in whole['orders']}
    assert (w_order['LL-1']['allocated'], w_order['LL-2']['allocated']) == (2, 0)
    mp01_whole = next(row for row in whole['lots'] if row['lot'] == 'MP-01')
    assert (mp01_whole['used'], mp01_whole['remaining']) == (2, 1)
    assert all(row['remaining'] >= 0 for row in whole['lots'])


def test_rerun_same_requisition_deducts_once(client):
    # 同一领用单重传：版本仲裁只采信一行，重跑整批不重复扣减。
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,1,首传
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,1,同版重传
LL-1,2,2026-11-20T09:00:00+08:00,00101,白蜡07,白蜡,1,晚到修订
"""
    first = client.post('/api/runs', json={'stock': STOCK.decode(),
                                           'requisitions': req}).json()
    second = client.post('/api/runs', json={'stock': STOCK.decode(),
                                            'requisitions': req}).json()
    assert first == second and len(client.get('/api/runs').json()) == 1
    lot = next(row for row in first['writeoff']['lots'] if row['lot'] == 'MP-01')
    assert lot['used'] == 1
    assert [row['code'] for row in first['writeoff']['suppressed']
            if row['code'] in {'SUPERSEDED', 'EXACT_DUP'}]


def test_held_positions_block_signoff(client):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,9,
"""
    run = client.post('/api/runs', json={'stock': STOCK.decode(),
                                         'requisitions': req}).json()
    assert run['writeoff']['summary']['signable'] is False
    rid = run['manifest']['run_id']
    response = client.post(f'/api/review/{rid}',
                           json={'version': 0, 'decision': '确认', 'note': '尝试签收'})
    assert (response.status_code, response.json()['code']) == (422, 'WRITEOFF_HELD')


def test_no_basis_and_unknown_key_are_held(source):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00103,栾树,栾树,1,该树位未补植
LL-2,1,2026-11-19T09:00:00+08:00,09999,香樟,香樟,1,街段未采信
LL-3,1,2026-11-19T09:00:00+08:00,00102,桂花,白蜡,1,树种发错
"""
    report = writeoff(source, req)
    by_order = {row['order']: row for row in report['lines']}
    assert by_order['LL-1']['status'] == '无补植依据'
    assert by_order['LL-2']['status'] == '街段未采信'
    assert by_order['LL-3']['status'] == '树种不符'
    assert all(row['allocated'] == 0 for row in report['lines'])


def test_duplicate_tree_claim_quarantines_both(source):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00102,桂花,桂花,1,
LL-2,1,2026-11-19T09:00:00+08:00,00102,桂花,桂花,1,重复认领
"""
    report = writeoff(source, req)
    assert report['summary']['duplicate_lines'] == 2
    assert {row['status'] for row in report['lines']} == {'树位重复领用'}


def test_bad_requisition_rows_quarantined(source):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,0,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,1,修订号越界
LL-2,1,2026-11-19T09:00,00101,白蜡07,白蜡,1,缺偏移
LL-3,1,2026-11-19T09:00:00+08:00,00101,白蜡07
"""
    report = writeoff(source, req)
    codes = set(report['reasons'])
    assert {'RANGE', 'TIMESTAMP', 'WIDTH'} <= codes


def test_stock_duplicate_and_header_rejected():
    payload = STOCK.decode() + 'MP-01,白蜡,2026-10-20,9\n'
    with pytest.raises(DataError) as error:
        stock(payload.encode())
    assert error.value.code == 'LOT_CONFLICT'
    with pytest.raises(DataError) as header_error:
        stock('苗批号,树种,进场日\n'.encode())
    assert header_error.value.code in {'HEADER', 'HEADER_ONLY'}


def test_closure_quantities_balance(source):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,2,
LL-2,1,2026-11-19T09:00:00+08:00,00102,桂花,桂花,5,
"""
    report = writeoff(source, req)
    s = report['summary']
    assert s['requisition_qty'] == s['settled_qty'] + s['held_qty']
    assert sum(row['used'] for row in report['lots']) == s['settled_qty']


def test_execute_without_writeoff_inputs_unchanged(source, book):
    report = execute(source, book)
    assert 'writeoff' not in report


def test_requisition_version_conflict_isolated(source):
    parsed, _ = parse_requisitions("""领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,1,
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,栾树,1,同版树种冲突
""".encode())
    _, _, conflicts = split_requisitions(parsed)
    assert len(conflicts) == 2 and {row['code'] for row in conflicts} == {'REQ_CONFLICT'}


def test_concurrent_runs_share_one_record_and_balance(client, source, book):
    req = """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,2,
""".encode()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: run(source, book, STOCK, req, 'partial'), range(4)))
    assert all(item == results[0] for item in results)
    assert len(client.get('/api/runs').json()) == 1
    lot = next(row for row in results[0]['writeoff']['lots'] if row['lot'] == 'MP-01')
    assert lot['used'] == 2 and lot['remaining'] == 1


def test_mode_change_creates_distinct_run(client):
    payload = {'stock': STOCK.decode(),
               'requisitions': """领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,1,
"""}
    partial = client.post('/api/runs', json={**payload, 'mode': 'partial'}).json()
    whole = client.post('/api/runs', json={**payload, 'mode': 'whole'}).json()
    assert partial['manifest']['run_id'] != whole['manifest']['run_id']
    assert len(client.get('/api/runs').json()) == 2


def test_conflicting_tree_does_not_block_sibling():
    # 同单内一个树位同版冲突，另一个树位正常：只隔离冲突树位。
    parsed, _ = parse_requisitions("""领用单号,修订号,提交时间,街段验收单,树位号,树种,数量,原始备注
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,白蜡,1,
LL-1,1,2026-11-19T09:00:00+08:00,00101,白蜡07,栾树,1,冲突行
LL-1,1,2026-11-19T09:00:00+08:00,00102,桂花,桂花,1,正常行
""".encode())
    ready, suppressed, conflicts = split_requisitions(parsed)
    assert [(row['key'], row['tree']) for row in ready] == [('00102', '桂花')]
    assert len(conflicts) == 2 and not suppressed
