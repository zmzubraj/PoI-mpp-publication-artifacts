# MPP alignment explanation (বাংলা ব্যাখ্যা)

তারিখ: 2026-08-23

এই নোটটি ইংরেজি পেপারের বাইরে একটি ব্যাখ্যামূলক দলিল। এর উদ্দেশ্য হলো বর্তমান repository-র Minimum Publishable Prototype (MPP) ঠিক কীভাবে paper-এর সাথে মিলে, কোথায় শুধু architecture/protocol composition আছে, কোথায় primitive novelty এখনো provisional, এবং কোন claim এখনো evidence-বাঁধা অবস্থায় অসম্পূর্ণ আছে—সেটা পরিষ্কার করে বলা।

এটি কোনো independent human review নয়, কোনো strongest-prior-art verdict নয়, কোনো publication acceptance verdict নয়, এবং AI-উৎপন্ন approval বা signature-কে independent review হিসেবে গণ্য করা যাবে না।

## ১) implemented MPP paper-এর সাথে কীভাবে align করে

সংক্ষেপে: repository-র implemented MPP paper-এর narrow first-publication reading-এর সাথে ভালোভাবে align করে, কিন্তু paper-এর full architecture reading-এর সাথে পুরোপুরি align করে না।

MPP-র align হওয়া অংশগুলো হলো:

- একবার model execution, তারপর commitment, তারপর post-commit audit, তারপর challenge/retention/maturity, তারপর next-epoch weight—এই মূল single-pass flow repository-তে সংরক্ষিত আছে।
- evidence kernel, protocol kernel, এবং experiment/reporting pipeline—এই তিন স্তরের ভাগ paper-এর logical decomposition-এর সাথে মিলে।
- local EVM/Foundry boundary-র মধ্যে compact on-chain state এবং heavy off-chain AI execution—এই separation paper-এর claimed EVM-compatible path-এর সাথে মিলে।
- E7 local Foundry measurement surface এবং E8 reproducible simulation surface—দুটিই paper-এর narrow MPP framing-এর সাথে consistent।

যেখানে full-paper scope আর implemented MPP আলাদা:

- 70B/600B scale বা full MoE serving repository-র বর্তমান empirical surface নয়।
- confidential GPU/TEE lane architecture-এ আছে, কিন্তু current MPP evidence surface নয়।
- production dispute VM, production DA network, production consensus client—এগুলো current repository result নয়।
- open-ended universal semantic intelligence verification current MPP claim boundary-র বাইরে।

সোজা ভাষায়: paper-এ বর্ণিত বড় architecture-এর একটি disciplined, evidence-gated, smaller MPP repository-তে implement করা হয়েছে; পুরো paper architecture empiricalভাবে already validated—এমন দাবি করা যাবে না।

## ২) কোন অংশ architecture/protocol composition, আর কোন অংশ primitive novelty হতে পারে

এখানে সবচেয়ে গুরুত্বপূর্ণ পার্থক্য হলো “ভালো composition” আর “সত্যিকারের primitive novelty” এক জিনিস নয়।

### Architecture / protocol composition হিসেবে যা বলা নিরাপদ

- single-pass execution + post-commit audit + maturity-gated receipt + next-epoch weight conversion—এই pipeline composition
- evidence root, trace root, commitment, audit obligation, receipt state, credit state—এই protocol object binding
- local EVM bounded path রেখে heavy AI work off-chain রাখার design
- simulation-bounded consensus weight modeling

এগুলো repository-তে design, interfaces, artifacts, diagrams, tables, এবং partial validated result surface হিসেবে দেখা যায়।

### Primitive novelty হিসেবে যা এখনো provisional

- এই composition সত্যিই materially new primitive কি না
- existing fraud-proof, audit, commitment, attestation, DA gating, committee-weight, বা weighted-BFT literature-এর তুলনায় exact differentiator কী
- “আগে কেউ করেনি” ধরনের stronger novelty statement

অর্থাৎ repository এখন architecture coherence এবং implementation discipline দেখায়; কিন্তু strongest-prior-art package ছাড়া primitive novelty finalভাবে প্রমাণ করে না।

## ৩) novelty কেন এখনো provisional

Novelty provisional থাকার কারণগুলো non-compensating:

- reproducible strongest-prior-art search package নেই
- independently challenged novelty case নেই
- closest predecessor বনাম current design-এর exact overlap/difference matrix নেই
- external independent novelty challenge artifact নেই

এই gap-গুলো code quality, diagrams, tests, বা partial experiment support দিয়ে compensate করা যাবে না।

তাই সঠিক ভাষা হবে:

- “novelty may be promising”
- “novelty remains provisional”
- “stronger novelty claim awaits strongest-prior-art search and independent challenge”

ভুল ভাষা হবে:

- “this primitive is proven novel”
- “paper establishes definitive novelty”
- “repository alone closes the novelty question”

## ৪) বর্তমান claim/evidence status: exact update

বর্তমান workspace ব্যাখ্যা করার সময় দুইটি জিনিস আলাদা করে দেখতে হবে:

- পুরোনো Task22 candidate verification report-এ যা লেখা আছে
- বর্তমান workstream-এর নতুন update

### ৪.১ পুরোনো candidate report কী বলছে

Ignored local Task22 candidate-এর historical verification report-এ `WAITING_LOCAL_MODEL_ARTIFACT` blocker ছিল। ওই temporary report tracked বা publication-admissible provenance নয়; এটি শুধু বোঝায় যে সেই পুরোনো candidate তৈরির সময় exact local model artifact absent ছিল।

### ৪.২ বর্তমান update কী

বর্তমান update অনুযায়ী exact Qwen 1.5B local model artifact এখন acquired এবং hash-verified।

