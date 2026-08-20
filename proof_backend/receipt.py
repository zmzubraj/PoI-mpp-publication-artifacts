from dataclasses import dataclass, asdict
import json, hashlib
@dataclass
class Receipt:
    task_id:int; worker:str; commitment:str; score:float; assurance:int; epoch:int; da_ok:bool; challenged:bool=False
    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()
