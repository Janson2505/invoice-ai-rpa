"""Render ground truth JSON files to PDF invoices using 3 different layouts.

Run from the repository root:
    python -m generator.render_pdf

Reads  data/ground_truth/inv_XXXX.json and data/cases.json
Writes data/raw/inv_XXXX.pdf and data/raw/manifest.csv

Documents marked as scan_good / scan_bad / photo in cases.json are converted
into image-only PDFs (no text layer) after rendering.

Each template shows the SAME data in a different layout, with different
labels, date formats, number formats and a few distractor elements
(e.g. an extra "sale date" and a bank account number).
"""

import argparse
import csv
import json
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from generator.degrade import pdf_to_scan

FONT_DIR = Path("generator/fonts")
W, H = A4

MONTHS_PL = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
]


# --------------------------------------------------------------------------
# Formatting helpers (each template uses a different style)
# --------------------------------------------------------------------------
def amount_spaced(v: str) -> str:  # 13170.69 -> "13 170,69"
    return f"{Decimal(v):,.2f}".replace(",", " ").replace(".", ",")


def amount_plain(v: str) -> str:  # 13170.69 -> "13170.69"
    return f"{Decimal(v):.2f}"


def amount_comma(v: str) -> str:  # 13170.69 -> "13170,69"
    return f"{Decimal(v):.2f}".replace(".", ",")


def date_dots(iso: str) -> str:  # 2026-05-16 -> "16.05.2026"
    d = date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def date_long(iso: str) -> str:  # 2026-05-16 -> "16 maja 2026"
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS_PL[d.month - 1]} {d.year}"


def nip_dashes(nip: str) -> str:  # 5252248481 -> "525-224-84-81"
    return f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:]}"


def nip_plain(nip: str) -> str:
    return nip


def is_correction(d: dict) -> bool:
    return Decimal(d["net_amount"]) < 0


def vat_rate(d: dict) -> int:
    return int(round(Decimal(d["vat_amount"]) / Decimal(d["net_amount"]) * 100))


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
def Y(mm_from_top: float) -> float:
    """Convert distance from the top of the page (mm) to a PDF y coordinate."""
    return H - mm_from_top * mm


def put(c, x, y, text, size=10, bold=False, align="left", color=colors.black):
    c.setFont("DejaVu-Bold" if bold else "DejaVu", size)
    c.setFillColor(color)
    if align == "right":
        c.drawRightString(x, y, text)
    elif align == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)


def party_block(c, x, y, title, name, nip, nip_fmt, size=10):
    put(c, x, y, title, size, bold=True)
    put(c, x, y - 6 * mm, name, size)
    if nip:  # private persons have no NIP
        put(c, x, y - 12 * mm, f"NIP: {nip_fmt(nip)}", size)


# --------------------------------------------------------------------------
# Template 1: classic
# --------------------------------------------------------------------------
def template_classic(c, d):
    cur = d["currency"]
    title = "Faktura korygująca nr" if is_correction(d) else "Faktura VAT nr"
    put(c, 20 * mm, Y(25), f"{title} {d['invoice_number']}", 16, True)
    put(c, W - 20 * mm, Y(25), f"Data wystawienia: {date_dots(d['issue_date'])}", align="right")
    if d.get("due_date"):
        put(c, W - 20 * mm, Y(31), f"Termin płatności: {date_dots(d['due_date'])}", align="right")

    party_block(c, 20 * mm, Y(50), "Sprzedawca", d["seller_name"], d["seller_nip"], nip_dashes)
    party_block(c, 110 * mm, Y(50), "Nabywca", d["buyer_name"], d["buyer_nip"], nip_dashes)

    # table
    c.setStrokeColor(colors.black)
    c.line(20 * mm, Y(82), W - 20 * mm, Y(82))
    put(c, 20 * mm, Y(80), "Lp.", 8, True)
    put(c, 30 * mm, Y(80), "Nazwa usługi", 8, True)
    put(c, 115 * mm, Y(80), "Netto", 8, True, "right")
    put(c, 130 * mm, Y(80), "VAT %", 8, True, "right")
    put(c, 158 * mm, Y(80), "Kwota VAT", 8, True, "right")
    put(c, W - 20 * mm, Y(80), "Brutto", 8, True, "right")
    put(c, 20 * mm, Y(90), "1", 9)
    put(c, 30 * mm, Y(90), "Usługi wg umowy", 9)
    put(c, 115 * mm, Y(90), amount_spaced(d["net_amount"]), 9, align="right")
    put(c, 130 * mm, Y(90), f"{vat_rate(d)}%", 9, align="right")
    put(c, 158 * mm, Y(90), amount_spaced(d["vat_amount"]), 9, align="right")
    put(c, W - 20 * mm, Y(90), amount_spaced(d["gross_amount"]), 9, align="right")
    c.line(20 * mm, Y(94), W - 20 * mm, Y(94))

    # totals
    put(c, 150 * mm, Y(108), "Razem netto:", align="right")
    put(c, W - 20 * mm, Y(108), f"{amount_spaced(d['net_amount'])} {cur}", align="right")
    put(c, 150 * mm, Y(114), "VAT:", align="right")
    put(c, W - 20 * mm, Y(114), f"{amount_spaced(d['vat_amount'])} {cur}", align="right")
    put(c, 150 * mm, Y(122), "Do zapłaty:", 11, True, "right")
    put(c, W - 20 * mm, Y(122), f"{amount_spaced(d['gross_amount'])} {cur}", 11, True, "right")


