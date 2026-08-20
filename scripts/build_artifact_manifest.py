"""Build a reproducibility manifest from configured result files."""
from pathlib import Path
import hashlib, json

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'results'
OUT=RESULTS/'artifact_manifest.json'

rows=[]
for p in sorted(RESULTS.rglob('*')):
    if p.is_file() and p.name != OUT.name:
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        rows.append({"path":str(p.relative_to(ROOT)),"sha256":h,"bytes":p.stat().st_size})
OUT.write_text(json.dumps({"files":rows},indent=2),encoding='utf-8')
print(f"wrote {OUT} with {len(rows)} files")
