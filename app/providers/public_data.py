"""Public Instagram records, without retaining arbitrary provider payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.providers.base import ProviderPrivacyError


def ensure_public_source(payload: Any, *, check_owner: bool = True) -> None:
    """Reject explicitly restricted sources; a private author can still comment publicly."""
    if not isinstance(payload, dict):
        return
    for key in ("is_private", "private", "is_hidden", "hidden", "is_private_account"):
        value = payload.get(key)
        if value is not None and str(value).strip().lower() not in {"", "false", "0", "no"}:
            raise ProviderPrivacyError("Instagram source is private or hidden")
    if "is_public" in payload and str(payload["is_public"]).strip().lower() in {"false", "0", "no"}:
        raise ProviderPrivacyError("Instagram source is not public")
    if check_owner:
        for key in ("user", "owner", "data", "xdt_shortcode_media"):
            ensure_public_source(payload.get(key))


def public_record[T: BaseModel](record: T) -> T:
    """The normalized schema is the allowlist; never copy unknown/nested raw fields."""
    return record.model_copy(
        update={"raw_data": record.model_dump(mode="json", exclude={"raw_data"})}
    )
