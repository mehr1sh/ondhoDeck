# Fine-tuning feasibility (LoRA / QLoRA) — decision: not run

Checked 2026-10-16. **No training was performed and no fine-tuned model exists.**

## Hardware and environment (inspected, not assumed)

| Item | Found |
|---|---|
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, 8,188 MiB VRAM (driver 610.57.04) |
| CPU / RAM | 24 logical CPUs, 30 GB RAM |
| Free disk | 59 GB on /home |
| ML libraries in the project venv | torch, transformers, peft, bitsandbytes, trl: **none installed** |

8 GB VRAM is enough, in principle, for QLoRA (4-bit) on a small open model (roughly 1–8B parameters)
with short sequences. Hardware is therefore not the blocking constraint.

## Data available for supervised fine-tuning

| Set | Rows | Status | Usable for training? |
|---|---|---|---|
| `data/labels/extraction_examples.jsonl` | 6 | Synthetic documents only, verified against the synthetic PDFs | Too few |
| `data/labels/evaluation_cases.jsonl` / `data/evaluation/expected_rules.jsonl` | 19 | Real public documents, source-checked, pending human sign-off | **No — reserved as the held-out evaluation set** |

Training on the 19 evaluation rules would leak the test set and make any reported improvement meaningless.
Six synthetic examples (from four template documents) cannot teach generalisation to real prospectuses,
credit agreements and LPAs; a model fine-tuned on them would mostly memorise the synthetic wording, which is
the failure mode the rule-based baseline already shows (6/6 on its development document, 0/13 on held-out
documents; see `extraction_eval_report.md`).

LLM predictions must not be used as training labels unless a human reviewer has approved each one, so
"generate labels with a large model, then distil" is not an available shortcut here.

## Decision

Fine-tuning is **not justified** with the current data. The baseline remains a pretrained LLM with
retrieval, schema-constrained output, Pydantic validation, verbatim-quote verification, contract-specific
checks and mandatory human approval.

## What would make it worthwhile

1. **Labels:** at least a few hundred reviewer-approved rules, approved in the app (approved constraints
   already carry quote, page, value, unit, value kind, conditions, exceptions and reviewer), spanning many
   issuers per contract family, plus RSU award agreements (none are in the dataset).
2. **Split by document/issuer:** keep the 19 current reference rules (and their documents) strictly held out.
3. **Comparison:** evaluate the pretrained baseline with `scripts/evaluate_extraction.py` first. Fine-tune
   only if the baseline's per-field errors are systematic and the gap justifies maintaining a model.
4. **Setup sketch (untested):** QLoRA (4-bit NF4, rank 16) on a small instruction model, output constrained
   to the same JSON schema, and the same validation and quote-verification layer applied to its outputs.
