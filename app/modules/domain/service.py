from app.errors import DataError
from app.evidence import finding
from app.settings import UNIT
from .rule import evaluate, parse_events, replants


def calculate(records):
    accepted, rejected = [],[]
    for record in records:
        try:
            amount, proof = evaluate(record['fields'])
            cutoff, events = parse_events(record['fields'])
            facts = replants(events)
        except DataError as error:
            rejected.append(finding(record,error.code,str(error)))
            continue
        accepted.append({'key':record['key'],'line':record['line'],'revision':record['revision'],
                         'amount':format(amount,'f'),'unit':UNIT,'raw':record['raw'],
                         'cutoff':cutoff.isoformat(),
                         'replants':[{'tree':item['tree'],'day':item['day'],'species':item['species']}
                                     for item in facts],
                         'proof':[{'metric':label,'value':str(value),'unit':unit} for label,value,unit in proof]})
    return accepted,rejected
