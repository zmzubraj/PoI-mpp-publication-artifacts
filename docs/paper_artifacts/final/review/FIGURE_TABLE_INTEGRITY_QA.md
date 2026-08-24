# Figure and table integrity QA

Status: `DEVELOPMENTAL_QA_ONLY`

Audit date: 2026-08-24

This audit binds the final figure/table derivatives to editable sources and
canonical data. It is an AI-assisted developmental review, not independent
scientific, accessibility, image-integrity, or publisher approval.

## Completed locally

- SHA-256, file presence, and explicit source-path mapping are recorded in
  `FIGURE_TABLE_FIDELITY_LEDGER.csv`.
- Quantitative figures F5-F12 retain their real-model, simulation,
  or local-Foundry evidence ceilings; no visual promotes an inconclusive result.
- F7 is hash-identical to the externally attested E3 SVG and remains a negative
  bounded result: n=8, invalid n=2, FAR 0.500 exceeds `alpha_sem=0.25`, and C3
  is `NOT_SUPPORTED`. Signature validity does not prove evaluator independence.
- Conceptual figures remain separate from quantitative evidence.
- Editable CSV table sources, Mermaid sources, canonical JSON/CSV data, and the
  deterministic figure builder are preserved.
- Captions disclose the relevant denominator, uncertainty type, origin, and
  limitation where applicable.
- The 16-page evidence-bound PDF was inspected at rendered page size for the
  title/abstract/keywords, quantitative result pages, and final limitations and
  references; fonts are embedded and no clipping or missing glyph was observed.

## Partial or external-only checks

- Grayscale inspection is a useful screen but is not a complete color-vision
  deficiency evaluation. The current figures use labels, axes, panel separation,
  or category position in addition to color, but qualified accessibility review
  remains `WAITING_EXTERNAL`.
- Exact final-size typography is provisional because the accountable author has
  not selected a venue/template/column width. Recheck every label after the
  official template is applied.
- Scientific image-integrity tools are not applicable to these code-generated
  charts and diagrams, but a qualified human must still compare plotted values
  with source data and captions.
- Table units, denominators, missing values, and definitions were mechanically
  inspected; domain-expert interpretation remains `WAITING_EXTERNAL`.
- Publisher-specific figure format, dimensions, accessibility, separate-file,
  and source-delivery rules remain `WAITING_USER` until venue selection.

## Human review handoff

The qualified reviewer must complete
`figure_table_external_review_record.schema.json`, bind the exact ledger hash,
list every artifact inspected, record discrepancies, and sign the exact record
with an externally controlled identity. A clean AI or automated result cannot
close this gate.
