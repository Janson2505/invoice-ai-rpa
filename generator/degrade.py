"""Turn a clean PDF into an image-only PDF that imitates a scan or a photo.

The result has NO text layer, so extraction needs OCR or a vision model.

Levels:
    scan_good - decent office scanner
    scan_bad  - old scanner: skew, blur, noise, low contrast, strong JPEG
    photo     - phone photo: bigger skew, shadow gradient, dark margins
"""

import io
import random
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

LEVELS = {
    "scan_good": dict(dpi=150, rotate=0.6, blur=0.4, noise=8, jpeg=70, contrast=0.95, shadow=0.0, bg=255, margin=0),
    "scan_bad": dict(dpi=110, rotate=2.0, blur=1.0, noise=22, jpeg=35, contrast=0.8, shadow=0.0, bg=255, margin=0),
    "photo": dict(dpi=100, rotate=4.0, blur=0.8, noise=14, jpeg=45, contrast=0.85, shadow=0.35, bg=170, margin=40),
}


def rasterize(pdf_path: Path, dpi: int) -> Image.Image:
    """Render the first page of a PDF to a PIL image."""
    doc = fitz.open(str(pdf_path))
    try:
        png_bytes = doc[0].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()
    return Image.open(io.BytesIO(png_bytes)).convert("L")


def degrade_image(img: Image.Image, params: dict, rng: random.Random) -> Image.Image:
    img = img.convert("L")

    # dark margin around the page (photo on a table)
    if params["margin"]:
        img = ImageOps.expand(img, border=params["margin"], fill=params["bg"])

    # random skew
    angle = rng.uniform(-params["rotate"], params["rotate"])
    img = img.rotate(angle, expand=True, fillcolor=params["bg"], resample=Image.BICUBIC)

    # uneven lighting: linear shadow from one side
    if params["shadow"]:
        w, h = img.size
        gradient = Image.linear_gradient("L").resize((w, h))
        gradient = gradient.rotate(rng.choice([0, 90, 180, 270]), expand=True).resize((w, h))
        s = params["shadow"]
        shade = gradient.point(lambda v: int(255 * (1 - s) + v * s))
        img = ImageChops.multiply(img, shade)

    img = img.filter(ImageFilter.GaussianBlur(params["blur"]))
    img = ImageEnhance.Contrast(img).enhance(params["contrast"])

    # gaussian noise centred on 128, so subtract 128 when adding
    noise = Image.effect_noise(img.size, params["noise"])
    img = ImageChops.add(img, noise, scale=1.0, offset=-128)

    # JPEG artifacts
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=params["jpeg"])
    buf.seek(0)
    return Image.open(buf).convert("L")


def pdf_to_scan(pdf_path: Path, level: str, rng: random.Random) -> None:
    """Replace the PDF with a degraded, image-only version of itself."""
    params = LEVELS[level]
    img = degrade_image(rasterize(pdf_path, params["dpi"]), params, rng)
    img.save(str(pdf_path), "PDF", resolution=params["dpi"])
