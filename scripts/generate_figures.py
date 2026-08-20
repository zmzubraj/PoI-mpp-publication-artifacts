"""Single entry point for publication figure generation.

Each figure should read machine-generated CSV/JSON from results/raw and write PDF/SVG to results/figures.
The current scaffold intentionally does not invent experimental values.
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
print('Figure pipeline scaffold ready. Add real plotting functions after E1–E8 produce result files.')
print('Figures target directory:', ROOT/'results'/'figures')
