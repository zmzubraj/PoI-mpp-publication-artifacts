# References Audit

Date: Monday, August 24, 2026

Scope:

- This audit covers the 12 references retained in `POI_SUBMISSION_MANUSCRIPT.md` after unused or unresolved source-carried entries were removed.
- The goal of this pass was bibliographic normalization and primary- or official-source verification where possible.
- No new scientific claim was introduced from the reference pass.
- References are still used as architectural lineage and background, not as substitutes for repository evidence.

## Overall audit summary

- total retained references reviewed: `12`
- normalized against a primary or official source: `12`
- unresolved retained references: `0`
- peer-reviewed conference or journal papers: `4`
- arXiv preprints: `4`
- official protocol, vendor, or project documentation: `4`
- explicitly grey literature among retained references: `1`

## Per-reference audit

| Ref | Normalized citation target | Source class | Primary or official source checked | Verification status | Notes |
|---|---|---|---|---|---|
| `[1]` | Conway et al., `opML: Optimistic Machine Learning on Blockchain`, arXiv:2401.17555 (2024) | arXiv preprint | `https://arxiv.org/abs/2401.17555` | verified | source-carried title/authors/year matched |
| `[2]` | Optimism Collective, `Fault Proof`, OP Stack Specification | official specification | `https://specs.optimism.io/fault-proof/index.html` | verified | official protocol-spec page |
| `[3]` | Chan et al., `Optimistic TEE-Rollups...`, arXiv:2512.20176 (2025) | arXiv preprint | `https://arxiv.org/abs/2512.20176` | verified | source-carried title/authors/year matched |
| `[4]` | NVIDIA, `Attestation and Key-Release Flow` in the confidential-computing reference architecture | vendor documentation | `https://docs.nvidia.com/enterprise-reference-architectures/deploying-proprietary-models-confidential-compute-self-hosted-vms/latest/attestation-and-key-release-flow.html` | verified | official vendor documentation; not independent empirical evidence |
| `[5]` | LambdaClass, `CommitLLM` project repository and engineering docs | project repository / grey literature | `https://github.com/lambdaclass/CommitLLM` | verified | official repo located; keep labeled grey literature |
| `[6]` | Ji, Mascagni, and Li, `Gaussian Variant of Freivalds’ Algorithm for Efficient and Reliable Matrix Product Verification`, arXiv:1705.10449 (2017) | arXiv preprint / primitive background | `https://arxiv.org/abs/1705.10449` | verified | normalized author order to match primary source |
| `[7]` | Intel Trust Authority, `GPU Remote Attestation with Intel Trust Authority` | vendor documentation | `https://docs.trustauthority.intel.com/main/articles/articles/ita/concept-gpu-attestation.html` | verified | official vendor documentation; not independent empirical evidence |
| `[8]` | Ribeiro Alves et al., `EigenAI: Deterministic Inference, Verifiable Results`, arXiv:2602.00182 (2026) | arXiv preprint | `https://arxiv.org/abs/2602.00182` | verified | source-carried title/authors/year matched |
| `[9]` | Qu et al., `zkGPT: An Efficient Non-interactive Zero-knowledge Proof Framework for LLM Inference`, USENIX Security 25 | conference paper | `https://www.usenix.org/conference/usenixsecurity25/presentation/qu-zkgpt` | verified | official conference page located |
| `[10]` | Peng et al., `A Survey of Zero-Knowledge Proof Based Verifiable Machine Learning`, *Artificial Intelligence Review* 59, 157 (2026) | journal article | `https://doi.org/10.1007/s10462-026-11557-y` | verified | normalized to version of record |
| `[11]` | Yu et al., `Coded Merkle Tree: Solving Data Availability Attacks in Blockchains`, FC 2020, LNCS 12059 | conference chapter | `https://doi.org/10.1007/978-3-030-51280-4_8` | verified | normalized to canonical Springer record |
| `[12]` | Yin et al., `HotStuff: BFT Consensus with Linearity and Responsiveness`, PODC 2019 | conference paper | `https://doi.org/10.1145/3293611.3331591` | verified | normalized to canonical ACM DOI |

The unresolved Hearth item and unused Ambient and Ethereum web references were
removed from the manuscript rather than carried into a submission-facing
bibliography without an in-text claim or stable primary-source need.

## Normalization decisions

1. Source-carried references with incomplete bibliographic form were normalized only up to what the primary or official source supported.
2. Grey literature remains explicitly labeled as grey literature even when an official project page or repository was found.
3. The unresolved `Hearth` item and unused Ambient and Ethereum web references were removed rather than retained without a stable primary-source need or an in-text claim.
4. Retained web documentation references remain access-dated because they are living documents.

## Manuscript-use constraints enforced

The manuscript uses these references only for:

- architectural lineage;
- background on adjacent verification families;
- protocol and systems comparison points; and
- framing of deferred future phases.

The manuscript does not use them as proof of:

- repository claim support for C1-C8;
- novelty resolution;
- independent review;
- production readiness;
- publication readiness.

## Residual risks

1. One retained reference is grey literature and is not treated as independent empirical evidence.
2. Official documentation pages can drift after August 24, 2026.
3. This audit normalizes citations and source status; it does not constitute a novelty search or literature-scope closure.
4. If the manuscript moves to formal submission, the bibliography should still receive venue-specific style formatting and final DOI/access-date QA.
