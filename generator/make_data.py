"""Generate synthetic invoice data (ground truth).

Run from the repository root:
    python -m generator.make_data --count 60 --seed 42

Writes one JSON per invoice to data/ground_truth/inv_XXXX.json.
The data is internally consistent (valid NIP checksum, net + VAT = gross,
due date after issue date). Rendering to PDF is a separate step.
"""

import argparse
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from api.schemas import InvoiceData

OUT_DIR = Path("data/ground_truth")

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for i in range(1, args.count + 1):
        invoice = make_invoice(rng)
        path = OUT_DIR / f"inv_{i:04d}.json"
        path.write_text(invoice.model_dump_json(indent=2), encoding="utf-8")

    print(f"Generated {args.count} ground truth files in {OUT_DIR}")


if __name__ == "__main__":
    main()
