"""Split documents into a development set and a held-out test set.

Run from the repository root:
    python -m evaluation.split

Rules:
- ~70% dev / ~30% test, stratified by degradation (digital / scan / photo)
  so both sets contain every kind of document.
- A duplicate always goes to the same set as its original.
- Fixed seed, so the split is reproducible.

IMPORTANT: tune prompts and thresholds on DEV only. Use TEST once, at the end,
to report final numbers.
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

CASES_PATH = Path("data/cases.json")
SPLIT_PATH = Path("data/split.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-share", type=float, default=0.3)
    args = parser.parse_args()

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rng = random.Random(args.seed)

    groups = defaultdict(list)
    for doc_id in sorted(cases):
        if cases[doc_id].get("duplicate_of") is None:
            groups[cases[doc_id]["degradation"]].append(doc_id)

    test, dev = [], []
    for level in sorted(groups):
        ids = groups[level]
        rng.shuffle(ids)
        n_test = round(len(ids) * args.test_share)
        test += ids[:n_test]
        dev += ids[n_test:]

    # duplicates follow their originals
    test_set = set(test)
    for doc_id in sorted(cases):
        original = cases[doc_id].get("duplicate_of")
        if original is not None:
            (test if original in test_set else dev).append(doc_id)

    split = {"dev": sorted(dev), "test": sorted(test)}
    SPLIT_PATH.write_text(json.dumps(split, indent=2), encoding="utf-8")
    print(f"dev: {len(dev)} documents, test: {len(test)} documents -> {SPLIT_PATH}")


if __name__ == "__main__":
    main()
