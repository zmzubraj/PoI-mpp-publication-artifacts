# E3-v2 Phase-3 accountable-human operator runbook

**Status:** executable through development-dataset sealing, policy/model collection, and accountable signatures. The Phase-3 engineering artifacts and adversarial tests are implemented. The single canonical gate is `WAITING_EXTERNAL_ENGINEERING_REVIEW`; no real inference or calibration freeze is authorized until a real independent reviewer returns a verified, hash-bound signed record.

**Audience:** the two real humans who will curate and independently annotate the E3-v2 development set, plus a third adjudicator if any annotation disagreement occurs.

**Scientific boundary:** this is development calibration, not confirmatory evidence. It cannot support C3-v2, replace the historical C3-v1 `NOT_SUPPORTED` result, or authorize the 500-item confirmatory run.

## 1. Non-negotiable rules

1. Use 120–150 unique development items: exactly 50 final `ACCEPT`, exactly 50 final `REJECT`, and 20–50 final `ABSTAIN`.
2. Both primary annotators must label every unique item independently and without seeing model outputs or each other's labels.
3. Never change an annotation after seeing model behavior.
4. Any disagreement requires a third human adjudicator who is distinct from both annotators. Do not negotiate a two-person consensus after unblinding.
5. Items, labels, annotations, policies, model identity, runtime, and every later observation must be hash-bound.
6. Real development observations must use `REAL_MODEL_EXECUTION`. Synthetic fixtures remain `SYNTHETIC_NON_EVIDENCE` and may test plumbing only.
7. All data in the current sealer must genuinely be `CC-BY-4.0` and `AUTHORIZED_PUBLIC`. If any item has a different license or privacy status, stop. The sealer currently hard-codes those two values and must be extended before that item can be used.
8. Use one primary unquantized 1B–3B open-weight model. Do not use 7B–8B as the primary model. Do not use 70B/MoE, TEE/confidential GPU, cloud inference APIs, or a production dispute VM.
9. Model acquisition may use the network. Actual development inference must be offline/local-only after the model files and wheels are present and hashed.
10. Do not run `scripts/run_e3_v2_real_model.py` for Phase 3. It is the 500-item confirmatory runner and is deliberately blocked.
11. Do not run or copy the untracked `scripts/e3_v2_evaluator_workflow.py`. It is not an approved workflow.
12. Private keys never enter the repository, bundle, chat, email body, or shared archive.

## 2. Human roles and independence

Record legal/accountable identity out of band. Stable IDs in files are references, not proof of identity.

| Role | Minimum responsibility | Prohibited action |
|---|---|---|
| Human A — owner/annotator A | source and license custody; independent annotation; local package ownership | viewing B's annotations before both freezes |
| Human B — reviewer/annotator B | independent annotation; license/policy/model review; second package signature | viewing A's annotations before both freezes |
| Human C — adjudicator, conditional | resolves only A/B disagreements after both annotation sets are frozen | being A or B; altering agreed rows |

Two people can close the annotation gate only if A and B agree on every item. If there is one or more disagreement and Human C is unavailable, status is `WAITING_EXTERNAL_ADJUDICATOR`.

Before work begins, each human creates a signed role declaration containing:

- full name and stable ID;
- role;
- organization/relationship to the project;
- conflict-of-interest statement;
- statement that annotations were created without model-output access;
- date, timezone, public-key fingerprint, and signature namespace;
- identity-binding method used outside the bundle.

Cryptographic validity proves control of a key, not the person's real-world identity or scientific independence. The project owner must verify those facts separately.

## 3. Machines, paths, and initial variables

Run commands from a clean terminal on the local execution machine. Replace every value inside angle brackets before pressing Enter.

```bash
export POI_REPO='/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts'
export E3_EXTERNAL='/Users/<ACCOUNT>/Documents/POI_E3_V2_EXTERNAL'
export E3_DEV="$E3_EXTERNAL/POI_E3_V2_DEVELOPMENT"
export WORKSHEET="$E3_EXTERNAL/worksheet"
export SEALED_DATASET="$E3_EXTERNAL/sealed-dataset"
export HUMAN_A_ID='<stable-human-a-id>'
export HUMAN_B_ID='<stable-human-b-id>'
export DATASET_ID='<stable-e3-v2-development-id>'
export MODEL_REPO='<owner/model-repository>'
export MODEL_REVISION='<40-character-lowercase-commit>'
export TOKENIZER_REPO='<owner/tokenizer-repository>'
export TOKENIZER_REVISION='<40-character-lowercase-commit>'
export HF_CACHE="$E3_EXTERNAL/hf-cache"
export PY="$POI_REPO/.venv/bin/python"
```

Fail immediately if a placeholder remains:

