"""Generate synthetic invoice data (ground truth) including hard cases.

Run from the repository root:
    python -m generator.make_data --count 60 --seed 42

Writes:
    data/ground_truth/inv_XXXX.json   - what is PRINTED on each invoice
    data/cases.json                   - description of each document: case type,
                                        how it will be degraded (scan/photo) and
                                        which flags a good system should raise

Hard cases (a few of each, chosen with the seed):
    missing_due_date   - no payment term on the invoice
    wrong_sum          - printed gross != net + VAT  (expected flag: sum_mismatch)
    bad_nip_checksum   - seller NIP with a wrong checksum (expected: checksum_failed)
    correction_invoice - "Faktura korygująca", negative amounts
    duplicate          - exact copy of another invoice under a new file name

Ground truth always equals what is printed, even when it is wrong. Detecting
that something is wrong is the job of the validation layer.
"""

import argparse
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from api.schemas import InvoiceData

OUT_DIR = Path("data/ground_truth")
CASES_PATH = Path("data/cases.json")

NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)

NAME_WORDS = [
    "Alfa", "Beta", "Gamma", "Delta", "Orion", "Nova", "Polaris", "Atlas",
    "Vega", "Mazovia", "Silesia", "Baltic", "Karpaty", "Nordic", "Terra",
    "Optima", "Prime", "Zenit", "Horyzont", "Meridian",
]
NAME_SECTORS = [
    "Systemy", "Logistyka", "Consulting", "Transport", "Budownictwo",
    "Technologie", "Handel", "Serwis", "Media", "Energia", "Finanse",
]
LEGAL_FORMS = ["Sp. z o.o.", "S.A.", "Sp. j.", "Sp. k."]
PRIVATE_NAMES = [
    "Jan Kowalski", "Anna Nowak", "Piotr Wiśniewski", "Maria Wójcik",
    "Tomasz Kamiński", "Katarzyna Lewandowska",
]
VAT_RATES = [Decimal("0.23"), Decimal("0.08"), Decimal("0.05")]
VAT_WEIGHTS = [0.8, 0.15, 0.05]
TWO_PLACES = Decimal("0.01")

DEGRADATIONS = ["digital", "scan_good", "scan_bad", "photo"]
DEGRADATION_WEIGHTS = [0.5, 0.2, 0.15, 0.15]
LOW_QUALITY = {"scan_bad", "photo"}


def make_nip(rng: random.Random) -> str:
    """Random 10-digit NIP with a valid checksum."""
    while True:
        digits = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(8)]
        check = sum(d * w for d, w in zip(digits, NIP_WEIGHTS)) % 11
        if check != 10:  # checksum 10 means the NIP is invalid
            return "".join(map(str, digits)) + str(check)


def make_company_name(rng: random.Random) -> str:
    return f"{rng.choice(NAME_WORDS)} {rng.choice(NAME_SECTORS)} {rng.choice(LEGAL_FORMS)}"


def make_invoice_number(rng: random.Random, issue: date) -> str:
    n = rng.randint(1, 999)
    style = rng.choice(["slash", "reverse", "short"])
    if style == "slash":
        return f"FV/{issue.year}/{issue.month:02d}/{n:04d}"
    if style == "reverse":
        return f"{n}/{issue.month:02d}/{issue.year}"
    return f"FS {n}/{issue.year}"


