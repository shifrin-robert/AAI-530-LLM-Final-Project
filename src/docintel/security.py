"""Security helpers: prompt-injection heuristics, input sanitization, safe errors, logging.

These are *defence-in-depth* measures, not guarantees. The primary prompt-injection
defence is structural (system/user/source separation plus explicit instructions that
document text is untrusted data); the heuristics below only flag suspicious passages so
that both the model and the user are warned.
"""

from __future__ import annotations

import logging
import re
import unicodedata

LOGGER_NAME = "docintel"

# Patterns that commonly appear in prompt-injection attempts embedded in documents.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b"
            r"(previous|prior|above|earlier|all|any|system|your)\b[^.\n]{0,30}"
            r"\b(instructions?|rules?|prompts?|guidelines?|directions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(reveal|print|show|repeat|output|disclose|display)\b[^.\n]{0,40}"
            r"\b(system|hidden|secret|internal|developer|initial)\s+(prompt|instructions?|message|rules)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\b(you are now|from now on,? you|act as (an?|the)\b|pretend to be|new instructions?:|"
            r"system (notice|message|override)\s*:)",
            re.IGNORECASE,
        ),
    ),
    (
        "assistant_directive",
        re.compile(
            r"\b(the|any|all|an?)\s+(ai\s+(assistants?|models?|systems?)|assistants?|language models?|"
            r"llms?|chatbots?|ai)\s+"
            r"(must|should|shall|is required to|are required to|will|needs? to)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "evidence_suppression",
        re.compile(
            r"\b(disregard|ignore|discard)\s+(all|any|the)?\s*(other\s+)?"
            r"(documents?|sources?|evidence|files?|passages?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "citation_manipulation",
        re.compile(
            r"\b(always\s+)?(cite|citation|reference)\b[^.\n]{0,30}\b(source\s+)?S\d+\b"
            r"|\bfabricate\b|\binvent (a |the )?(citation|source)",
            re.IGNORECASE,
        ),
    ),
    (
        "chat_markup",
        re.compile(
            r"(<\|im_start\|>|<\|system\|>|\[INST\]|<<SYS>>|</?(system|assistant)>)", re.IGNORECASE
        ),
    ),
)

INJECTION_FLAG = "instruction_like_text"


def detect_instruction_like_text(text: str) -> list[str]:
    """Return the names of injection heuristics that match ``text`` (empty list if none)."""
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_inline(value: str, max_len: int = 120) -> str:
    """Make an untrusted short string (file name, metadata) safe to embed in a prompt or UI line."""
    value = unicodedata.normalize("NFKC", value)
    value = _CONTROL_CHARS.sub("", value)
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = value.replace("<", "(").replace(">", ")").replace('"', "'")
    value = re.sub(r"\s{2,}", " ", value).strip()
    if len(value) > max_len:
        value = value[: max_len - 1].rstrip() + "…"
    return value


def sanitize_filename(name: str) -> str:
    """Keep only the base name, strip path tricks and unsafe characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = sanitize_inline(base, max_len=100)
    base = re.sub(r"[^\w.\- ()\[\]&,+'’]", "_", base)
    base = base.lstrip(". ") or "document.pdf"
    return base


def neutralize_source_delimiters(text: str) -> str:
    """Prevent document text from closing or opening our <source> blocks."""
    return re.sub(
        r"<(/?)\s*(source|sources|system|instructions)\b", r"‹\1\2", text, flags=re.IGNORECASE
    )


# --------------------------------------------------------------------------- errors

GENERIC_ERROR = "Something went wrong while processing your request. Please try again."


def safe_error_message(exc: BaseException) -> str:
    """User-facing message for an exception: no stack traces, no document content."""
    user_message = getattr(exc, "user_message", None)
    if isinstance(user_message, str) and user_message:
        return user_message
    return GENERIC_ERROR


# --------------------------------------------------------------------------- logging


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def configure_logging(level: int = logging.INFO) -> None:
    """Configure package logging once.

    Policy: log events, identifiers, counts, timings and error *types* only. Document text,
    user questions, prompts, model outputs and API keys are never logged.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
