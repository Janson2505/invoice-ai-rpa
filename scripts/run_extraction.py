"""Run extraction on documents and save predictions to data/predictions/<run>/.

Run from the repository root:
    python scripts/run_extraction.py --run try1 --limit 5
    python scripts/run_extraction.py --run flash_lite_v1 --model gemini-3.5-flash-lite

Already processed documents are skipped, so an interrupted run can be resumed
by running the same command again.

Use --subset dev while developing. The test set is for the final report only.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# make "api" importable when running as a script from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from google import genai  # noqa: E402

from api.extractor import extract_pdf  # noqa: E402

RAW_DIR = Path("data/raw")
SPLIT_PATH = Path("data/split.json")
PRED_ROOT = Path("data/predictions")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="name of this run, e.g. try1")
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--subset", choices=["dev", "test"], default="dev")
    parser.add_argument("--limit", type=int, default=None, help="only the first N documents")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between requests (free tier limits)")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not found. Check your .env file.")

    if args.subset == "test":
        answer = input("The TEST set should be used only for final results. Type TEST to continue: ")
        if answer.strip() != "TEST":
            sys.exit("Cancelled.")

    client = genai.Client(api_key=api_key)

    doc_ids = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))[args.subset]
    if args.limit:
        doc_ids = doc_ids[: args.limit]

    out_dir = PRED_ROOT / args.run
    out_dir.mkdir(parents=True, exist_ok=True)

    done = failed = 0
    for n, doc_id in enumerate(doc_ids, start=1):
        out_path = out_dir / f"{doc_id}.json"
        if out_path.exists():
            print(f"[{n}/{len(doc_ids)}] {doc_id} already done, skipping")
            continue

        pdf_bytes = (RAW_DIR / f"{doc_id}.pdf").read_bytes()
        try:
            fields, meta = extract_pdf(client, args.model, pdf_bytes)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[{n}/{len(doc_ids)}] {doc_id} FAILED: {exc}")
            continue

        record = {**fields, "_meta": meta}
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        done += 1
        print(f"[{n}/{len(doc_ids)}] {doc_id} ok ({meta['seconds']}s, tokens in/out: {meta['prompt_tokens']}/{meta['output_tokens']})")
        time.sleep(args.delay)

    print(f"\nFinished: {done} new, {failed} failed. Predictions in {out_dir}")


if __name__ == "__main__":
    main()
