#!/usr/bin/env python3
"""Run the whole data-preparation pipeline in order (idempotent; raw files are only read).

    .venv/bin/python scripts/prepare_data.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["prepare_contract_data.py", "prepare_finance_data.py", "build_evaluation_set.py", "build_dataset_report.py"]

for step in STEPS:
    print(f"\n=== {step}")
    code = subprocess.call([sys.executable, str(HERE / step)])
    if code:
        sys.exit(f"{step} failed with exit code {code}")
