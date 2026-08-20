import re

def normalize(s):
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9 ]',' ',s.lower())).strip()

def verify_grounded(response, evidence_items, answer_terms, threshold=0.8):
    resp=normalize(response)
    support=0
    for term in answer_terms:
        if normalize(term) in resp: support += 1
    evidence_text=' '.join(normalize(e.get('text','')) for e in evidence_items)
    unsupported=[t for t in answer_terms if normalize(t) not in evidence_text]
    coverage=support/max(1,len(answer_terms))
    if unsupported:
        return {"decision":"ABSTAIN","score":coverage,"unsupported":unsupported}
    return {"decision":"ACCEPT" if coverage>=threshold else "REJECT","score":coverage,"unsupported":[]}