```bash
env | grep -E '^(E3_EXTERNAL|HUMAN_[AB]_ID|DATASET_ID|MODEL_REPO|MODEL_REVISION|TOKENIZER_REPO|TOKENIZER_REVISION)=' | grep '<' && {
  echo 'STOP: unresolved placeholder'; exit 1;
}
case "$HUMAN_A_ID:$HUMAN_B_ID:$DATASET_ID" in
  (*[!a-z0-9:-]*|'') echo 'STOP: stable IDs must use lowercase letters, digits, and hyphens'; exit 1;;
esac
```

Create external directories with owner-only permissions:

```bash
umask 077
install -d -m 700 "$E3_EXTERNAL" "$E3_DEV" "$HF_CACHE"
install -d -m 700 \
  "$E3_DEV/model" "$E3_DEV/dataset" "$E3_DEV/policy" \
  "$E3_DEV/execution" "$E3_DEV/signatures" "$E3_EXTERNAL/custody"
```

The repository and external root must not contain symlink components:

```bash
"$PY" - "$POI_REPO" "$E3_EXTERNAL" <<'PY'
import os, sys
from pathlib import Path
for raw in sys.argv[1:]:
    path = Path(os.path.abspath(raw))
    probe = Path(path.anchor)
    for part in path.parts[1:]:
        probe /= part
        if probe.is_symlink():
            raise SystemExit(f'STOP: symlink component: {probe}')
print('PASS: no symlink components')
PY
```

## 4. Pin and verify repository state

```bash
cd "$POI_REPO"
git rev-parse HEAD | tee "$E3_EXTERNAL/custody/repository_commit.txt"
git status --short
git log -2 --oneline
test ! -e "$POI_REPO/scripts/e3_v2_evaluator_workflow.py" || {
  echo 'STOP: unapproved untracked evaluator workflow is present; use a verified clean checkout'; exit 1;
}
"$PY" -m pytest -q \
  tests/experiments/test_e3_annotation_worksheet.py \
  tests/semantic/test_calibration_v2.py \
  tests/experiments/test_e3_phase3_development.py
```

Stop if tracked files are modified or tests fail. Historical untracked result directories are not inputs to this Phase-3 package.

Record tool versions:

```bash
{
  "$PY" --version
  "$PY" -c 'import torch,transformers,huggingface_hub; print("torch",torch.__version__); print("transformers",transformers.__version__); print("huggingface_hub",huggingface_hub.__version__)'
  git --version
  ssh -V
  uname -a
} > "$E3_EXTERNAL/custody/tool_versions.txt" 2>&1
shasum -a 256 "$E3_EXTERNAL/custody/tool_versions.txt" > "$E3_EXTERNAL/custody/tool_versions.txt.sha256"
```

## 5. Model selection, license review, and local deployment preparation

Humans A and B must jointly record, before download:

- why the model is within 1B–3B and appropriate for the task;
- exact repository and 40-character commit;
- tokenizer repository and exact commit;
- model license and permitted research/publication use;
- unquantized safetensors availability;
- expected RAM/VRAM/disk requirement;
- no remote inference/API dependency;
- whether model access requires accepting additional terms.

Dry-run the download:

```bash
cd "$POI_REPO"
"$POI_REPO/.venv/bin/hf" download "$MODEL_REPO" \
  --revision "$MODEL_REVISION" --cache-dir "$HF_CACHE" --dry-run
```

Download the exact snapshot. Do not pass a token on the command line; authenticate separately only if the humans are authorized to accept the model's terms.

```bash
"$POI_REPO/.venv/bin/hf" download "$MODEL_REPO" \
  --revision "$MODEL_REVISION" --cache-dir "$HF_CACHE"

if [ "$TOKENIZER_REPO" != "$MODEL_REPO" ] || [ "$TOKENIZER_REVISION" != "$MODEL_REVISION" ]; then
  "$POI_REPO/.venv/bin/hf" download "$TOKENIZER_REPO" \
    --revision "$TOKENIZER_REVISION" --cache-dir "$HF_CACHE"
fi
```

Confirm offline loading only after the cache is populated:

```bash
export HF_HOME="$HF_CACHE"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
"$PY" - <<'PY'
import os
from transformers import AutoConfig, AutoTokenizer
model = os.environ['MODEL_REPO']
model_rev = os.environ['MODEL_REVISION']
tok = os.environ['TOKENIZER_REPO']
tok_rev = os.environ['TOKENIZER_REVISION']
AutoConfig.from_pretrained(model, revision=model_rev, local_files_only=True)
AutoTokenizer.from_pretrained(tok, revision=tok_rev, local_files_only=True)
print('PASS: exact model configuration and tokenizer load offline')
PY
```