কিন্তু এখানেই claim upgrade করা যাবে না। কারণ:

- exact model artifact পাওয়া গেছে মানেই E1 pilot automatically admissible নয়
- E1 pilot এখনো admissible নয়, কারণ runtime/cache-method corrections এখনো claim-ready publication evidence boundary-তে freeze হয়নি
- অর্থাৎ model provenance gap আংশিকভাবে কমেছে, কিন্তু E1 evidence gate এখনো closed নয়

এই distinction খুব গুরুত্বপূর্ণ:

- “artifact acquired” ≠ “experiment admitted”
- “hash verified model” ≠ “publication-grade E1 evidence”
- “mechanics available” ≠ “claim supported”

## ৫) claim-by-claim current status

বর্তমান evidence boundary অনুযায়ী:

- `C7` locally supported
- `C8` simulation-based but inconclusive
- `C1` থেকে `C6` এখনো supported নয়

আরও স্পষ্টভাবে:

- `C1`: supported নয়; authorized real E1 pilot চালানো হয়েছে, কিন্তু publication decision এখনো `INCOMPLETE / INCONCLUSIVE`
- `C2`: executed real pilot artifact এখন আছে, কিন্তু publication freeze gate এখনো complete নয়; তাই final claim এখনো supported বলা যাবে না
- `C3`: supported নয়; external evaluator authority এখনো দরকার
- `C4`: reproducible simulation run আছে, কিন্তু provenance freeze gate incomplete; তাই final claim এখনো supported নয়
- `C5`: reproducible simulation run আছে, কিন্তু provenance freeze gate incomplete; তাই final claim এখনো supported নয়
- `C6`: reproducible simulation run আছে, কিন্তু provenance freeze gate incomplete; তাই final claim এখনো supported নয়
- `C7`: local Foundry measurement boundary-র মধ্যে supported
- `C8`: reproducible simulation surface আছে, কিন্তু disposition inconclusive

এখানে দুটি boundary মনে রাখতে হবে:

- `C7` মানে local EVM boundedness surface supported; এটা Ethereum mainnet production claim নয়
- `C8` মানে modeled next-epoch weight dynamics explain করা যায়; এটা demonstrated consensus-security proof নয়

## ৬) এক overall score নয়, আলাদা non-compensating assessment

নিচের dimension-গুলোকে আলাদা আলাদা পড়তে হবে। একটাতে ভালো হলে আরেকটার ঘাটতি মুছে যায় না।

### ক) Architecture coherence

অবস্থা: strong within narrow MPP scope

কারণ:

- paper-এর main single-pass path repository-তে preserved
- evidence/protocol/reporting split internally consistent
- diagrams, tables, and manuscript framing narrow MPP boundary-র সাথে মোটামুটি consistent

### খ) Implementation maturity

অবস্থা: high for narrow MPP software

কারণ:

- repository substantial implementation discipline দেখায়
- E7/E8, reporting, replay, and fail-closed bundle logic বিদ্যমান

সীমা:

- implementation maturity empirical claim maturity নয়

### গ) Empirical evidence maturity

অবস্থা: narrow and incomplete

কারণ:

- positive support এখন মূলত `C7`-এ সীমাবদ্ধ
- `C8` complete surface হলেও inconclusive
- `C1`-`C6` supported নয়

### ঘ) Reproducibility discipline

অবস্থা: strong at software/artifact discipline level, incomplete at publication-freeze level

কারণ:

- repository fail-closed behavior সংরক্ষণ করে
- incomplete state-কে success বলে relabel করে না

সীমা:

- canonical publication bundle এখনো complete নয়

### ঙ) Primitive novelty

অবস্থা: provisional

কারণ:

- strongest-prior-art package নেই
- independent novelty challenge নেই

### চ) Publication readiness

অবস্থা: not ready for central empirical claims

কারণ:

- `C1`-`C6` supported নয়
- external evaluator authority এখনো বাকি
- independent domain-expert review/signature এখনো বাকি
- publication-complete state এখনো অর্জিত হয়নি

## ৭) external evaluator এবং independent domain-expert signature কেন এখনো বাধ্যতামূলক

এই project-এ কিছু জিনিস AI generate করতে পারে, কিন্তু authority generate করতে পারে না।

এখনো যেগুলো externalভাবে দরকার:

- external evaluator authority, বিশেষ করে semantic/real-evidence dependent surfaces-এর জন্য
- authenticated independent domain-expert review signature

যা AI করতে পারবে না:

- independent reviewer হওয়া
- external evaluator authority impersonate করা
- domain-expert signature generate করা
- manual scientific review fabricate করা

অর্থাৎ AI summary, AI drafting, AI approval, বা user approval—কোনোটাই independent external review-এর বিকল্প নয়।

## ৮) bottom line

সবকিছু একসাথে ধরে সবচেয়ে honest summary হলো:

- implemented MPP paper-এর narrow first-publication interpretation-এর সাথে broadly aligned
- repository architecture এবং software composition শক্তিশালী
- primitive novelty এখনো provisional
- empirical support এখনো narrow
- `C7` supported
- `C8` inconclusive
- `C1`-`C6` supported নয়
- exact Qwen 1.5B local model artifact এখন acquired এবং hash-verified; E1 runtime/cache boundary fix-এর পরে authorized pilot চালানো হয়েছে, কিন্তু publication disposition এখনো `INCOMPLETE / INCONCLUSIVE`
- external evaluator authority এবং independent domain-expert signature এখনো required
- তাই paper-এ language অবশ্যই evidence-bounded থাকতে হবে; কোনো overall score, compensating score table, বা stronger-than-evidence success language ব্যবহার করা উচিত নয়
