from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.lead_scoring_v3 import infer_historical_intent


class AIContextFingerprintService:
    """Build a stable semantic key for one versioned AI analysis contract."""

    def __init__(
        self,
        *,
        analysis_version: str,
        model: str,
        prompt_version: str,
        schema_version: str,
    ) -> None:
        self.analysis_version = analysis_version
        self.model = model
        self.prompt_version = prompt_version
        self.schema_version = schema_version

    def fingerprint(self, context: Any) -> str:
        commercial_signals = [
            {
                "competitor": (signal.competitor or "").strip().lower(),
                "comment": (signal.comment or "").strip(),
                "discovered_at": signal.discovered_at,
            }
            for signal in context.previous_signals
            if infer_historical_intent(signal.comment) is not None
        ]
        commercial_signals.sort(
            key=lambda item: (
                item["discovered_at"], item["competitor"], item["comment"]
            )
        )
        canonical = {
            "analysis_contract_version": self.analysis_version,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "model": self.model,
            "competitor": (context.competitor or "").strip().lower(),
            "post_caption": (context.post_caption or "").strip(),
            "comment": (context.comment or "").strip(),
            "username": (context.username or "").strip().lower(),
            "stable_contact_id": context.stable_contact_id,
            "vertical": context.vertical,
            "catalog_context_version": context.catalog_context_version,
            "previous_signals": commercial_signals,
            "previous_interests": sorted(set(context.previous_interests)),
            "known_customer_context": dict(sorted(context.known_customer_context.items())),
            "evidence_ids": sorted(set(context.evidence_ids)),
        }
        payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