Do not start inference. Hash all resolved model/tokenizer files and preserve a wheel/runtime ledger. The final `model_file_hashes` and `tokenizer_file_hashes` maps must use unique basenames and lowercase SHA-256 digests; at least one model filename must end in `.safetensors`, and `.bin`, `.pt`, `.pth`, and `.ckpt` are forbidden.

Create a read-only cache inventory for later human classification into model and tokenizer files:

```bash
find "$HF_CACHE" -type f -print0 | sort -z | xargs -0 shasum -a 256 \
  > "$E3_EXTERNAL/custody/hf_cache_files.sha256"
grep -Ei '\.(bin|pt|pth|ckpt)([[:space:]]|$)' "$E3_EXTERNAL/custody/hf_cache_files.sha256" && {
  echo 'STOP: forbidden weight format present in selected inventory'; exit 1;
}
```

## 6. Collect the 120–150 real development items

Create `$E3_EXTERNAL/raw_items.jsonl`. Each line is one UTF-8 JSON object:

```json
{"source_id":"stable-source-id","text":"the exact item shown to annotators","evidence":"source or ground-truth reference","error_family":"BASELINE","subgroup":"core","difficulty":"standard"}
```

Collection rules:

1. Use independent items as the unit; repeated generations of one item do not increase `n`.
2. Preserve the original source separately and record its SHA-256.
3. Record source family, acquisition date, license URL/document, privacy review, and any transformation.
4. Remove direct identifiers and confidential material before annotation.
5. Include terminology and difficulty variation, but do not select items after model inspection.
6. Do not include confirmatory items or items derived from a future confirmatory set.
7. Do not duplicate text to reach the target count. The compiler deduplicates by text content.
8. The expected composition is based on final human labels after independent annotation, not on model output.

Validate JSONL syntax and count:

```bash
"$PY" - "$E3_EXTERNAL/raw_items.jsonl" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1]); rows=[]
for n,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
    if not line.strip(): continue
    row=json.loads(line)
    for key in ('source_id','text','evidence','error_family','subgroup','difficulty'):
        if not isinstance(row.get(key),str) or not row[key].strip():
            raise SystemExit(f'STOP: line {n} missing {key}')
    rows.append(row)
if not 120 <= len(rows) <= 170:
    raise SystemExit(f'STOP: raw count {len(rows)} is outside collection allowance 120..170')
print('raw_count',len(rows))
PY
```

The temporary upper allowance of 170 permits deduplication loss. The sealed unique set must still be 120–150.

## 7. Freeze policy files before annotation

Humans A and B must review and freeze these exact files before annotations begin:

```text
policy/claim_spec.json
policy/prompt_template.txt
policy/output_schema.json
policy/contradiction_policy.json
policy/error_recovery_policy.json
policy/error_taxonomy_review.json
```

The files must define, at minimum:

- the scoped C3-v2 development question and prohibited generalizations;
- the exact prompt presented during later local inference;
- output fields and valid ranges for `decision`, `support_fraction`, and `calibrated_confidence`;
- multiple-decision and contradiction handling;
- unparseable/error behavior, always fail-closed to `ABSTAIN`;
- canonical error-code/family mapping;
- reviewer IDs, review dates, revision, and source hashes.

Copy the reviewed files into `$E3_DEV/policy/`. Do not use `TEST_ONLY` fixture policies from `tests/`.

Canonicalize JSON policy files:

```bash
"$PY" - "$E3_DEV/policy" <<'PY'
import json, os, sys, tempfile
from pathlib import Path
root=Path(sys.argv[1])
for p in sorted(root.glob('*.json')):
    obj=json.loads(p.read_text(encoding='utf-8'))
    data=json.dumps(obj,allow_nan=False,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()
    fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.'+p.name+'.')
    with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,p)
print('PASS: policy JSON canonicalized')
PY
```

Hash the frozen claim specification:

```bash
export CLAIM_SPEC_HASH="$(shasum -a 256 "$E3_DEV/policy/claim_spec.json" | awk '{print $1}')"
printf '%s\n' "$CLAIM_SPEC_HASH" | tee "$E3_EXTERNAL/custody/claim_spec_hash.txt"
```

## 8. Compile the blind worksheet

The exact final composition is not yet known, so compile without `allocation`; the sealer will enforce the final decisions supplied later.

```bash
test ! -e "$WORKSHEET" || { echo 'STOP: choose a new worksheet revision path'; exit 1; }
"$PY" - "$E3_EXTERNAL/raw_items.jsonl" "$E3_DEV/policy/claim_spec.json" "$WORKSHEET" "$DATASET_ID" <<'PY'
import sys
from pathlib import Path
from poi_mpp.experiments.e3_annotation_worksheet import AnnotationWorksheetCompiler
result=AnnotationWorksheetCompiler.build(
    items_path=Path(sys.argv[1]), claim_spec_path=Path(sys.argv[2]),
    split='DEVELOPMENT', dataset_id=sys.argv[4], output_root=Path(sys.argv[3]),
)
m=result['manifest']
print('record_count',m['record_count'])
print('unique_record_count',m['unique_record_count'])
print('duplicate_record_count',m['duplicate_record_count'])
if not 120 <= m['unique_record_count'] <= 150:
    raise SystemExit('STOP: unique development count must be 120..150')
PY
```

