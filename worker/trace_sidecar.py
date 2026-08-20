import hashlib, json, time

def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

class TraceSidecar:
    def __init__(self):
        self.events=[]
    def record(self, op, inputs, output, meta=None):
        evt={"i":len(self.events),"op":op,"inputs":inputs,"output":output,"meta":meta or {},"ts":time.time_ns()}
        evt["hash"]=h(canonical(evt))
        self.events.append(evt)
        return evt
    def root(self):
        if not self.events: return h(b"")
        level=[bytes.fromhex(e["hash"]) for e in self.events]
        while len(level)>1:
            if len(level)%2: level.append(level[-1])
            level=[hashlib.sha256(level[i]+level[i+1]).digest() for i in range(0,len(level),2)]
        return level[0].hex()
    def dump(self,path):
        with open(path,'w') as f: json.dump({"root":self.root(),"events":self.events},f,indent=2)
