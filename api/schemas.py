"""Data contract for the invoice extraction project.

Two layers:
1. InvoiceData            - plain values only. Used for ground truth files.
2. ExtractionResponse     - what the API returns: every field wrapped with
                            confidence, source and flags.

Keeping the field names identical in both layers makes evaluation trivial:
compare ExtractionResponse.fields.<name>.value with InvoiceData.<name>.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# --------------------------------------------------------------------------
# Layer 1: plain invoice data (ground truth)
# --------------------------------------------------------------------------
class InvoiceData(BaseModel):
    invoice_number: str
    issue_date: date
    due_date: date | None = None
    seller_name: str
    seller_nip: str  # 10 digits, no dashes or spaces
    buyer_name: str
    buyer_nip: str | None = None  # buyer may be a private person
    currency: str = "PLN"  # ISO 4217
    net_amount: Decimal
    vat_amount: Decimal
    gross_amount: Decimal


# --------------------------------------------------------------------------
# Layer 2: API response
# --------------------------------------------------------------------------
class FieldFlag(str, Enum):
    """Reasons why a field may be doubtful. Used by UiPath and for analysis."""

    NOT_FOUND_IN_TEXT = "not_found_in_text"  # value not present in document text
    INVALID_FORMAT = "invalid_format"  # e.g. NIP with wrong length
    CHECKSUM_FAILED = "checksum_failed"  # e.g. NIP checksum
    SUM_MISMATCH = "sum_mismatch"  # net + VAT != gross
    DATE_INCONSISTENT = "date_inconsistent"  # e.g. due date before issue date
    METHODS_DISAGREE = "methods_disagree"  # two extraction methods differ
    MISSING = "missing"  # nothing extracted


class DocumentFlag(str, Enum):
    """Problems concerning the whole document."""

    LOW_QUALITY_SCAN = "low_quality_scan"
    POSSIBLE_CORRECTION_INVOICE = "possible_correction_invoice"
    UNREADABLE = "unreadable"
    NOT_AN_INVOICE = "not_an_invoice"


class Source(BaseModel):
    """Where in the document the value came from (helps the human reviewer)."""

    page: int | None = Field(default=None, ge=1)
    snippet: str | None = None  # short text fragment around the value


class FieldResult(BaseModel, Generic[T]):
    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Source | None = None
    flags: list[FieldFlag] = Field(default_factory=list)


class InvoiceFields(BaseModel):
    invoice_number: FieldResult[str]
    issue_date: FieldResult[date]
    due_date: FieldResult[date]
    seller_name: FieldResult[str]
    seller_nip: FieldResult[str]
    buyer_name: FieldResult[str]
    buyer_nip: FieldResult[str]
    currency: FieldResult[str]
    net_amount: FieldResult[Decimal]
    vat_amount: FieldResult[Decimal]
    gross_amount: FieldResult[Decimal]


class ExtractionMeta(BaseModel):
    model_version: str
    extraction_method: str  # e.g. "text_llm" or "vision_llm"
    processing_time_ms: int
    cost_usd: float | None = None


class ExtractionResponse(BaseModel):
    document_id: str
    fields: InvoiceFields
    document_flags: list[DocumentFlag] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    meta: ExtractionMeta
