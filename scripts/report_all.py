"""Publication reporting entry point.

Expected flow:
1. validate raw artifacts
2. aggregate experiments
3. compute confidence intervals
4. generate tables
5. generate figures
6. build artifact manifest
"""
from scripts.build_artifact_manifest import OUT
print('Publication report pipeline scaffold. Run after E1-E8 are populated.')
print('Manifest target:', OUT)