Record worksheet hashes:

```bash
find "$WORKSHEET" -type f -print0 | sort -z | xargs -0 shasum -a 256 \
  > "$E3_EXTERNAL/custody/worksheet_files.sha256"
shasum -a 256 "$WORKSHEET/manifest.json" "$WORKSHEET/items.jsonl"
```

## 9. Prepare two blind annotation packets

Each human receives the same frozen item text and record ID but not metadata that reveals a proposed label, the other person's annotations, or model output.

```bash
"$PY" - "$WORKSHEET" "$E3_EXTERNAL" <<'PY'
import csv, json, sys
from pathlib import Path
worksheet=Path(sys.argv[1]); out=Path(sys.argv[2])
rows=[]
seen=set()
for line in (worksheet/'items.jsonl').read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    item=json.loads(line); text=item['text']
    import hashlib
    h=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if h in seen: continue
    seen.add(h); rid=f'dev-{len(rows):04d}'
    rows.append({'record_id':rid,'text':text,'decision':'','rationale_reference':'','annotator_notes':''})
for suffix in ('A','B'):
    p=out/f'annotation_packet_{suffix}.csv'
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
print('packet_rows',len(rows))
PY
shasum -a 256 "$E3_EXTERNAL/annotation_packet_A.csv" "$E3_EXTERNAL/annotation_packet_B.csv"
```

Human A gets only packet A. Human B gets only packet B. Each annotator fills every `decision` with exactly one of `ACCEPT`, `REJECT`, or `ABSTAIN`, adds a concise evidence/rationale reference, then freezes and signs the completed CSV.

## 10. Import independent annotations

After both signed packet hashes are received, one custodian imports them. Do not edit the CSVs during import.

```bash
"$PY" - "$WORKSHEET" "$E3_EXTERNAL/annotation_packet_A.csv" "$HUMAN_A_ID" <<'PY'
import csv,json,sys
from pathlib import Path
root=Path(sys.argv[1]); packet=Path(sys.argv[2]); annotator=sys.argv[3]
out=root/'annotations'; out.mkdir(exist_ok=True)
for row in csv.DictReader(packet.open(encoding='utf-8')):
    decision=row['decision'].strip().upper(); rid=row['record_id'].strip()
    if decision not in {'ACCEPT','REJECT','ABSTAIN'}: raise SystemExit(f'STOP: invalid {rid}')
    payload={'annotator_id':annotator,'decision':decision,'record_id':rid}
    (out/f'{rid}-{annotator}.json').write_bytes(json.dumps(payload,allow_nan=False,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode())
PY

"$PY" - "$WORKSHEET" "$E3_EXTERNAL/annotation_packet_B.csv" "$HUMAN_B_ID" <<'PY'
import csv,json,sys
from pathlib import Path
root=Path(sys.argv[1]); packet=Path(sys.argv[2]); annotator=sys.argv[3]
out=root/'annotations'; out.mkdir(exist_ok=True)
for row in csv.DictReader(packet.open(encoding='utf-8')):
    decision=row['decision'].strip().upper(); rid=row['record_id'].strip()
    if decision not in {'ACCEPT','REJECT','ABSTAIN'}: raise SystemExit(f'STOP: invalid {rid}')
    payload={'annotator_id':annotator,'decision':decision,'record_id':rid}
    (out/f'{rid}-{annotator}.json').write_bytes(json.dumps(payload,allow_nan=False,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode())
PY
```

## 11. Identify disagreements and obtain adjudication

```bash
"$PY" - "$WORKSHEET" "$HUMAN_A_ID" "$HUMAN_B_ID" "$E3_EXTERNAL/disagreements.csv" <<'PY'
import csv,json,sys
from pathlib import Path
root=Path(sys.argv[1]); a,b=sys.argv[2:4]; out=Path(sys.argv[4]); rows=[]
for pa in sorted((root/'annotations').glob(f'*-{a}.json')):
    rid=pa.name.removesuffix(f'-{a}.json'); pb=root/'annotations'/f'{rid}-{b}.json'
    if not pb.is_file(): raise SystemExit(f'STOP: missing B annotation for {rid}')
    da=json.loads(pa.read_bytes())['decision']; db=json.loads(pb.read_bytes())['decision']
    if da != db: rows.append({'record_id':rid,'annotator_a_decision':da,'annotator_b_decision':db,'adjudicator_decision':''})
with out.open('w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=('record_id','annotator_a_decision','annotator_b_decision','adjudicator_decision')); w.writeheader(); w.writerows(rows)
print('disagreements',len(rows))
PY
```