# --------------------------------------------------------------------------
# Template 2: modern (colored header, stacked parties, plain numbers)
# --------------------------------------------------------------------------
def template_modern(c, d):
    cur = d["currency"]
    blue = colors.HexColor("#1F4E79")
    c.setFillColor(blue)
    c.rect(0, H - 38 * mm, W, 38 * mm, stroke=0, fill=1)
    put(c, 20 * mm, Y(17), "FAKTURA KORYGUJĄCA" if is_correction(d) else "FAKTURA", 22, True, color=colors.white)
    put(c, 20 * mm, Y(27), f"Nr {d['invoice_number']}", 12, color=colors.white)
    put(c, W - 20 * mm, Y(17), f"Wystawiono: {d['issue_date']}", 10, align="right", color=colors.white)
    if d.get("due_date"):
        put(c, W - 20 * mm, Y(24), f"Zapłacić do: {d['due_date']}", 10, align="right", color=colors.white)

    party_block(c, 20 * mm, Y(58), "Wystawca", d["seller_name"], d["seller_nip"], nip_plain, 11)
    party_block(c, 20 * mm, Y(88), "Odbiorca", d["buyer_name"], d["buyer_nip"], nip_plain, 11)

    # table header band
    c.setFillColor(colors.HexColor("#E8EEF4"))
    c.rect(20 * mm, Y(122), W - 40 * mm, 9 * mm, stroke=0, fill=1)
    put(c, 24 * mm, Y(120), "Opis", 9, True)
    put(c, 110 * mm, Y(120), "Netto", 9, True, "right")
    put(c, 145 * mm, Y(120), "VAT", 9, True, "right")
    put(c, W - 24 * mm, Y(120), "Brutto", 9, True, "right")
    put(c, 24 * mm, Y(131), "Usługi wg umowy", 10)
    put(c, 110 * mm, Y(131), amount_plain(d["net_amount"]), 10, align="right")
    put(c, 145 * mm, Y(131), amount_plain(d["vat_amount"]), 10, align="right")
    put(c, W - 24 * mm, Y(131), amount_plain(d["gross_amount"]), 10, align="right")

    # totals box
    c.setStrokeColor(blue)
    c.setLineWidth(1.2)
    c.rect(105 * mm, Y(168), W - 125 * mm, 28 * mm, stroke=1, fill=0)
    put(c, 110 * mm, Y(148), "Suma netto", 10)
    put(c, W - 24 * mm, Y(148), f"{amount_plain(d['net_amount'])} {cur}", 10, align="right")
    put(c, 110 * mm, Y(155), f"Podatek VAT ({vat_rate(d)}%)", 10)
    put(c, W - 24 * mm, Y(155), f"{amount_plain(d['vat_amount'])} {cur}", 10, align="right")
    put(c, 110 * mm, Y(163), "Razem brutto", 11, True)
    put(c, W - 24 * mm, Y(163), f"{amount_plain(d['gross_amount'])} {cur}", 11, True, "right")


