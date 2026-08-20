import hashlib

def derive_seed(epoch_beacon, task_root, response_commitment, audit_round=0):
    s=f"POI_AUDIT|{epoch_beacon}|{task_root}|{response_commitment}|{audit_round}".encode()
    return int.from_bytes(hashlib.sha256(s).digest(),"big")