- If the count is zero, no adjudicator is needed.
- If the count is positive, stop until Human C reviews only the disputed items and supplies a signed decision for each.
- Human C's stable ID must differ from A and B.

Import Human C's completed disagreement CSV:

```bash
export HUMAN_C_ID='<stable-human-c-id>'
"$PY" - "$WORKSHEET" "$E3_EXTERNAL/disagreements.csv" "$HUMAN_C_ID" <<'PY'
import csv,json,sys
from pathlib import Path
root=Path(sys.argv[1]); packet=Path(sys.argv[2]); adjudicator=sys.argv[3]
if adjudicator.startswith('<'): raise SystemExit('STOP: missing Human C ID')
out=root/'adjudications'; out.mkdir(exist_ok=True)
for row in csv.DictReader(packet.open(encoding='utf-8')):
    decision=row['adjudicator_decision'].strip().upper(); rid=row['record_id'].strip()
    if decision not in {'ACCEPT','REJECT','ABSTAIN'}: raise SystemExit(f'STOP: invalid adjudication {rid}')
    payload={'adjudicator_id':adjudicator,'decision':decision,'record_id':rid}
    (out/f'{rid}.json').write_bytes(json.dumps(payload,allow_nan=False,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode())
PY
```

## 12. Build the final decision ledger and check composition

```bash
"$PY" - "$WORKSHEET" "$HUMAN_A_ID" "$HUMAN_B_ID" "$E3_EXTERNAL/decisions.jsonl" <<'PY'
import json,sys
from collections import Counter
from pathlib import Path
root=Path(sys.argv[1]); a,b=sys.argv[2:4]; out=Path(sys.argv[4]); rows=[]
for pa in sorted((root/'annotations').glob(f'*-{a}.json')):
    rid=pa.name.removesuffix(f'-{a}.json'); pb=root/'annotations'/f'{rid}-{b}.json'
    da=json.loads(pa.read_bytes())['decision']; db=json.loads(pb.read_bytes())['decision']
    if da == db: final=da
    else:
        adj=root/'adjudications'/f'{rid}.json'
        if not adj.is_file(): raise SystemExit(f'STOP: missing adjudication for {rid}')
        final=json.loads(adj.read_bytes())['decision']
    rows.append({'record_id':rid,'decision':final})
counts=Counter(row['decision'] for row in rows)
if counts != Counter({'ACCEPT':50,'REJECT':50,'ABSTAIN':len(rows)-100}):
    raise SystemExit(f'STOP: final composition invalid: {dict(counts)}')
if not 20 <= counts['ABSTAIN'] <= 50: raise SystemExit('STOP: ABSTAIN must be 20..50')
out.write_text('\n'.join(json.dumps(r,separators=(',',':'),sort_keys=True) for r in rows)+'\n',encoding='utf-8')
print(dict(counts), 'total',len(rows))
PY
```

Do not delete items merely to force composition after labels are known. If the frozen corpus does not yield the required composition, record the failed attempt and construct a new, independently frozen dataset revision before any model execution.

## 13. Create the license/privacy ledger

Create `$E3_EXTERNAL/license_privacy_ledger.json` with one row per final record:

```json
{"schema_version":"POI_MPP_E3_LICENSE_PRIVACY_LEDGER_V1","rows":[{"record_id":"dev-0000","license_id":"CC-BY-4.0","privacy_status":"AUTHORIZED_PUBLIC","source_reference":"immutable source reference","authorization_reference":"human-reviewed authorization reference"}]}
```

Every row must be truthful. If even one row is not `CC-BY-4.0` and `AUTHORIZED_PUBLIC`, stop and request a sealer schema/code revision.

Canonicalize and count-check:

```bash
"$PY" - "$E3_EXTERNAL/license_privacy_ledger.json" "$E3_EXTERNAL/decisions.jsonl" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); d=Path(sys.argv[2]); obj=json.loads(p.read_text(encoding='utf-8'))
ids=[r['record_id'] for r in obj['rows']]
expected=[json.loads(x)['record_id'] for x in d.read_text().splitlines() if x.strip()]
if sorted(ids) != sorted(expected) or len(ids) != len(set(ids)): raise SystemExit('STOP: license ledger record closure failed')
for r in obj['rows']:
    if r['license_id']!='CC-BY-4.0' or r['privacy_status']!='AUTHORIZED_PUBLIC': raise SystemExit(f"STOP: unsupported license/privacy for {r['record_id']}")
p.write_bytes(json.dumps(obj,allow_nan=False,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode())
print('PASS: license/privacy rows',len(ids))
PY
```

