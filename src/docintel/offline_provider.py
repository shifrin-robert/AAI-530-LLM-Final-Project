"""Offline extractive baseline provider (``DOCINTEL_PROVIDER=mock``).

This is **not** a language model. It deterministically selects and copies sentences from the
retrieved sources using lexical overlap and regular expressions, and returns them in the same
structured schemas the real models use. It exists so that:

* the full application can be demonstrated and tested without an API key or network access;
* the evaluation suite has a reproducible, zero-cost *baseline* that real models must beat.

Its outputs are always labelled as offline/extractive in the UI and in evaluation reports.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from docintel.config import Settings
from docintel.llm_client import LLMProvider, LLMResponseFormatError, StructuredRequest, TokenUsage
from docintel.models import (
    Citation,
    Claim,
    ComparisonFinding,
    ComparisonOutput,
    DatedItem,
    ExtractedItem,
    ExtractionOutput,
    JudgeVerdict,
    QAOutput,
    SectionNotes,
    SourcePassage,
    SummaryOutput,
    SummaryPoint,
)
from docintel.retrieval import tokenize

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
DATE_RE = re.compile(
    rf"\b(?:(?:{MONTHS})\.?\s+\d{{1,2}},\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})\b"
)
MONEY_RE = re.compile(
    r"(?:USD\s?|\$)\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?:\s?(?:million|thousand|k|M))?"
)
ORG_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z&'\-]+\s){0,4}(?:LLC|Inc\.|Inc|Ltd\.?|Corporation|Corp\.|University|Library|"
    r"Department|Council|Agency|Company|Group|Partners|Foundation|Institute|Authority|Bank)\b"
)
PERSON_ROLE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z]\.)?\s[A-Z][a-z]+(?:-[A-Z][a-z]+)?),\s+((?:Chief|Senior|Project|Program|"
    r"Finance|Operations|Account|Contract|Technical|Executive|Managing|Head|Director|Manager|Lead|"
    r"Coordinator|Officer|Analyst|Engineer|Controller|Counsel|President|Vice)[A-Za-z ,&\-]{0,60}?)(?=[.;)\n]|$)"
)

OBLIGATION_WORDS = re.compile(
    r"\b(shall|must|is required to|agrees to|will provide|obligat)", re.IGNORECASE
)
RESPONSIBILITY_WORDS = re.compile(r"\b(responsible for|owner|owns|accountable)\b", re.IGNORECASE)
DECISION_WORDS = re.compile(r"\b(decided|approved|agreed to|decision|resolved)\b", re.IGNORECASE)
RISK_WORDS = re.compile(
    r"\b(risk|delay|concern|overrun|penalt|breach|shortfall|exposure)", re.IGNORECASE
)
ACTION_WORDS = re.compile(
    r"\b(action item|will|due|by \w+ \d|deadline|follow up|to do)\b", re.IGNORECASE
)


def split_sentences(text: str) -> list[str]:
    """Split into sentences without merging separate paragraphs (e.g. a heading and its body)."""
    parts: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        flat = re.sub(r"\s+", " ", paragraph).strip()
        parts.extend(p.strip() for p in _SENTENCE_SPLIT.split(flat) if p.strip())
    return [p for p in parts if len(p) > 3]


def _truncate_words(text: str, max_words: int = 40) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words])


class ExtractiveOfflineProvider(LLMProvider):
    provider_name = "offline"
    is_offline = True

    def __init__(self, settings: Settings | None = None, **kwargs: Any):
        super().__init__("extractive-baseline", settings or Settings(provider="mock"), **kwargs)

    def _call(self, request: StructuredRequest) -> tuple[BaseModel, TokenUsage, str | None]:
        ctx = request.context
        sources: list[SourcePassage] = list(ctx.get("sources", []))
        handlers = {
            "qa": lambda: self._qa(ctx.get("question", ""), sources),
            "summary_map": lambda: self._section_notes(sources),
            "summary_reduce": lambda: self._reduce(ctx.get("section_notes", []), sources),
            "extraction": lambda: self._extract(sources, ctx.get("categories")),
            "comparison": lambda: self._compare(sources),
            "judge": lambda: JudgeVerdict(
                verdict="partially_supported", rationale="Offline baseline cannot judge support."
            ),
        }
        handler = handlers.get(request.task)
        if handler is None:
            raise LLMResponseFormatError(
                f"The offline provider does not support task '{request.task}'."
            )
        output = handler()
        if not isinstance(output, request.response_model):
            raise LLMResponseFormatError("Offline provider produced the wrong output type.")
        raw = output.model_dump_json()
        usage = TokenUsage(
            input_tokens=len(request.system + request.user) // 4,
            output_tokens=len(raw) // 4,
            estimated=True,
        )
        return output, usage, raw

    # ------------------------------------------------------------------ QA
    def _qa(self, question: str, sources: Sequence[SourcePassage]) -> QAOutput:
        q_terms = set(tokenize(question))
        scored: list[tuple[float, int, int, str, SourcePassage]] = []
        for rank, src in enumerate(sources):
            for pos, sentence in enumerate(split_sentences(src.text)):
                terms = set(tokenize(sentence))
                if not q_terms or not terms:
                    continue
                overlap = len(q_terms & terms) / len(q_terms)
                scored.append((overlap, -rank, -pos, sentence, src))
        scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        if not scored or scored[0][0] < 0.5:
            return QAOutput(
                status="insufficient_evidence",
                answer="The retrieved passages do not appear to contain an answer to this question "
                "(offline extractive baseline).",
                claims=[],
                conflicts=[],
                missing_information=[question.strip()],
                confidence="low",
            )
        best = scored[0][0]
        chosen: list[tuple[str, SourcePassage]] = []
        for overlap, _, _, sentence, src in scored:
            if overlap < max(0.5, 0.8 * best) or len(chosen) >= 2:
                break
            if all(sentence != s for s, _ in chosen):
                chosen.append((sentence, src))
        claims = [
            Claim(
                statement=sentence,
                claim_type="fact",
                citations=[Citation(source_id=src.source_id, quote=_truncate_words(sentence))],
            )
            for sentence, src in chosen
        ]
        answer = " ".join(f"{sentence} [{src.source_id}]" for sentence, src in chosen)
        return QAOutput(
            status="answered",
            answer=answer,
            claims=claims,
            conflicts=[],
            missing_information=[],
            confidence="medium" if best >= 0.75 else "low",
        )

    # ------------------------------------------------------------------ summaries
    def _section_notes(self, sources: Sequence[SourcePassage]) -> SectionNotes:
        def lead_sentence(text: str) -> str:
            # Skip headings ("3. Fees") and other short fragments: use the first real sentence.
            sentences = split_sentences(text) or [text]
            return next((s for s in sentences if len(s.split()) >= 6), sentences[0])

        firsts = [lead_sentence(s.text) for s in sources]
        summary = " ".join(
            f"{_truncate_words(t, 35)} [{s.source_id}]"
            for t, s in zip(firsts[:3], sources, strict=False)
        )
        key_points = [
            SummaryPoint(text=_truncate_words(t, 35), source_ids=[s.source_id])
            for t, s in zip(firsts, sources, strict=False)
        ]
        dates, actions, obligations, risks = [], [], [], []
        for src in sources:
            for sentence in split_sentences(src.text):
                for match in DATE_RE.findall(sentence):
                    dates.append(
                        DatedItem(
                            date=match,
                            description=_truncate_words(sentence, 30),
                            source_ids=[src.source_id],
                        )
                    )
                point = SummaryPoint(text=_truncate_words(sentence, 35), source_ids=[src.source_id])
                if OBLIGATION_WORDS.search(sentence):
                    obligations.append(point)
                elif RISK_WORDS.search(sentence):
                    risks.append(point)
                elif ACTION_WORDS.search(sentence) and DATE_RE.search(sentence):
                    actions.append(point)
        return SectionNotes(
            section_summary=summary or "No text in this section.",
            key_points=key_points[:8],
            dates=dates[:10],
            action_items=actions[:8],
            obligations=obligations[:8],
            risks=risks[:8],
        )

    def _reduce(
        self, notes: Sequence[SectionNotes], sources: Sequence[SourcePassage]
    ) -> SummaryOutput:
        if not notes:
            notes = [self._section_notes(sources)]
        key_points = [p for n in notes for p in n.key_points]
        exec_summary = " ".join(f"{p.text} [{', '.join(p.source_ids)}]" for p in key_points[:3])
        return SummaryOutput(
            executive_summary=exec_summary or "No content available.",
            detailed_summary="\n\n".join(n.section_summary for n in notes),
            key_findings=key_points[:8],
            important_dates=[d for n in notes for d in n.dates][:12],
            action_items=[a for n in notes for a in n.action_items][:10],
            obligations=[o for n in notes for o in n.obligations][:10],
            risks_and_concerns=[r for n in notes for r in n.risks][:10],
            gaps_or_limitations=[
                "Offline extractive baseline: sentences are copied, not synthesized; no reasoning "
                "about importance, conflicts or implications was performed."
            ],
        )

    # ------------------------------------------------------------------ extraction
    def _extract(
        self, sources: Sequence[SourcePassage], categories: Sequence[str] | None
    ) -> ExtractionOutput:
        found: dict[str, list[ExtractedItem]] = {
            k: [] for k in ExtractionOutput.model_fields if k != "not_found"
        }
        seen: set[tuple[str, str]] = set()

        def add(
            category: str,
            value: str,
            src: SourcePassage,
            sentence: str,
            normalized: str | None = None,
            detail: str | None = None,
        ) -> None:
            key = (category, value.lower())
            if key in seen:
                return
            seen.add(key)
            found[category].append(
                ExtractedItem(
                    value=value,
                    normalized_value=normalized,
                    detail=detail,
                    source_id=src.source_id,
                    quote=_truncate_words(sentence, 30),
                )
            )

        for src in sources:
            for sentence in split_sentences(src.text):
                for m in DATE_RE.findall(sentence):
                    add("dates", m, src, sentence)
                for m in MONEY_RE.findall(sentence):
                    digits = re.sub(r"[^\d.]", "", m)
                    add(
                        "monetary_amounts",
                        m.strip(),
                        src,
                        sentence,
                        f"USD {digits}" if digits else None,
                    )
                for m in ORG_RE.findall(sentence):
                    add("organizations", m.strip(), src, sentence)
                for name, role in PERSON_ROLE_RE.findall(sentence):
                    add("people", name, src, sentence, detail=role.strip(" ,"))
                if OBLIGATION_WORDS.search(sentence):
                    add("obligations", _truncate_words(sentence, 30), src, sentence)
                if RESPONSIBILITY_WORDS.search(sentence):
                    add("responsibilities", _truncate_words(sentence, 30), src, sentence)
                if DECISION_WORDS.search(sentence):
                    add("decisions", _truncate_words(sentence, 30), src, sentence)
                if RISK_WORDS.search(sentence):
                    add("risks", _truncate_words(sentence, 30), src, sentence)
        wanted = set(categories) if categories else set(found)
        result = {k: (v[:15] if k in wanted else []) for k, v in found.items()}
        not_found = sorted(k for k in wanted if not result.get(k))
        return ExtractionOutput(**result, not_found=not_found)

    # ------------------------------------------------------------------ comparison
    def _compare(self, sources: Sequence[SourcePassage]) -> ComparisonOutput:
        by_doc: dict[str, list[tuple[str, SourcePassage]]] = {}
        for src in sources:
            for sentence in split_sentences(src.text):
                by_doc.setdefault(src.doc_id, []).append((sentence, src))
        doc_ids = list(by_doc)
        findings: list[ComparisonFinding] = []
        if len(doc_ids) >= 2:
            a_items, b_items = by_doc[doc_ids[0]], by_doc[doc_ids[1]]
            for sa, src_a in a_items:
                ta = set(tokenize(sa))
                nums_a = set(re.findall(r"\d[\d,.]*\d|\d", sa))
                best: tuple[float, str, SourcePassage] | None = None
                for sb, src_b in b_items:
                    tb = set(tokenize(sb))
                    if not ta or not tb:
                        continue
                    jac = len(ta & tb) / len(ta | tb)
                    if best is None or jac > best[0]:
                        best = (jac, sb, src_b)
                if best is None or best[0] < 0.35:
                    continue
                _, sb, src_b = best
                nums_b = set(re.findall(r"\d[\d,.]*\d|\d", sb))
                ids = [src_a.source_id, src_b.source_id]
                if nums_a and nums_b and nums_a != nums_b:
                    findings.append(
                        ComparisonFinding(
                            category="numerical_discrepancy",
                            topic=_truncate_words(sa, 8),
                            description=f'Different figures: "{_truncate_words(sa, 25)}" [{ids[0]}] vs '
                            f'"{_truncate_words(sb, 25)}" [{ids[1]}]',
                            nature="unclear",
                            source_ids=ids,
                        )
                    )
                elif sa.strip().lower() == sb.strip().lower() or best[0] >= 0.7:
                    findings.append(
                        ComparisonFinding(
                            category="similarity",
                            topic=_truncate_words(sa, 8),
                            description=f'Both documents state: "{_truncate_words(sa, 25)}" [{ids[0]}, {ids[1]}]',
                            nature="not_a_conflict",
                            source_ids=ids,
                        )
                    )
        return ComparisonOutput(
            overview="Offline extractive baseline: sentences from the two documents were aligned by word "
            "overlap; aligned sentences with different numbers are listed as discrepancies.",
            findings=findings[:20],
            limitations="No semantic understanding: cannot tell genuine contradictions from context "
            "differences, and misses differences expressed in different wording.",
        )


def offline_output_json(model: BaseModel) -> str:  # pragma: no cover - debugging helper
    return json.dumps(model.model_dump(), indent=2)
