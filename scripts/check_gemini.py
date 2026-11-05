"""Check that the Gemini API key works and list the models available to it.

Run from the repository root:
    python scripts/check_gemini.py
    python scripts/check_gemini.py gemini-2.5-flash-lite     (test a specific model)

Needs a .env file in the repo root containing:
    GEMINI_API_KEY=your_key
"""

import os
import sys

from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    sys.exit("GEMINI_API_KEY not found. Create a .env file in the repo root.")

client = genai.Client(api_key=api_key)

print("Models that support generateContent:")
try:
    for model in client.models.list():
        actions = getattr(model, "supported_actions", None) or []
        if "generateContent" in actions:
            print("  ", model.name)
except Exception as exc:  # noqa: BLE001
    sys.exit(f"Could not list models: {exc}")

model_name = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash-lite"
print(f"\nTest call with model: {model_name}")
try:
    response = client.models.generate_content(
        model=model_name,
        contents="Odpowiedz jednym słowem: czy działasz?",
    )
    print("Answer:", response.text)
except Exception as exc:  # noqa: BLE001
    print("Call failed:", exc)