## 14. Seal the annotated dataset

```bash
test ! -e "$SEALED_DATASET" || { echo 'STOP: choose a new sealed-dataset revision path'; exit 1; }
"$PY" - "$WORKSHEET" "$CLAIM_SPEC_HASH" "$HUMAN_A_ID" "$HUMAN_B_ID" \
  "$E3_EXTERNAL/decisions.jsonl" "$E3_EXTERNAL/license_privacy_ledger.json" "$SEALED_DATASET" <<'PY'
import json,sys
from pathlib import Path
from poi_mpp.experiments.e3_annotation_worksheet import AnnotatedDatasetSealer
worksheet,claim,a,b,decisions,license_path,out=sys.argv[1:]
rows=[json.loads(x) for x in Path(decisions).read_text(encoding='utf-8').splitlines() if x.strip()]
bundle=AnnotatedDatasetSealer(
    worksheet_root=Path(worksheet), claim_spec_hash=claim, annotator_ids=(a,b)
).seal(
    output_root=Path(out), decisions_source=[(r['record_id'],r['decision']) for r in rows],
    license_ledger_path=Path(license_path), evidence_origin='REAL_MODEL_EXECUTION',
)
print(bundle.dataset_root)
PY
```

Copy the sealed dataset as a new directory; do not merge it over an older revision:

```bash
test -d "$E3_DEV/dataset" || { echo 'STOP: dataset destination is missing'; exit 1; }
test -z "$(find "$E3_DEV/dataset" -mindepth 1 -print -quit)" || {
  echo 'STOP: dataset destination is not empty; choose a new E3_DEV revision'; exit 1;
}
cp -R "$SEALED_DATASET/." "$E3_DEV/dataset/"
```

## 15. Prepare model/decode drafts and record the environment HOLD

Create these canonical files using real measured values:

```text
model/pinned_model_manifest.json
execution/deterministic_decode_policy.json
model/file_hashes.sha256
```

Required model fields:

```json
{"schema_version":"POI_MPP_WORKER_MODEL_MANIFEST_V1","model_id":"stable-public-id","repository":"owner/model","revision":"40-char-commit","tokenizer_id":"owner/tokenizer","tokenizer_revision":"40-char-commit","license_id":"reviewed-license-id","parameter_scale":"1B|1.5B|2B|3B","precision":"bfloat16|float16|float32","quantization":"none","runtime_name":"transformers","runtime_version":"measured-version","model_file_hashes":{"weights.safetensors":"sha256"},"tokenizer_file_hashes":{"tokenizer.json":"sha256"},"assurance_class":1}
```

Required deterministic decode fields:

```json
{"schema_version":"POI_MPP_DETERMINISTIC_DECODE_V1","seed":7,"max_new_tokens":96,"do_sample":false,"temperature":0.0,"top_p":1.0,"top_k":0,"repetition_penalty":1.0,"stop_sequences":[]}
```

The values `7` and `96` are examples, not defaults. Humans must freeze the actual seed and token limit before execution.

Do **not** create `execution/environment_manifest.json` or the final `owner_declaration.json` yet. The environment schema requires hashes for the real development runner and artifact exporter. Those programs do not currently exist, so supplying substitute or placeholder hashes would be false provenance. After the engineering batch exists, the environment manifest must bind the same model/tokenizer revisions, seed, maximum tokens, dependency-lock hash, SBOM digest, hardware/driver inventory, real development runner and exporter hashes, protocol/config hashes, `network_access: "LOCAL_ONLY"`, and an empty `external_services` list. The final owner declaration must then cite those reviewed artifacts and use different `owner_id` and `accountable_reviewer_id` values.

Validate schemas before continuing:

```bash
"$PY" - "$E3_DEV" <<'PY'
import json,sys
from pathlib import Path
from poi_mpp.worker.model_manifest import PinnedModelManifest
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
root=Path(sys.argv[1])
PinnedModelManifest.model_validate(json.loads((root/'model/pinned_model_manifest.json').read_bytes()))
DeterministicDecodePolicy.model_validate(json.loads((root/'execution/deterministic_decode_policy.json').read_bytes()))
print('PASS: model/decode schemas; environment remains WAITING_ENGINEERING')
PY
```

## 16. Sign human declarations and frozen annotation packets

Each human generates and retains their own private key outside the repository and shared bundle:

```bash
export HUMAN_SIGNER_ID='<stable-human-id-for-this-signing-step>'
case "$HUMAN_SIGNER_ID" in (*'<'*|''|*[!a-z0-9-]*) echo 'STOP: invalid signer ID'; exit 1;; esac
install -d -m 700 "$HOME/.ssh/poi-e3-v2"
ssh-keygen -t ed25519 -f "$HOME/.ssh/poi-e3-v2/$HUMAN_SIGNER_ID" -C "$HUMAN_SIGNER_ID"
ssh-keygen -lf "$HOME/.ssh/poi-e3-v2/$HUMAN_SIGNER_ID.pub"
```

