import json
from app.errors import DataError
from app.store import connection


def lookup(db,run_id):
    row = db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
    if row is None:
        raise DataError('RUN_UNKNOWN','没有此批次',404)
    return row


def extra(db,run_id):
    return db.execute('SELECT * FROM runs_extra WHERE run_id=?',(run_id,)).fetchone()


def fetch(run_id):
    with connection() as db:
        return lookup(db,run_id)


def fetch_extra(run_id):
    with connection() as db:
        row = extra(db,run_id)
        return dict(row) if row is not None else None


def persist(run_id,source,book,result,created,stock=None,requisitions=None,mode='partial'):
    with connection() as db:
        db.execute('INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?)',
                   (run_id,source,book,json.dumps(result,ensure_ascii=False),created))
        if stock is not None and requisitions is not None:
            db.execute('INSERT OR IGNORE INTO runs_extra(run_id,stock,requisitions,mode) VALUES (?,?,?,?)',
                       (run_id,stock,requisitions,mode))
        return lookup(db,run_id)


def history():
    with connection() as db:
        return [dict(row) for row in db.execute('SELECT id,created FROM runs ORDER BY created DESC,id DESC LIMIT 50')]
