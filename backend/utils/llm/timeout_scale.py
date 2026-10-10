"""One knob to stretch LLM deadlines for slow self-hosted models.

Omi's deadlines are sized for hosted models. A local model on a home PC
(selfhost/) can need many times longer for the same prompt, and every
deadline that fires turns into a failed conversation. ``OMI_LLM_TIMEOUT_SCALE``
multiplies the backend's LLM request deadlines and the gateway route timeouts.
Unset, invalid or below 1 means 1: hosted deployments are unchanged.
"""

from __future__ import annotations

import os

TIMEOUT_SCALE_ENV = 'OMI_LLM_TIMEOUT_SCALE'


def llm_timeout_scale() -> float:
    raw = os.getenv(TIMEOUT_SCALE_ENV, '').strip()
    if not raw:
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return value if value > 1.0 else 1.0


def scaled_seconds(seconds: float) -> float:
    return seconds * llm_timeout_scale()