Human A signs A's role declaration and annotation packet; Human B signs B's equivalents. Human C signs the adjudication packet if used:

```bash
ssh-keygen -Y sign -f "$HOME/.ssh/poi-e3-v2/$HUMAN_SIGNER_ID" \
  -n poi-e3-v2-development '<exact-file-to-sign>'
```

The custodian verifies with an externally maintained allowed-signers file:

```bash
ssh-keygen -Y verify -f "$E3_EXTERNAL/trust/allowed_signers" \
  -I "$HUMAN_SIGNER_ID" -n poi-e3-v2-development \
  -s '<exact-file-to-sign>.sig' < '<exact-file-to-sign>'
```

Copy only public keys, signed declarations, and detached signatures into the bundle. Never copy private keys.

## 17. Reserved continuation: build the final pre-execution manifest

**Do not run this step until the integration owner has delivered the approved development runner/exporter and the humans have completed the real environment manifest and owner declaration.**

After every pre-execution file is frozen, generate `manifest.json` last:

```bash
"$PY" - "$E3_DEV" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); entries=[]
for p in sorted(root.rglob('*')):
    if not p.is_file() or p.name=='manifest.json': continue
    if p.is_symlink(): raise SystemExit(f'STOP: symlink {p}')
    entries.append({'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
payload={'schema_version':'POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_MANIFEST_V1','files':entries}
(root/'manifest.json').write_bytes(json.dumps(payload,allow_nan=False,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode())
print('manifest_entries',len(entries))
PY
```

## 18. Reserved continuation: validate the complete pre-execution package

**Do not run this step in the current repository state.** It becomes executable only after Step 17 is legitimately complete.

```bash
cd "$POI_REPO"
"$PY" scripts/build_e3_v2_development_bundle.py \
  --bundle-root "$E3_DEV" \
  --output "$E3_EXTERNAL/E3_V2_DEVELOPMENT_BUNDLE_REPORT.json"

"$PY" -m pytest -q \
  tests/experiments/test_e3_annotation_worksheet.py \
  tests/semantic/test_calibration_v2.py \
  tests/experiments/test_e3_phase3_development.py \
  tests/reproducibility/test_build_e3_v2_development_bundle.py
```

Expected report status at this point:

```text
MATERIALS_VALIDATED_WAITING_AUTHORITY
```

This is not execution authority and not scientific evidence.

## 19. Canonical engineering checkpoint state

**Canonical gate state: `WAITING_EXTERNAL_ENGINEERING_REVIEW`. Stop here.**

The Phase-3 engineering artifacts and adversarial tests are implemented and locally
verified. That mechanical evidence does not satisfy the separately owned signed
review gate. Real inference remains prohibited until a qualified external reviewer
returns a verified signed review record plus identity, independence, and key-custody
evidence bound to the reviewed commit and file hashes.

1. **Development-only authority request builder** — `scripts/build_e3_v2_development_authority_request.py`
   and `src/poi_mpp/experiments/e3_v2_development_authority.py`. Binds the sealed
   dataset, model, decode policy, environment, and policy inputs without referencing
   confirmatory lineage. Fails closed if confirmatory materials are present.

2. **Development-only real-model runner** — `scripts/run_e3_v2_development_model.py`.
   Runs the pinned 1B–3B unquantized model over 120–150 development items in
   offline/local-only mode. Never reads confirmatory freeze material. Emits raw
   outputs.jsonl, trace.jsonl, summary.json, and execution_manifest.json.

3. **Canonical observation exporter** — `src/poi_mpp/worker/development_observation_exporter.py`.
   Converts raw execution output into `DevelopmentCalibrationObservationV2` with
   authoritative dataset-record binding hashes. Enforces REAL_MODEL_EXECUTION origin
   and fail-closed decision parsing (contradictions → ABSTAIN).

4. **Calibration CLI** — `scripts/fit_e3_v2_development_calibration.py`. Calls
   `fit_development_calibration_v2`, emits error ledger, NOT_YET_ASSESSABLE
   leakage report, metrics, and FROZEN_DEVELOPMENT_ONLY freeze atomically.

The existing `scripts/run_e3_v2_real_model.py` remains the 500-item confirmatory
runner and is deliberately blocked. Bypassing the development pipeline with
an ad-hoc script, self-signature, or the confirmatory runner is prohibited.

Create a curation-stage manifest that is explicitly not the final development-bundle manifest:

