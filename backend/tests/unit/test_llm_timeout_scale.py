"""OMI_LLM_TIMEOUT_SCALE stretches LLM deadlines for slow self-hosted models and is a no-op by default."""

import pytest

from llm_gateway.gateway.config_loader import load_gateway_config
from utils.llm.timeout_scale import TIMEOUT_SCALE_ENV, llm_timeout_scale, scaled_seconds


@pytest.mark.parametrize(
    'raw, expected', [(None, 1.0), ('', 1.0), ('abc', 1.0), ('0.5', 1.0), ('1', 1.0), ('12.5', 12.5)]
)
def test_scale_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(TIMEOUT_SCALE_ENV, raising=False)
    else:
        monkeypatch.setenv(TIMEOUT_SCALE_ENV, raw)
    assert llm_timeout_scale() == expected
    assert scaled_seconds(10.0) == 10.0 * expected


def test_gateway_route_timeouts_scale_after_digest_check(monkeypatch):
    monkeypatch.delenv(TIMEOUT_SCALE_ENV, raising=False)
    base = {
        route_id: a.timeouts.request_ms for route_id, a in load_gateway_config(prod_mode=True).route_artifacts.items()
    }

    monkeypatch.setenv(TIMEOUT_SCALE_ENV, '4')
    scaled = load_gateway_config(prod_mode=True).route_artifacts

    assert scaled.keys() == base.keys()
    assert all(scaled[route_id].timeouts.request_ms == base[route_id] * 4 for route_id in base)
