"""Config/health: which API keys are present, the thresholds in effect, and —
new — the editable credential catalogue behind ``/api/config/credentials``.

SOURCE_ACQUISITION.md §3 documents credentials that fail silently when missing.
The worst is ``UNPAYWALL_EMAIL``: without it the whole Unpaywall step is skipped
behind a ``logger.debug``, and the 31% acquisition rate that motivated this work
was measured on a machine whose ``.env`` held exactly one line. Making the
credentials editable from the UI is therefore an acquisition fix, not a
convenience.

Secrets are write-only over HTTP. A GET reports presence plus a last-four hint;
only non-secret fields (an email, a proxy hostname) round-trip their value.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from asv.core import credentials as creds

from apps.api.schemas import (
    ConfigStatus, CredentialField, CredentialsStatus, CredentialsUpdate,
)

logger = logging.getLogger(__name__)
from asv.sourcefinder.config import (
    CQ_ABSTRACT_MAX_CHARS,
    CQ_FULL_TEXT_MIN_CHARS,
    CQ_MIN_USABLE_CHARS,
    CQ_STRONG_IMRAD_SECTIONS,
    CQ_WEAK_IMRAD_SECTIONS,
    DATASET_REUSE_THRESHOLD,
    DOWNLOAD_TIMEOUT,
    ENABLE_REFERENCE_CHECK,
    MAX_CANDIDATES_PER_BATCH,
    MAX_FILE_SIZE_MB,
    REFCHECK_MIN_INDEXES_FOR_NOT_FOUND,
    REFCHECK_VERIFIED_TITLE_SIM,
)
from asv.validator.config import (
    DATASET_REUSE_CONFIDENCE,
    LLM_VERIFIER_CONFIDENCE_THRESHOLD,
    QUOTE_VERIFICATION_THRESHOLD,
    RAG_SIMILARITY_THRESHOLD,
    RAG_TOP_K,
    SCRIPT_TIMEOUT_SECONDS,
    SOURCE_VERIFICATION_PROMPT_VERSION,
)

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=ConfigStatus)
def get_config() -> ConfigStatus:
    # Driven off the same catalogue the config page edits, so a credential can
    # never be addable-but-unreported (or the reverse).
    file_values = creds.read_env_file()
    env_keys = {
        spec.name: bool(os.getenv(spec.name) or file_values.get(spec.name))
        for spec in creds.CREDENTIAL_SPECS
    }
    thresholds = {
        "LLM_VERIFIER_CONFIDENCE_THRESHOLD": LLM_VERIFIER_CONFIDENCE_THRESHOLD,
        # Tier 0.5
        "QUOTE_VERIFICATION_THRESHOLD": QUOTE_VERIFICATION_THRESHOLD,
        "SOURCE_VERIFICATION_PROMPT_VERSION": SOURCE_VERIFICATION_PROMPT_VERSION,
        # Tier 0.3
        "CQ_MIN_USABLE_CHARS": CQ_MIN_USABLE_CHARS,
        "CQ_FULL_TEXT_MIN_CHARS": CQ_FULL_TEXT_MIN_CHARS,
        "CQ_ABSTRACT_MAX_CHARS": CQ_ABSTRACT_MAX_CHARS,
        "CQ_STRONG_IMRAD_SECTIONS": CQ_STRONG_IMRAD_SECTIONS,
        "CQ_WEAK_IMRAD_SECTIONS": CQ_WEAK_IMRAD_SECTIONS,
        "MAX_CANDIDATES_PER_BATCH": MAX_CANDIDATES_PER_BATCH,
        # Tier 0.6
        "ENABLE_REFERENCE_CHECK": ENABLE_REFERENCE_CHECK,
        "REFCHECK_VERIFIED_TITLE_SIM": REFCHECK_VERIFIED_TITLE_SIM,
        "REFCHECK_MIN_INDEXES_FOR_NOT_FOUND": REFCHECK_MIN_INDEXES_FOR_NOT_FOUND,
        "DATASET_REUSE_CONFIDENCE": DATASET_REUSE_CONFIDENCE,
        "RAG_TOP_K": RAG_TOP_K,
        "RAG_SIMILARITY_THRESHOLD": RAG_SIMILARITY_THRESHOLD,
        "SCRIPT_TIMEOUT_SECONDS": SCRIPT_TIMEOUT_SECONDS,
        "DATASET_REUSE_THRESHOLD": DATASET_REUSE_THRESHOLD,
        "MAX_FILE_SIZE_MB": MAX_FILE_SIZE_MB,
        "DOWNLOAD_TIMEOUT": DOWNLOAD_TIMEOUT,
    }
    return ConfigStatus(env_keys=env_keys, thresholds=thresholds)


# ---------------------------------------------------------------------------
# Editable credentials
# ---------------------------------------------------------------------------

def _to_field(state: creds.CredentialState) -> CredentialField:
    spec = state.spec
    return CredentialField(
        name=spec.name,
        label=spec.label,
        group=spec.group,
        help=spec.help,
        impact=spec.impact,
        secret=spec.secret,
        required=spec.required,
        placeholder=spec.placeholder,
        signup_url=spec.signup_url,
        input_type=spec.input_type,
        present=state.present,
        value=state.display_value,
        from_shell=state.from_shell,
    )


def _status() -> CredentialsStatus:
    return CredentialsStatus(
        fields=[_to_field(s) for s in creds.current_state()],
        group_order=list(creds.GROUP_ORDER),
        group_blurb=dict(creds.GROUP_BLURB),
        env_path=str(creds.env_path()),
    )


@router.get("/config/credentials", response_model=CredentialsStatus)
def get_credentials() -> CredentialsStatus:
    """The credential catalogue plus what is currently set.

    Secret values are never returned — only presence and a last-four hint.
    """
    return _status()


@router.put("/config/credentials", response_model=CredentialsStatus)
def put_credentials(update: CredentialsUpdate) -> CredentialsStatus:
    """Write credentials to the repo-root ``.env``.

    Only names in the catalogue are accepted: this endpoint must not become a
    way to set arbitrary environment variables for a subprocess the API then
    launches.

    A field submitted unchanged arrives as its masked display value (the UI
    shows ``••••••ab12``), which is not a credential and must not be written
    over the real one. Those are dropped here rather than in the browser, since
    the browser is not where that invariant should live.
    """
    unknown = sorted(set(update.values) - set(creds.SPECS_BY_NAME))
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown credential name(s): {', '.join(unknown)}"
        )

    current = {s.spec.name: s for s in creds.current_state()}
    to_write: dict[str, str] = {}
    for name, value in update.values.items():
        value = (value or "").strip()
        state = current.get(name)
        if value and state is not None and state.spec.secret and value == state.display_value:
            continue  # unchanged masked placeholder echoed back
        to_write[name] = value

    if not to_write:
        return _status()

    changed = creds.write_env_values(to_write)
    creds.apply_to_process(to_write)
    # Log names only. The values are the whole point of not logging.
    logger.info("Credentials updated via config page: %s", ", ".join(sorted(changed)) or "(no change)")
    return _status()
