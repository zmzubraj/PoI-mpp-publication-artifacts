"""Scaffold for E7. Real gas values must come from Foundry/Anvil, not synthetic numbers."""
import argparse, csv
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--out',required=True); a=p.parse_args()
Path(a.out).parent.mkdir(parents=True,exist_ok=True)
with open(a.out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['call','gas_median','gas_p95','storage_delta_bytes'])
print('E7 scaffold created; populate from actual Foundry gas snapshots.')
