"""Bounded, provenance-checked evidence enrichment, independent of /chat."""
from dataclasses import dataclass, field
from typing import Optional, Sequence

from core.evidence import EvidenceBundle, LogAttributes, within_window


@dataclass(frozen=True)
class EvidenceTerm:
    text: str
    evidence_id: str


@dataclass(frozen=True)
class RetrievalQuery:
    original_message: str
    query: str
    evidence_ids: list[str] = field(default_factory=list)


def build_retrieval_query(message: str, *, evidence: Optional[EvidenceBundle] = None,
                          service_name: Optional[str] = None,
                          terms: Optional[Sequence[EvidenceTerm]] = None) -> RetrievalQuery:
    if evidence is None:
        return RetrievalQuery(message, message)
    service = evidence.query_context.service_name
    if service_name is not None and service_name != service:
        return RetrievalQuery(message, message)
    valid = {}
    state = evidence.tool_status.get("query_logs")
    if state is None or state.status != "ok":
        return RetrievalQuery(message, message)
    for item in evidence.evidence:
        if (item.service_name == service and item.environment == evidence.query_context.environment
                and item.dataset_id == evidence.query_context.dataset_id
                and item.dataset_version == evidence.query_context.dataset_version
                and within_window(item, evidence.query_context.logs_window)
                and isinstance(item.attributes, LogAttributes)):
            valid[item.evidence_id] = item
    if terms is None:
        terms = [EvidenceTerm(text, item.evidence_id) for item in valid.values()
                 for text in (item.attributes.error_code, item.attributes.message[:64]) if text]
    parts, ids, seen = [], [], set()
    for term in terms:
        item = valid.get(term.evidence_id)
        text = term.text.strip()
        if item is None or not text or len(text) > 64 or any(ord(c) < 32 for c in text):
            continue
        source = f"{item.attributes.error_code or ''}\n{item.attributes.message}".casefold()
        if text.casefold() not in source or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        parts.append(text)
        if term.evidence_id not in ids:
            ids.append(term.evidence_id)
        if len(parts) == 6:
            break
    if not parts:
        return RetrievalQuery(message, message)
    suffix = " ".join([service[:64]] + parts)[:512]
    return RetrievalQuery(message, f"{message}\n{suffix}", ids)
