from app.evidence import distribution
from .ledger import stock
from .requisition import parse_requisitions, split_requisitions
from .engine import writeoff


def settle(accepted, stock_payload, requisition_payload, mode):
    lots = stock(stock_payload)
    parsed, rejected = parse_requisitions(requisition_payload)
    ready, suppressed, conflicts = split_requisitions(parsed)
    quarantine = sorted([*rejected, *conflicts], key=lambda row: row['line'])
    parse_counts = {'parsed': len(parsed), 'rejected': len(rejected),
                    'suppressed': len(suppressed), 'conflicts': len(conflicts)}
    report = writeoff(accepted, lots, ready, mode, parse_counts)
    report['quarantine'] = quarantine
    report['suppressed'] = suppressed
    report['reasons'] = distribution(quarantine)
    return report
