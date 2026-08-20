# Result Schema

Every receipt-level experimental record should include at least:

```json
{
  "experiment_id": "E2",
  "task_id": "task-000001",
  "model_id": "primary-model",
  "model_hash": "...",
  "task_class": "objective",
  "seed": 42,
  "response_hash": "...",
  "trace_root": "...",
  "evidence_root": "...",
  "audit_seed": "...",
  "audit_rate": 0.05,
  "freivalds_rounds": 8,
  "attack": "tensor_corruption",
  "accepted": false,
  "abstained": false,
  "da_available": true,
  "dispute_opened": true,
  "credit": 0.0,
  "active_weight": 0.0,
  "latency_ms": 0.0,
  "gas_used": 0,
  "config_hash": "...",
  "git_commit": "..."
}
```

Never aggregate away receipt-level records before archiving the raw file.
