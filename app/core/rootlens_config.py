"""Explicit RootLens defaults, separate from backwards-compatible component defaults."""
import os
from typing import Mapping

ROOTLENS_COLLECTION = "rootlens_runbooks_v1"
ROOTLENS_ENTITY_FIELDS = (
    "date", "service_name", "start_time", "version", "status_code", "error_code",
)
LEGACY_ENTITY_FIELDS = ("order_id", "product", "amount")


def project_rootlens_entities(entities: Mapping[str, list[str]]) -> dict[str, list[str]]:
    """Expose only meaningful incident fields to RootLens; legacy extraction stays intact."""
    legacy_values = {
        value.strip().casefold()
        for field in LEGACY_ENTITY_FIELDS
        for value in entities.get(field, []) or []
        if isinstance(value, str) and value.strip()
    }
    projected = {}
    for field in ROOTLENS_ENTITY_FIELDS:
        values = entities.get(field)
        if not isinstance(values, (list, tuple)):
            continue
        meaningful = [value.strip() for value in values
                      if isinstance(value, str) and value.strip()
                      and value.strip().casefold() not in legacy_values]
        if meaningful:
            projected[field] = meaningful
    return projected


def memory_options():
    options = {}
    for env, parameter in (("ROOTLENS_USER_PROFILE_ENABLED", "enable_user_profile"),
                           ("ROOTLENS_EPISODIC_RECALL_ENABLED", "enable_episodic_recall")):
        value = os.getenv(env, "false").strip().lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError(f"{env} must be true/false or 1/0")
        options[parameter] = value in {"true", "1"}
    return options


def knowledge_collection():
    name = os.getenv("ROOTLENS_KNOWLEDGE_COLLECTION", ROOTLENS_COLLECTION).strip()
    if not name.startswith("rootlens_"):
        raise ValueError("RootLens requires a separate rootlens_ knowledge collection")
    return name
