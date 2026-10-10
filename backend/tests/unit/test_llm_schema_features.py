"""OMI_LLM_SCHEMA_FEATURES (selfhost/) holds small local models to a feature's JSON schema; unset it changes nothing."""

import os

os.environ.setdefault("ENCRYPTION_SECRET", "omi_ZwB2ZNqB2HHpMK6wStk7sTpavJiPTFg7gXUHnc4tFABPU6pZ2c2DKgehtfgi4RZw")
os.environ.setdefault("OPENAI_API_KEY", "***")
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8787")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test")

import pytest  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

import utils.llm.model_config as model_config  # noqa: E402
import utils.llm.working_observations as working_observations  # noqa: E402
from llm_gateway.gateway.config_loader import feature_lane_id, load_gateway_config  # noqa: E402

_L1_BATCH_JSON = (
    '{"items": [{"text": "Tobi baut einen Recorder.", "evidence_quotes": ["Ich baue einen Recorder."], '
    '"speaker_label": "SPEAKER_00", "about": "the user", "confidence": "high"}]}'
)
_TEXT = "SPEAKER_00 (Tobi): Ich baue einen Recorder, der den ganzen Tag aufnimmt."


@pytest.mark.parametrize(
    'raw, expected',
    [(None, set()), ('', set()), (' , ', set()), ('memory_l1', {'memory_l1'}), ('memory_l1, x ,', {'memory_l1', 'x'})],
)
def test_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(model_config.SCHEMA_FEATURES_ENV, raising=False)
    else:
        monkeypatch.setenv(model_config.SCHEMA_FEATURES_ENV, raw)
    assert model_config.schema_forced_features() == expected


def _lane(feature: str):
    return load_gateway_config(prod_mode=True).lanes[feature_lane_id(feature)]


def test_gateway_lane_follows_the_feature_list(monkeypatch):
    assert _lane('memory_l1').capabilities.structured_output == 'none'
    monkeypatch.setattr(
        model_config, '_STRUCTURED_OUTPUT_FEATURES', model_config._STRUCTURED_OUTPUT_FEATURES | {'memory_l1'}
    )
    assert _lane('memory_l1').capabilities.structured_output == 'json_schema'


class _Model:
    def __init__(self):
        self.bound: dict = {}

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def invoke(self, messages):
        return AIMessage(content=_L1_BATCH_JSON)


@pytest.mark.parametrize('forced', [False, True])
def test_memory_l1_asks_for_the_schema_only_when_forced(monkeypatch, forced):
    model = _Model()
    monkeypatch.setattr(working_observations, 'get_llm', lambda *args, **kwargs: model)
    monkeypatch.setattr(working_observations, 'is_structured_output_feature', lambda feature: forced)

    items = working_observations.extract_l1_memory_archive_items_from_text(
        uid='tobi', source_id='c1', source_type='omi', text=_TEXT, user_name='Tobi', persist_route_outcomes=False
    )

    assert [item.text for item in items] == ['Tobi baut einen Recorder.']
    if not forced:
        assert model.bound == {}
        return
    response_format = model.bound['response_format']
    assert response_format['type'] == 'json_schema'
    assert response_format['json_schema']['name'] in {'WorkingObservationBatch', 'BeliefWorkingObservationBatch'}
    assert 'items' in response_format['json_schema']['schema']['properties']


@pytest.mark.parametrize(
    'batch', [working_observations.WorkingObservationBatch, working_observations.BeliefWorkingObservationBatch]
)
def test_forced_schema_only_asks_for_what_the_model_writes(batch):
    schema = working_observations.forced_response_format(batch)['json_schema']['schema']
    item = next(d for d in schema['$defs'].values() if 'confidence' in d.get('properties', {}))
    assert {'archive_id', 'user_id', 'schema_version', 'search_result_label'}.isdisjoint(item['properties'])
    assert item['additionalProperties'] is False
    assert item['properties']['confidence']['enum'] == ['high', 'medium', 'low']
    assert item['properties']['evidence_quotes']['maxItems'] == 5
    assert schema['properties']['items']['maxItems'] == working_observations.MAX_WORKING_OBSERVATION_ITEMS
    # what the schema allows still parses into an archive item
    reply = '{"items": [{"text": "Tobi baut einen Recorder.", "evidence_quotes": ["Ich baue einen Recorder."], "about": "the user", "confidence": "low", "archive_class": "general"}]}'
    assert batch.model_validate_json(reply).items[0].confidence == 'low'
