"""Explicit RootLens defaults, separate from backwards-compatible component defaults."""
import os

ROOTLENS_COLLECTION = "rootlens_runbooks_v1"


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
