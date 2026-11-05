"""Compare predictions with ground truth and print accuracy metrics.

Run from the repository root:
    python -m evaluation.metrics --pred-dir data/predictions/run1 --subset dev

A prediction file inv_XXXX.json can be either
  - the full API response (ExtractionResponse): {"fields": {"net_amount": {"value": ...}, ...}}
  - or a flat dict: {"net_amount": "1000.00", ...}

Values are normalized before comparing (NIP -> digits only, amounts -> Decimal
with 2 places, whitespace collapsed), so "525-224-84-81" equals "5252248481".
A missing prediction file counts as all fields wrong.

Outputs:
  - tables in the terminal (overall, per field, per degradation/template/case)
  - evaluation/results/<run>.json         (numbers)
  - evaluation/results/<run>_errors.csv   (every wrong field, for error analysis)
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = [
    "invoice_number", "issue_date", "due_date",
    "seller_name", "seller_nip", "buyer_name", "buyer_nip",
    "currency", "net_amount", "vat_amount", "gross_amount",
]
NIP_FIELDS = {"seller_nip", "buyer_nip"}
AMOUNT_FIELDS = {"net_amount", "vat_amount", "gross_amount"}

GT_DIR = Path("data/ground_truth")
CASES_PATH = Path("data/cases.json")
SPLIT_PATH = Path("data/split.json")
MANIFEST_PATH = Path("data/raw/manifest.csv")
RESULTS_DIR = Path("evaluation/results")


def normalize(field: str, value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    if field in NIP_FIELDS:
        return re.sub(r"\D", "", s) or None
    if field in AMOUNT_FIELDS:
        try:
            cleaned = re.sub(r"\s", "", s).replace(",", ".")
            return str(Decimal(cleaned).quantize(Decimal("0.01")))
        except InvalidOperation:
            return s
    if field == "currency":
        return s.upper()
    return " ".join(s.split())


def load_prediction(path: Path):
    """Return {field: value} or None when the prediction file is missing."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if "fields" in data:
        return {name: (data["fields"].get(name) or {}).get("value") for name in FIELDS}
    return {name: data.get(name) for name in FIELDS}


def summarize(rows: list[dict]) -> dict:
    """rows: [{"correct": {field: bool}}]. Returns accuracy numbers."""
    if not rows:
        return {"documents": 0, "field_accuracy": None, "document_accuracy": None}
    total_fields = len(rows) * len(FIELDS)
    correct_fields = sum(sum(r["correct"].values()) for r in rows)
    perfect_docs = sum(all(r["correct"].values()) for r in rows)
    return {
        "documents": len(rows),
        "field_accuracy": correct_fields / total_fields,
        "document_accuracy": perfect_docs / len(rows),
    }


def pct(x) -> str:
    return "  n/a" if x is None else f"{100 * x:5.1f}%"


def print_table(title: str, groups: dict) -> None:
    print(f"\n{title}")
    print(f"  {'':<22}{'docs':>5}  {'field acc':>10}  {'doc acc':>8}")
    for name, rows in sorted(groups.items()):
        s = summarize(rows)
        print(f"  {name:<22}{s['documents']:>5}  {pct(s['field_accuracy']):>10}  {pct(s['document_accuracy']):>8}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-dir", required=True)
    parser.add_argument("--subset", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--only-predicted",
        action="store_true",
        help="evaluate only documents that have a prediction file (useful for small trial runs)",
    )
    args = parser.parse_args()

    pred_dir = Path(args.pred_dir)
    run_name = args.run_name or pred_dir.name

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if args.subset == "all" or not SPLIT_PATH.exists():
        doc_ids = sorted(cases)
    else:
        doc_ids = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))[args.subset]

    if args.only_predicted:
        doc_ids = [d for d in doc_ids if (pred_dir / f"{d}.json").exists()]

    templates = {}
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            templates = {r["doc_id"]: r["template"] for r in csv.DictReader(fh)}

    rows, errors, missing = [], [], 0
    for doc_id in doc_ids:
        truth_raw = json.loads((GT_DIR / f"{doc_id}.json").read_text(encoding="utf-8"))
        pred = load_prediction(pred_dir / f"{doc_id}.json")
        if pred is None:
            missing += 1
            pred = {name: None for name in FIELDS}
            missing_file = True
        else:
            missing_file = False

        correct = {}
        for field in FIELDS:
            expected = normalize(field, truth_raw.get(field))
            got = normalize(field, pred.get(field))
            correct[field] = expected == got
            if expected != got:
                errors.append(
                    {
                        "doc_id": doc_id,
                        "field": field,
                        "expected": expected,
                        "got": "<no prediction file>" if missing_file else got,
                        "degradation": cases[doc_id]["degradation"],
                        "template": templates.get(doc_id, ""),
                        "case": cases[doc_id]["case"],
                    }
                )
        rows.append(
            {
                "doc_id": doc_id,
                "correct": correct,
                "degradation": cases[doc_id]["degradation"],
                "template": templates.get(doc_id, "?"),
                "case": cases[doc_id]["case"],
            }
        )

    overall = summarize(rows)
    print(f"Run: {run_name} | subset: {args.subset} | documents: {len(rows)} | missing predictions: {missing}")
    print(f"Field accuracy:    {pct(overall['field_accuracy'])}")
    print(f"Document accuracy: {pct(overall['document_accuracy'])}  (all {len(FIELDS)} fields correct)")

    per_field = {f: sum(r["correct"][f] for r in rows) / len(rows) for f in FIELDS}
    print("\nPer field")
    for f in FIELDS:
        print(f"  {f:<16}{pct(per_field[f])}")

    breakdowns = {}
    for key, title in [("degradation", "By degradation"), ("template", "By template"), ("case", "By case")]:
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        print_table(title, groups)
        breakdowns[key] = {name: summarize(g) for name, g in groups.items()}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "run": run_name,
        "subset": args.subset,
        "missing_predictions": missing,
        "overall": overall,
        "per_field": per_field,
        "breakdowns": breakdowns,
    }
    (RESULTS_DIR / f"{run_name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    errors_path = RESULTS_DIR / f"{run_name}_errors.csv"
    with open(errors_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["doc_id", "field", "expected", "got", "degradation", "template", "case"]
        )
        writer.writeheader()
        writer.writerows(errors)
    print(f"\n{len(errors)} wrong fields -> {errors_path}")


if __name__ == "__main__":
    main()
