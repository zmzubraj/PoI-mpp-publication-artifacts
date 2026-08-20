import hashlib, json

def h(x: bytes): return hashlib.sha256(x).hexdigest()
def commit_response(task_root, model_root, response, trace_root, evidence_root, artifact_root, nonce):
    obj={"task_root":task_root,"model_root":model_root,"response_hash":h(response.encode()),"trace_root":trace_root,"evidence_root":evidence_root,"artifact_root":artifact_root,"nonce":nonce}
    return h(json.dumps(obj,sort_keys=True,separators=(",",":")).encode())