def make_invoice(rng: random.Random) -> InvoiceData:
    issue = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    due = issue + timedelta(days=rng.choice([7, 14, 21, 30]))

    net = (Decimal(rng.randint(10_000, 2_000_000)) / 100).quantize(TWO_PLACES)
    rate = rng.choices(VAT_RATES, weights=VAT_WEIGHTS)[0]
    vat = (net * rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    # ~10% of buyers are private persons without a NIP
    if rng.random() < 0.10:
        buyer_name, buyer_nip = rng.choice(PRIVATE_NAMES), None
    else:
        buyer_name, buyer_nip = make_company_name(rng), make_nip(rng)

    return InvoiceData(
        invoice_number=make_invoice_number(rng, issue),
        issue_date=issue,
        due_date=due,
        seller_name=make_company_name(rng),
        seller_nip=make_nip(rng),
        buyer_name=buyer_name,
        buyer_nip=buyer_nip,
        currency=rng.choices(["PLN", "EUR"], weights=[0.85, 0.15])[0],
        net_amount=net,
        vat_amount=vat,
        gross_amount=net + vat,
    )


# --------------------------------------------------------------------------
# Hard cases
# --------------------------------------------------------------------------
def break_nip(nip: str, rng: random.Random) -> str:
    """Change the last digit so that the checksum is guaranteed to be wrong."""
    return nip[:-1] + str((int(nip[-1]) + rng.randint(1, 9)) % 10)


def apply_hard_cases(invoices: list[InvoiceData], rng: random.Random):
    """Mutate some invoices in place. Returns (cases_by_index, duplicates)."""
    n = len(invoices)
    k = n // 20  # how many of each hard case (3 for 60 invoices)
    if k == 0:
        return {}, []

    pool = list(range(n))
    rng.shuffle(pool)

    def take() -> list[int]:
        return [pool.pop() for _ in range(k)]

    cases: dict[int, dict] = {}

    for i in take():
        invoices[i] = invoices[i].model_copy(update={"due_date": None})
        cases[i] = {"case": "missing_due_date", "expected_flags": {"due_date": ["missing"]}, "document_flags": []}

    for i in take():
        inv = invoices[i]
        offset = Decimal(rng.randint(10, 500)) * rng.choice([-1, 1])
        invoices[i] = inv.model_copy(update={"gross_amount": inv.gross_amount + offset})
        cases[i] = {"case": "wrong_sum", "expected_flags": {"gross_amount": ["sum_mismatch"]}, "document_flags": []}

    for i in take():
        invoices[i] = invoices[i].model_copy(update={"seller_nip": break_nip(invoices[i].seller_nip, rng)})
        cases[i] = {"case": "bad_nip_checksum", "expected_flags": {"seller_nip": ["checksum_failed"]}, "document_flags": []}

    for i in take():
        inv = invoices[i]
        invoices[i] = inv.model_copy(
            update={
                "invoice_number": "KOR/" + inv.invoice_number,
                "net_amount": -inv.net_amount,
                "vat_amount": -inv.vat_amount,
                "gross_amount": -inv.gross_amount,
            }
        )
        cases[i] = {
            "case": "correction_invoice",
            "expected_flags": {},
            "document_flags": ["possible_correction_invoice"],
        }

    duplicates = take()  # indices of invoices that will be copied
    return cases, duplicates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    # 1. clean base invoices (same sequence as before, so same data for same seed)
    invoices = [make_invoice(rng) for _ in range(args.count)]
    doc_ids = [f"inv_{i + 1:04d}" for i in range(args.count)]

    # 2. hard cases
    cases_by_index, duplicate_sources = apply_hard_cases(invoices, rng)

    cases: dict[str, dict] = {}
    for i, doc_id in enumerate(doc_ids):
        cases[doc_id] = cases_by_index.get(
            i, {"case": "clean", "expected_flags": {}, "document_flags": []}
        ).copy()
        cases[doc_id]["duplicate_of"] = None

    # 3. duplicates: exact copies under new ids
    for src in duplicate_sources:
        new_id = f"inv_{len(doc_ids) + 1:04d}"
        invoices.append(invoices[src].model_copy())
        doc_ids.append(new_id)
        cases[new_id] = {
            "case": "duplicate",
            "expected_flags": {},
            "document_flags": [],
            "duplicate_of": doc_ids[src],
        }

    # 4. how each document will look (digital PDF, scan, photo)
    for doc_id in doc_ids:
        level = rng.choices(DEGRADATIONS, weights=DEGRADATION_WEIGHTS)[0]
        cases[doc_id]["degradation"] = level
        if level in LOW_QUALITY:
            cases[doc_id]["document_flags"] = cases[doc_id]["document_flags"] + ["low_quality_scan"]

    # 5. write files (remove leftovers from earlier runs first)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("inv_*.json"):
        old.unlink()
    for doc_id, invoice in zip(doc_ids, invoices):
        (OUT_DIR / f"{doc_id}.json").write_text(invoice.model_dump_json(indent=2), encoding="utf-8")

    CASES_PATH.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Generated {len(doc_ids)} ground truth files in {OUT_DIR}")
    print(f"Case descriptions written to {CASES_PATH}")


if __name__ == "__main__":
    main()
