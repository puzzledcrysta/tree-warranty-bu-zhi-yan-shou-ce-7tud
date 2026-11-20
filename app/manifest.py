from hashlib import sha256
from app.settings import RULE_VERSION


def manifest(raw, book, stock=None, requisitions=None, mode='partial'):
    source_hash, book_hash = sha256(raw).hexdigest(), sha256(book).hexdigest()
    basis = f'{RULE_VERSION}:{source_hash}:{book_hash}'
    parameters = {'mode': '独立复算'}
    if stock is not None and requisitions is not None:
        stock_hash, req_hash = sha256(stock).hexdigest(), sha256(requisitions).hexdigest()
        basis = f'{basis}:{stock_hash}:{req_hash}:{mode}'
        parameters = {'mode': '苗批核销', 'writeoff_mode': mode}
    run_id = sha256(basis.encode()).hexdigest()
    proof = {'run_id': run_id, 'source_sha256': source_hash, 'book_sha256': book_hash,
             'version': RULE_VERSION, 'parameters': parameters}
    if stock is not None and requisitions is not None:
        proof['stock_sha256'] = sha256(stock).hexdigest()
        proof['requisitions_sha256'] = sha256(requisitions).hexdigest()
    return proof
