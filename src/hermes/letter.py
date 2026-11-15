"""The settlement letter (ticket 24): model-written prose around placeholders, numbers from the engine.

The model never writes a figure. Its draft is checked (no digit absent from the engine values, no
banned phrase, only known placeholders, the offer placeholder present); on any failure, no key, an
exhausted limit or a refused data mode, the engine's plain template is used. Neutral notes from the
buyer statement are appended by the template, never by the model.
"""

import json
import os
import re

from hermes.checks import check_drafting
from hermes.llm import DataModeRefused, Document, GeminiBackend, ModelClient

TASK, PROMPT_VERSION = "draft_letter", "letter-1"
SCHEMA = {"type": "object", "required": ["body"], "properties": {"body": {"type": "string"}}}
SYSTEM = (
    "You write the prose of a polite settlement letter from a small supplier to a late-paying buyer. "
    "Write the letter body using only the placeholders in the list, written {{name}}, for every "
    "name, date and amount. Never write a digit or a figure yourself. Do not threaten, do not "
    "mention courts or legal action, and do not state any legal conclusion. Include {{offer}}. "
    'Reply as JSON: {"body": "..."}.')
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def client_from_env() -> ModelClient | None:
    """A Gemini-backed client when a key is set, else None (the plain template is used)."""
    return ModelClient(GeminiBackend()) if os.environ.get("GEMINI_API_KEY") else None


def letter_document(values: dict) -> Document:
    """The engine values the draft is about, as the one input document of the call."""
    return Document(json.dumps(values, sort_keys=True).encode(), "application/json")


def with_notes(text: str, notes: list[str]) -> str:
    return text.rstrip("\n") + "\n\nFor information:\n" + "".join(f"- {n}\n" for n in notes)


def draft_letter(model: ModelClient | None, result: dict) -> tuple[str, str]:
    """(letter text, "model" or "template") for a settlement engine result."""
    values, notes = result["letter"]["values"], result["buyer_statement"]["notes"]
    plain = (with_notes(result["letter"]["text"], notes), "template")
    if model is None:
        return plain
    try:
        res = model.call(TASK, "flash", PROMPT_VERSION, SYSTEM,
                         "Placeholders: " + ", ".join(values), letter_document(values), SCHEMA)
    except DataModeRefused:
        return plain
    if res.status != "ok":
        return plain
    body = res.data["body"]
    if (check_drafting(body, values) or "{{offer}}" not in body
            or not set(_PLACEHOLDER.findall(body)) <= values.keys()):
        return plain
    return with_notes(_PLACEHOLDER.sub(lambda m: values[m[1]], body), notes), "model"