# --------------------------------------------------------------------------
# Template 3: dense (small font, long dates, buyer on the left, distractors)
# --------------------------------------------------------------------------
def template_dense(c, d):
    cur = d["currency"]
    title = "Faktura korygująca nr" if is_correction(d) else "Faktura nr"
    put(c, W / 2, Y(15), f"{title} {d['invoice_number']}", 12, True, "center")
    put(c, 15 * mm, Y(25), f"Data wystawienia: {date_long(d['issue_date'])}", 8)
    put(c, 15 * mm, Y(29), f"Data sprzedaży: {date_long(d['issue_date'])}", 8)  # distractor
    if d.get("due_date"):
        put(c, 15 * mm, Y(33), f"Płatne do: {date_long(d['due_date'])}", 8)

    party_block(c, 15 * mm, Y(48), "Klient", d["buyer_name"], d["buyer_nip"], nip_plain, 8)
    party_block(c, 110 * mm, Y(48), "Dostawca", d["seller_name"], d["seller_nip"], nip_dashes, 8)

    c.setStrokeColor(colors.grey)
    c.line(15 * mm, Y(72), W - 15 * mm, Y(72))
    for x, label in [(15, "Lp."), (25, "Towar / usługa")]:
        put(c, x * mm, Y(70), label, 7, True)
    put(c, 110 * mm, Y(70), "Wart. netto", 7, True, "right")
    put(c, 130 * mm, Y(70), "Stawka", 7, True, "right")
    put(c, 155 * mm, Y(70), "Kwota VAT", 7, True, "right")
    put(c, W - 15 * mm, Y(70), "Wart. brutto", 7, True, "right")
    put(c, 15 * mm, Y(77), "1", 8)
    put(c, 25 * mm, Y(77), "Usługi wg umowy", 8)
    put(c, 110 * mm, Y(77), amount_comma(d["net_amount"]), 8, align="right")
    put(c, 130 * mm, Y(77), f"{vat_rate(d)}%", 8, align="right")
    put(c, 155 * mm, Y(77), amount_comma(d["vat_amount"]), 8, align="right")
    put(c, W - 15 * mm, Y(77), amount_comma(d["gross_amount"]), 8, align="right")
    c.line(15 * mm, Y(80), W - 15 * mm, Y(80))

    # totals on the left side
    put(c, 15 * mm, Y(90), "Wartość netto:", 8)
    put(c, 80 * mm, Y(90), f"{amount_comma(d['net_amount'])} {cur}", 8, align="right")
    put(c, 15 * mm, Y(95), "Kwota VAT:", 8)
    put(c, 80 * mm, Y(95), f"{amount_comma(d['vat_amount'])} {cur}", 8, align="right")
    put(c, 15 * mm, Y(100), "Wartość brutto:", 8, True)
    put(c, 80 * mm, Y(100), f"{amount_comma(d['gross_amount'])} {cur}", 8, True, "right")

    # distractors
    put(c, 15 * mm, Y(115), "Nr konta: PL 61 1090 1014 0000 0712 1981 2874", 7)
    put(c, 15 * mm, Y(120), "Dokument wygenerowany automatycznie.", 7)


TEMPLATES = [
    ("classic", template_classic),
    ("modern", template_modern),
    ("dense", template_dense),
]


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))


def render(data: dict, path: Path, template_fn) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    template_fn(c, data)
    c.showPage()
    c.save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt-dir", default="data/ground_truth")
    parser.add_argument("--out-dir", default="data/raw")
    parser.add_argument("--cases", default="data/cases.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    gt_dir, out_dir = Path(args.gt_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("inv_*.pdf"):
        old.unlink()
    register_fonts()

    cases_path = Path(args.cases)
    cases = json.loads(cases_path.read_text(encoding="utf-8")) if cases_path.exists() else {}
    rng = random.Random(args.seed)

    files = sorted(gt_dir.glob("inv_*.json"))
    rows = []
    for i, f in enumerate(files):
        data = json.loads(f.read_text(encoding="utf-8"))
        name, template_fn = TEMPLATES[i % len(TEMPLATES)]
        pdf_path = out_dir / f"{f.stem}.pdf"
        render(data, pdf_path, template_fn)

        info = cases.get(f.stem, {})
        degradation = info.get("degradation", "digital")
        if degradation != "digital":
            pdf_to_scan(pdf_path, degradation, rng)

        rows.append(
            {
                "doc_id": f.stem,
                "template": name,
                "case": info.get("case", "clean"),
                "degradation": degradation,
            }
        )

    with open(out_dir / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["doc_id", "template", "case", "degradation"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Rendered {len(rows)} PDFs into {out_dir}")


if __name__ == "__main__":
    main()
