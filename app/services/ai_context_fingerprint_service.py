from __future__ import annotations

import hashlib
import json
from typing import Any


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
                "lead_id": signal.lead_id,
                "public_signal_id": signal.public_signal_id,
                "evidence_ids": sorted(set(signal.evidence_ids)),
                "competitor_id": signal.competitor_id,
                "competitor": (signal.competitor or "").strip().lower(),
                "intent": signal.intent,
                "product_family": signal.product_family,
                "buyer_role": signal.buyer_role,
                "commercial_quality": signal.commercial_quality,
                "priority_score": signal.priority_score,
                "confidence": signal.confidence,
                "observed_at": signal.observed_at,
                "vertical": signal.vertical,
            }
            for signal in context.previous_signals
        ]
        commercial_signals.sort(
            key=lambda item: (
                item["observed_at"], item["competitor_id"], item["lead_id"]
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
            "parent_comment": (context.parent_comment or "").strip(),
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
