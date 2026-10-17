#!/usr/bin/env python3
"""Classify corpus records for the public, rights-aware search release."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class RightsDecision:
    disposition: str
    rights_status: str
    rights_basis: str
    redistribution_scope: str
    review_note: str
    legal_xml: bool
    notice_match: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise ValueError(f"Unsupported rights policy schema: {policy.get('schema_version')}")
    if not isinstance(policy.get("sources"), dict):
        raise ValueError("Rights policy must contain a sources object")
    return policy


def path_extension(row: Mapping[str, Any]) -> str:
    original = str(row.get("original_path") or "")
    if original:
        return Path(original).suffix.lower()
    path = unquote(urlsplit(str(row.get("url") or "")).path)
    return Path(path).suffix.lower()


def media_type(row: Mapping[str, Any]) -> str:
    return str(row.get("content_type") or "").lower().split(";", 1)[0].strip()


def notice_match(body: str, policy: Mapping[str, Any]) -> str:
    limit = max(1000, int(policy.get("notice_scan_characters", 40000)))
    sample = body if len(body) <= limit else body[: limit // 2] + "\n" + body[-limit // 2 :]
    for item in policy.get("notice_patterns", []):
        if re.search(str(item["pattern"]), sample, flags=re.IGNORECASE):
            return str(item["label"])
    return ""


def _decision(settings: Mapping[str, Any], **changes: Any) -> RightsDecision:
    values = {
        "disposition": settings.get("disposition", "link_only"),
        "rights_status": settings.get("rights_status", "review_required"),
        "rights_basis": settings.get("rights_basis", "No rights basis recorded."),
        "redistribution_scope": settings.get(
            "redistribution_scope", "metadata_and_official_link_only"
        ),
        "review_note": settings.get("review_note", "Review before redistributing full text."),
        "legal_xml": bool(settings.get("legal_xml", False)),
        "notice_match": "",
    }
    values.update(changes)
    return RightsDecision(**values)


def classify_document(
    row: Mapping[str, Any], body: str, policy: Mapping[str, Any]
) -> RightsDecision:
    """Return the public-release disposition for a catalog record.

    The decision is intentionally conservative. It does not delete or alter the
    research corpus; it controls only what is copied into the public search pack.
    """
    source_settings = policy.get("sources", {}).get(
        str(row.get("source_id") or ""), policy.get("default", {})
    )
    extension = path_extension(row)
    ctype = media_type(row)
    url = str(row.get("url") or "")

    if url.startswith("archive://"):
        archive_policy = policy.get("archive_members", {})
        approved = archive_policy.get("approved", {}).get(str(row.get("source_id") or ""))
        if not approved or extension not in set(approved.get("extensions", [])):
            return _decision(
                source_settings,
                disposition=str(archive_policy.get("default_disposition", "omit")),
                rights_status="not_redistributed",
                redistribution_scope="omitted_from_public_release",
                review_note=str(archive_policy.get("default_note", "Archive member omitted.")),
                legal_xml=False,
            )
        merged = dict(source_settings)
        merged.update(approved)
        source_settings = merged

    if any(ctype.startswith(prefix) for prefix in policy.get("omit_media_prefixes", [])):
        return _decision(
            source_settings,
            disposition="omit",
            rights_status="not_redistributed",
            redistribution_scope="omitted_from_public_release",
            review_note=f"Non-text media type {ctype or 'unknown'} is not part of the public release.",
            legal_xml=False,
        )
    if extension in set(policy.get("omit_extensions", [])):
        return _decision(
            source_settings,
            disposition="omit",
            rights_status="not_redistributed",
            redistribution_scope="omitted_from_public_release",
            review_note=f"Non-document asset {extension} is not part of the public release.",
            legal_xml=False,
        )

    decision = _decision(source_settings)
    if decision.disposition == "full_text" and source_settings.get("scan_notices", True) and body:
        matched = notice_match(body, policy)
        if matched:
            return _decision(
                source_settings,
                disposition="link_only",
                rights_status="review_required",
                redistribution_scope="metadata_and_official_link_only",
                review_note=(
                    f"Full text withheld automatically after detecting {matched}; "
                    "review the original document and its credits."
                ),
                legal_xml=False,
                notice_match=matched,
            )
    return decision
