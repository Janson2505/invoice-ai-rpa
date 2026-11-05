"""Invoice field extraction with a vision-capable LLM (Gemini).

Approach B: the whole PDF is sent to the model, which reads text-based PDFs
and scans/photos alike. The model is forced to answer with JSON matching
RawExtraction (structured output).

This module is deliberately small and provider-specific: only extract_pdf()
talks to Gemini, so another provider can be added next to it later.
"""

import time

from google.genai import types
from pydantic import BaseModel, Field

PROMPT = """You are extracting data from a Polish VAT invoice (a PDF that may be a clean document, a scan or a phone photo).

Return the following fields exactly as they are PRINTED on the document.

Rules:
- Copy values, never calculate, correct or guess. If the printed totals do not add up, still return the printed numbers.
- Dates: format YYYY-MM-DD.
- Amounts: plain decimal with a dot and two decimals, no thousands separators, no currency symbol (e.g. 13170.69). Keep the minus sign if the amount is negative (correction invoices).
- NIP (Polish tax id): digits only, no dashes, spaces or country prefix.
- Seller = the party issuing the invoice (labels such as Sprzedawca, Wystawca, Dostawca). Buyer = the party receiving it (Nabywca, Odbiorca, Klient).
- issue_date is the date of issue (Data wystawienia / Wystawiono). Do not use the sale date or any other date for it.
- due_date is the payment deadline (Termin płatności / Zapłacić do / Płatne do).
- net_amount, vat_amount, gross_amount are the invoice TOTALS (Razem netto, VAT, Do zapłaty / Razem brutto).
- currency is a 3-letter ISO code (PLN, EUR).
- If a field is not present on the document (for example a private buyer has no NIP, or there is no due date), return null.
- Ignore bank account numbers and other unrelated numbers."""


class RawExtraction(BaseModel):
    """What the model returns. Everything is text; normalization happens later."""

    invoice_number: str | None = Field(default=None, description="Invoice number as printed")
    issue_date: str | None = Field(default=None, description="Issue date, YYYY-MM-DD")
    due_date: str | None = Field(default=None, description="Payment deadline, YYYY-MM-DD, null if absent")
    seller_name: str | None = Field(default=None, description="Seller company name")
    seller_nip: str | None = Field(default=None, description="Seller NIP, digits only")
    buyer_name: str | None = Field(default=None, description="Buyer company or person name")
    buyer_nip: str | None = Field(default=None, description="Buyer NIP, digits only, null if absent")
    currency: str | None = Field(default=None, description="ISO currency code")
    net_amount: str | None = Field(default=None, description="Total net amount, e.g. 13170.69")
    vat_amount: str | None = Field(default=None, description="Total VAT amount")
    gross_amount: str | None = Field(default=None, description="Total gross amount")


RETRYABLE_CODES = (429, 500, 503)


def extract_pdf(client, model: str, pdf_bytes: bytes, max_attempts: int = 4):
    """Extract invoice fields from one PDF.

    Returns (fields_dict, meta_dict). Retries on rate limits (429) and
    temporary server errors; other errors are raised to the caller.
    """
    contents = [
        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
        PROMPT,
    ]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RawExtraction,
    )

    for attempt in range(1, max_attempts + 1):
        started = time.time()
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            fields = RawExtraction.model_validate_json(response.text).model_dump()
            usage = getattr(response, "usage_metadata", None)
            meta = {
                "model": model,
                "seconds": round(time.time() - started, 2),
                "attempts": attempt,
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
            }
            return fields, meta
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            if code not in RETRYABLE_CODES or attempt == max_attempts:
                raise
            wait = 5 * 2 ** (attempt - 1)  # 5s, 10s, 20s
            print(f"  retry in {wait}s ({exc.__class__.__name__}, code {code})")
            time.sleep(wait)