```bash
"$PY" - "$E3_EXTERNAL" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); included=[]
for base in ('sealed-dataset','POI_E3_V2_DEVELOPMENT/policy','POI_E3_V2_DEVELOPMENT/model','custody','signatures','trust'):
    target=root/base
    if not target.exists(): continue
    for p in sorted(target.rglob('*')):
        if p.is_file(): included.append({'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
payload={'schema_version':'POI_MPP_E3_V2_CURATION_HOLD_MANIFEST_V1','status':'WAITING_EXTERNAL_ENGINEERING_REVIEW','files':included}
(root/'CURATION_HOLD_MANIFEST.json').write_bytes(json.dumps(payload,allow_nan=False,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode())
print('hold_entries',len(included))
PY
```

Package the HOLD-point materials:

```bash
cd "$E3_EXTERNAL"
shasum -a 256 CURATION_HOLD_MANIFEST.json > HOLD_POINT_SHA256SUMS.txt
zip -r -X E3_V2_PHASE3_PREEXECUTION_HANDOFF.zip \
  POI_E3_V2_DEVELOPMENT sealed-dataset CURATION_HOLD_MANIFEST.json \
  HOLD_POINT_SHA256SUMS.txt trust custody signatures
shasum -a 256 E3_V2_PHASE3_PREEXECUTION_HANDOFF.zip
```

Transmit the archive hash through a second channel. Do not send private keys or unrestricted identity documents in the archive.

## 20. Engineering completion versus external review

The following engineering artifacts are now implemented:

| Artifact | Implementation status | External signed review status |
|---|---|---|
| Development authority request and verifier | Implemented with canonical material hashes and canonical external trust primitive | `WAITING_EXTERNAL` |
| Local-files-only 1B–3B development runner | Implemented; atomic output; pinned cache bytes re-hashed; synthetic stub is non-evidence | `WAITING_EXTERNAL` |
| Canonical observation exporter | Implemented; one-to-one row, prompt, raw output, trace, summary, and manifest closure | `WAITING_EXTERNAL` |
| Development calibration CLI | Implemented; authority-bound input, real-only observations, atomic self-digested output | `WAITING_EXTERNAL` |
| Adversarial and regression tests | RED failures captured and GREEN locally; exact command output belongs in the checkpoint record | developmental evidence only |

No person, email address, public key, independent-review verdict, or key-custody fact
is asserted by this runbook. An AI read-only code review may be retained as
developmental QA only; it cannot close the accountable-human review gate.

The HOLD is released only after the canonical external review verifier accepts the
hash-bound signed review record and the repository remains at the reviewed commit.

## 21. Acceptance gate presented to the project owner

The project owner will accept the accountable development package only if all rows below are satisfied:

| Gate | Required evidence |
|---|---|
| Human identity | out-of-band identity binding for A and B; C if used |
| Independence | signed blinding declarations; no model-output access before annotation freeze |
| Dataset | 120–150 unique records; exact 50/50/20–50 composition |
| Annotation | two complete independent ledgers; agreement counts; third-person adjudication for every disagreement |
| License/privacy | complete truthful `CC-BY-4.0` / `AUTHORIZED_PUBLIC` ledger under current code |
| Model | exact 40-character revisions; unquantized 1B–3B safetensors; file hashes; reviewed license |
| Environment | engineering implementation is complete; external signed engineering review remains `WAITING_EXTERNAL`; after it passes, bind local-only declaration, runner/exporter hashes, dependency lock, SBOM, hardware and driver inventory |
| Policy | frozen claim, prompt, output schema, contradiction, recovery, and taxonomy review |
| Provenance | canonical manifest closure, no symlinks, detached human signatures, second-channel archive hash |
| Execution | `WAITING_EXTERNAL_ENGINEERING_REVIEW`; then still requires a separately verified development authority and sealed real bundle |
| Calibration | `BLOCKED_BY_SEQUENCE` until authorized real observations exist; it cannot be frozen from synthetic or stub output |
| Confirmatory | remains `BLOCKED_BY_DESIGN`; no 500-item data inspection or execution |

## 22. Immediate stop conditions

Stop, preserve the files, and report the exact error if any of these occurs:

- a human saw model output before freezing annotation;
- A or B saw the other's labels before both signed;
- a disagreement exists without Human C;
- final composition is outside 50/50/20–50;
- a source is not genuinely CC-BY-4.0 and authorized public;
- any symlink, hash mismatch, duplicate ID, missing row, stale signature, or invalid signature appears;
- model/tokenizer revision is not a 40-character commit;
- weights are quantized or not safetensors;
- inference needs network access or an external service;
- anyone proposes using `SYNTHETIC_NON_EVIDENCE` as real calibration evidence;
- anyone proposes running the 500-item confirmatory runner before Phase-3 freeze and Phase-4 approval.

The correct state after a stop is `WAITING_EXTERNAL`, `WAITING_ENGINEERING`, or `BLOCKED`, never an inferred pass.
