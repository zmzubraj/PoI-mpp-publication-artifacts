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

বর্তমান workspace বোঝার source of truth হলো canonical
`publication/artifact_manifest.json`। এর SHA-256 হলো
`7177d57747304d003160cdcb45bd572337028a8ffed8793dfa57e2d1444aaabf`।

এই canonical bundle-এ E1, E2, এবং E4-E8-এর table/figure artifact আছে; E3-এর
T4, T8, ও F7 `WAITING_EXTERNAL` omission হিসেবে আছে। এই evidence state আর
artifact regeneration-এর অপেক্ষার state নয়। কিন্তু bundle থাকা আর
publication-ready হওয়া এক জিনিস নয়।

এখনো তিনটি independent blocker আছে:

- E3-এর external evaluator authority;
- authenticated independent manual review; এবং
- publication-freeze sentinel।

AI output, AI approval, বা user approval—কোনোটিই independent review নয়।

## ৫) claim-by-claim current status

বর্তমান evidence boundary অনুযায়ী:

- `C1` / E1: `INCONCLUSIVE` fixed-order real-model pilot। দুই paired observation,
  ছয় measured row; mean two-run 5197.17125 ms, MPP 2678.932229 ms, delta
  2518.239021 ms, bootstrap interval [2440.923209, 2595.554833]। Fixed order
  থাকার কারণে general cost-advantage claim করা যাবে না।
- `C2` / E2: `INCONCLUSIVE` narrow real-model pilot। 4/4 attacked observation
  detect হয়েছে; তিনটি exact surface, একটি empirical surface, Wilson interval
  [0.5101091635454027, 1.0], এবং এক honest control-এ false positive নেই। এটা
  general detection claim নয়।
- `C3` / E3: `WAITING_EXTERNAL`; external evaluator authority না আসা পর্যন্ত
  semantic performance evidence নেই।
- `C4` / E4: `INCONCLUSIVE` declared playback simulation; executed
  reconstruction নয়।
- `C5` / E5: `SUPPORTED`, কিন্তু শুধু declared reproducible-simulation
  scenario-র জন্য; figure নেই।
- `C6` / E6: `SUPPORTED`, কিন্তু শুধু declared reproducible-simulation
  scenario-র জন্য; open-network Sybil resistance নয়।
- `C7` / E7: local Foundry measurement boundary-র মধ্যে `SUPPORTED`; 15 row,
  max gas 467937, max block-limit fraction 0.00043580029159784317।
- `C8` / E8: 10-row reproducible simulation, কিন্তু `INCONCLUSIVE`।

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

- evidence disposition একরকম নয়: E1, E2, E4, ও E8 inconclusive; E5 ও E6
  declared simulation-এ supported; E7 local Foundry-তে supported; E3-এ evidence
  নেই

### ঘ) Reproducibility discipline

অবস্থা: strong at software/artifact discipline level, incomplete at publication-freeze level

কারণ:

- repository fail-closed behavior সংরক্ষণ করে
- incomplete state-কে success বলে relabel করে না

সীমা:

- canonical publication artifact bundle আছে, কিন্তু freeze, authority, এবং
  independent-review gate এখনো complete নয়

### ঙ) Primitive novelty

অবস্থা: provisional এবং primitive layer-এ low-to-moderate

কারণ:

- CommitLLM open-weight LLM inference-এর commitment, challenge-time trace opening,
  exact/Freivalds-style audit এবং per-response full proof এড়ানোর একটি close
  implementation predecessor
- opML on-chain ML-এর optimistic fraud-proof path আগেই দেখিয়েছে
- strongest-prior-art package এখনো reproducible case হিসেবে frozen নয়
- differently owned independent novelty challenge নেই

সম্ভাব্য differentiator primitive execution proof নয়; বরং execution/semantic
evidence থেকে retention, receipt maturity, task-budgeted credit এবং bounded
next-epoch consensus weight পর্যন্ত protocol composition। এই composition
materially novel কি না, সেটা এখনো independently established নয়।

### চ) Publication readiness

অবস্থা: not ready for central empirical claims

কারণ:

- external evaluator authority এখনো বাকি
- independent domain-expert review/signature এখনো বাকি
- publication-freeze sentinel এখনো নেই

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
- provisional primitive novelty central estimate 35/100 (uncertainty band 25-45); এটি developmental score, scientific gate নয়
- protocol-composition differentiation central estimate 68/100 (uncertainty band 55-75), independent prior-art challenge-এর আগে ceiling প্রযোজ্য
- empirical support এখনো narrow
- E1, E2, E4, এবং E8 `INCONCLUSIVE`
- E5 ও E6 declared simulation scope-এ `SUPPORTED`
- E7 local Foundry scope-এ `SUPPORTED`
- E3 `WAITING_EXTERNAL`
- external evaluator authority, independent domain-expert review/signature, এবং publication-freeze sentinel এখনো required
- তাই paper-এ language অবশ্যই evidence-bounded থাকতে হবে; কোনো overall score, compensating score table, বা stronger-than-evidence success language ব্যবহার করা উচিত নয়

বিস্তারিত non-compensating scorecard paper-এর বাইরে
`PROVISIONAL_NOVELTY_AND_OVERALL_ASSESSMENT.md`-এ আছে।
