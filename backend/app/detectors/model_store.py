"""Optional load of the pretrained OmniAnomaly checkpoint for the serving path.

Graceful by design: if the URI is unset, torch is missing, or the GCS download
fails, ``load_omni`` returns ``None`` and the agent serves the MAD/EVT baseline only
— serving never breaks because of the deep-learning arm. The heavy imports
(``torch`` via the detector, ``google.cloud.storage``) happen lazily in here, so a
torch-less environment (tests, the lean dev install) never pays for them.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def load_omni(uri: str, device: str = "cpu"):
    """Load the checkpoint at ``uri`` into a ready-to-score detector, or ``None``.

    Never raises: any failure (no URI, torch missing, GCS/download error, bad
    checkpoint) is logged and degrades to ``None`` so the baseline still serves.
    """
    if not uri:
        return None
    try:
        from app.detectors.omnianomaly import OmniAnomalyDetector

        local = _ensure_local(uri)
        det = OmniAnomalyDetector.load(local, device=device)
        log.info("OmniAnomaly checkpoint loaded from %s (window=%d)", uri, det.window)
        return det
    except Exception as exc:  # noqa: BLE001 — degrade to baseline, never crash serving
        log.warning("OmniAnomaly checkpoint not loaded (%s); serving baseline only", exc)
        return None


def _ensure_local(uri: str) -> str:
    """Return a local path for ``uri`` — downloading from GCS to a temp file if needed."""
    if not uri.startswith("gs://"):
        return uri
    from google.cloud import storage

    bucket, _, blob = uri.removeprefix("gs://").partition("/")
    dest = str(Path(tempfile.gettempdir()) / Path(blob).name)
    storage.Client().bucket(bucket).blob(blob).download_to_filename(dest)
    return dest
