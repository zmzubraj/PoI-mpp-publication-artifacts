# Search queries and raw snapshots

Cutoff date: Tuesday, August 25, 2026 (Asia/Dhaka)

Every query below is bound to a raw snapshot under `raw/`.

| Query ID | Surface | Exact URL or query | Raw snapshot |
|---|---|---|---|
| `Q1` | OpenAlex | `https://api.openalex.org/works?search=optimistic%20machine%20learning%20blockchain&per-page=10&sort=relevance_score:desc` | `raw/openalex_query_optimistic_machine_learning_blockchain_2026-08-25.json` |
| `Q2` | OpenAlex | `https://api.openalex.org/works?search=verifiable%20llm%20inference&per-page=10&sort=relevance_score:desc` | `raw/openalex_query_verifiable_llm_inference_2026-08-25.json` |
| `Q3` | Crossref | `https://api.crossref.org/works?query=optimistic%20machine%20learning%20blockchain&rows=10` | `raw/crossref_query_optimistic_machine_learning_blockchain_2026-08-25.json` |
| `Q4` | Crossref | `https://api.crossref.org/works?query=verifiable%20llm%20inference&rows=10` | `raw/crossref_query_verifiable_llm_inference_2026-08-25.json` |
| `Q5` | arXiv API | `search_query=all:"optimistic machine learning blockchain"&start=0&max_results=10` | `raw/arxiv_query_optimistic_machine_learning_blockchain_2026-08-25.xml` |
| `Q6` | arXiv API | `search_query=all:"verifiable llm inference"&start=0&max_results=10` | `raw/arxiv_query_verifiable_llm_inference_2026-08-25.xml` |
| `K1` | GitHub known item | `https://api.github.com/repos/lambdaclass/CommitLLM` | `raw/github_commitllm_repo_2026-08-25.json` |
| `K2` | arXiv known item | `https://arxiv.org/abs/2401.17555` | `raw/arxiv_opml_abs_2026-08-25.html` |
| `K3` | USENIX known item | `https://www.usenix.org/conference/usenixsecurity25/presentation/qu-zkgpt` | `raw/usenix_zkgpt_2026-08-25.html` |
| `K4` | arXiv known item | `https://arxiv.org/abs/2602.00182` | `raw/arxiv_eigenai_abs_2026-08-25.html` |
| `K5` | arXiv known item | `https://arxiv.org/abs/2512.20176` | `raw/arxiv_optimistic_tee_rollups_abs_2026-08-25.html` |
| `K6` | OpenAlex known item recovery | `https://api.openalex.org/works?search=opML%20Optimistic%20Machine%20Learning%20on%20Blockchain&per-page=5&sort=relevance_score:desc` | `raw/openalex_known_item_opml_2026-08-25.json` |
| `K7` | OpenAlex known item recovery | `https://api.openalex.org/works?search=zkGPT%20Efficient%20Non-interactive%20Zero-knowledge%20Proof%20Framework%20for%20LLM%20Inference&per-page=5&sort=relevance_score:desc` | `raw/openalex_known_item_zkgpt_2026-08-25.json` |
| `K8` | OpenAlex known item recovery | `https://api.openalex.org/works?search=EigenAI%20Deterministic%20Inference%20Verifiable%20Results&per-page=5&sort=relevance_score:desc` | `raw/openalex_known_item_eigenai_2026-08-25.json` |
| `K9` | OpenAlex adjacent recovery | `https://api.openalex.org/works?search=SVIP%20Towards%20Verifiable%20Inference%20of%20Open-source%20Large%20Language%20Models&per-page=5&sort=relevance_score:desc` | `raw/openalex_adjacent_svip_2026-08-25.json` |

Additional bounded public-index surfaces checked on 2026-08-25:

| Query ID | Surface | Exact public URL | Disposition |
|---|---|---|---|
| `P1` | Google Patents | `https://patents.google.com/patent/US11494677B2/en` | included: blockchain-recorded inference audit trail |
| `P2` | Google Patents | `https://patents.google.com/patent/US11562228B2/en` | included: efficient blockchain-native ML verification |
| `P3` | Google Patents | `https://patents.google.com/patent/US11303454B2/en` | included: model/inference event provenance and verification |
| `P4` | Google Patents | `https://patents.google.com/patent/US20250165967A1/en` | included: smart-contract-mediated encrypted model verification and transaction |
| `S1` | IEEE SA | `https://standards.ieee.org/ieee/3127/10745/` | included as adjacent blockchain/ML auditability standard |
| `S2` | IEEE SA | `https://standards.ieee.org/ieee/3217/10565/` | included as blockchain interface standard; not claim-matched |
| `S3` | IEEE SA | `https://standards.ieee.org/about/sasb/sba/20may2024/` | included as public record for blockchain consensus-framework project |
| `B1` | MLCommons | `https://docs.mlcommons.org/inference/index_gh/` | excluded as a performance benchmark, not a trust/audit benchmark |

These public pages were inspected and source-linked, but their full pages were
not frozen into the raw-snapshot subdirectory. Patent-family completeness,
claims construction, standards full text, and non-IEEE registries remain
access-limited and therefore cannot close novelty.

## Count reconciliation

| Surface/query | Reported total | Retrieved | Screened | Included | Excluded/adjacent |
|---|---:|---:|---:|---:|---:|
| OpenAlex Q1 | 5,597 | 10 | 10 | 2 | 8 |
| OpenAlex Q2 | 16,888 | 10 | 10 | 1 | 9 |
| Crossref Q3 | 3,082,928 | 10 | 10 | 2 | 8 |
| Crossref Q4 | 143,753 | 10 | 10 | 3 | 7 |
| arXiv Q5 | 0 | 0 | 0 | 0 | 0 |
| arXiv Q6 | 8 | 8 | 8 | 7 | 1 |
| Known-item snapshots K1-K9 | fixed lookups | 9 | 9 | 9 | 0 |
| Public patent/standards/benchmark pages P1-P4/S1-S3/B1 | fixed lookups | 8 | 8 | 6 | 2 |
| **Total retrieved records/pages** | not additive across indexes | **65** | **65** | **30** | **35** |

Deduplication used normalized lowercase title plus DOI/arXiv identifier where
available. The 30 inclusion events are screening events, not 30 unique works;
known-item recovery deliberately duplicates several query results. The bounded
benchmark screen found no standard trust/audit benchmark; MLPerf Inference is a
performance suite and is not evidence of PoI-like verification. No count is
treated as evidence of absence.

Notes:

- `Q1` and `Q3` are intentionally low-precision broad-surface queries; they
  are useful for count reconciliation and background saturation, not for direct
  novelty claims.
- `Q2`, `Q4`, and `Q6` surfaced multiple 2025-2026 adjacent systems that force
  the novelty verdict to remain fail-closed.
- patent and standards/protocol-registry search were not fully closed in this
  local package and remain explicit residual uncertainties.
