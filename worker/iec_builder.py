import hashlib, json, re

def build_iec(response, evidence_items, task_requirements=None):
    sents=[s.strip() for s in re.split(r'(?<=[.!?])\s+', response.strip()) if s.strip()]
    claims=[]
    for i,s in enumerate(sents):
        claims.append({"id":i,"text":s,"evidence_ids":[e["id"] for e in evidence_items if any(k.lower() in s.lower() for k in e.get("keywords",[]))],"uncertainty":None})
    iec={"claims":claims,"evidence":evidence_items,"requirements":task_requirements or [],"coverage":{r:[] for r in (task_requirements or [])}}
    blob=json.dumps(iec,sort_keys=True).encode()
    iec["root"]=hashlib.sha256(blob).hexdigest()
    return iec
