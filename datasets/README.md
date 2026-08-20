# Dataset Rules

## Objective

The objective generator creates deterministic tasks with exact ground truth.

## Grounded

The grounded generator creates evidence-backed questions with explicit support spans.

## Publication use

The publication dataset should have a versioned manifest with:

- dataset ID
- generator commit
- item count
- task-family distribution
- positive/negative/ambiguous counts
- evidence-source identifiers
- deduplication hash
- seed

Store sensitive source text outside the repository if necessary and publish hashes/redacted evidence.
