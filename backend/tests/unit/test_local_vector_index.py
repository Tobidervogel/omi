"""LocalVectorIndex: the SQLite stand-in for Pinecone used by selfhost/."""

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / 'database' / 'local_vector_index.py'
_spec = importlib.util.spec_from_file_location('local_vector_index_under_test', _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
local_vector_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_vector_index)

LocalVectorIndex = local_vector_index.LocalVectorIndex
matches_filter = local_vector_index.matches_filter


@pytest.fixture
def index(tmp_path):
    return LocalVectorIndex(tmp_path / 'vectors.sqlite3')


def test_query_ranks_by_cosine_and_respects_namespace(index):
    index.upsert(
        vectors=[
            {'id': 'a', 'values': [1.0, 0.0], 'metadata': {'uid': 'u1'}},
            {'id': 'b', 'values': [0.6, 0.8], 'metadata': {'uid': 'u1'}},
            {'id': 'c', 'values': [0.0, 1.0], 'metadata': {'uid': 'u1'}},
        ],
        namespace='ns1',
    )
    index.upsert(vectors=[('x', [1.0, 0.0], {'uid': 'u1'})], namespace='ns2')

    result = index.query(vector=[1.0, 0.1], top_k=2, namespace='ns1', include_metadata=True)

    assert [m['id'] for m in result['matches']] == ['a', 'b']
    assert result['matches'][0]['score'] == pytest.approx(0.995, abs=1e-3)
    assert result['matches'][0]['metadata'] == {'uid': 'u1'}
    assert 'values' not in result['matches'][0]


def test_query_skips_vectors_of_other_dimension(index):
    index.upsert(vectors=[{'id': 'old', 'values': [1.0, 0.0, 0.0], 'metadata': {}}], namespace='ns1')
    index.upsert(vectors=[{'id': 'new', 'values': [1.0, 0.0], 'metadata': {}}], namespace='ns1')

    assert [m['id'] for m in index.query(vector=[1.0, 0.0], top_k=5, namespace='ns1')['matches']] == ['new']


def test_upsert_replaces_and_update_merges_metadata(index):
    index.upsert(vectors=[{'id': 'a', 'values': [1.0, 0.0], 'metadata': {'uid': 'u1', 'k': 1}}], namespace='ns1')
    index.upsert(vectors=[{'id': 'a', 'values': [0.0, 1.0], 'metadata': {'uid': 'u1', 'k': 2}}], namespace='ns1')
    index.update('a', set_metadata={'extra': True}, namespace='ns1')

    fetched = index.fetch(ids=['a', 'missing'], namespace='ns1')['vectors']
    assert list(fetched) == ['a']
    assert fetched['a']['values'] == [0.0, 1.0]
    assert fetched['a']['metadata'] == {'uid': 'u1', 'k': 2, 'extra': True}


def test_delete_by_ids_filter_and_all(index):
    index.upsert(
        vectors=[{'id': f'u1-{n}', 'values': [1.0, float(n)], 'metadata': {'uid': 'u1', 'n': n}} for n in range(5)],
        namespace='ns1',
    )
    index.delete(ids=['u1-0'], namespace='ns1')
    index.delete(filter={'n': {'$gte': 3}}, namespace='ns1')
    remaining = [vector_id for page in index.list(namespace='ns1') for vector_id in page]
    assert remaining == ['u1-1', 'u1-2']

    index.delete(delete_all=True, namespace='ns1')
    assert list(index.list(namespace='ns1')) == []


def test_list_pages_with_prefix(index):
    index.upsert(
        vectors=[{'id': f'uid-conv-{n:03d}', 'values': [1.0], 'metadata': {}} for n in range(250)]
        + [{'id': 'other-1', 'values': [1.0], 'metadata': {}}],
        namespace='ns_tchunks',
    )

    pages = list(index.list(prefix='uid-conv-', namespace='ns_tchunks'))

    assert [len(page) for page in pages] == [100, 100, 50]
    assert pages[0][0] == 'uid-conv-000'


def test_data_survives_reopen(tmp_path):
    path = tmp_path / 'v.sqlite3'
    LocalVectorIndex(path).upsert(vectors=[{'id': 'a', 'values': [1.0, 0.0], 'metadata': {'uid': 'u'}}], namespace='n')

    reopened = LocalVectorIndex(path)

    assert reopened.query(vector=[1.0, 0.0], top_k=1, namespace='n')['matches'][0]['id'] == 'a'
    assert reopened.describe_index_stats()['total_vector_count'] == 1


@pytest.mark.parametrize(
    'flt, expected',
    [
        ({'uid': 'u1'}, True),
        ({'uid': {'$eq': 'u2'}}, False),
        ({'uid': {'$ne': 'u2'}}, True),
        ({'topics': {'$in': ['sport', 'auto']}}, True),
        ({'topics': {'$in': ['kochen']}}, False),
        ({'topics': {'$nin': ['kochen']}}, True),
        ({'topics': 'auto'}, True),
        ({'created_at': {'$gte': 100, '$lte': 200}}, True),
        ({'created_at': {'$gt': 150}}, False),
        ({'missing': {'$exists': False}}, True),
        ({'uid': {'$exists': True}}, True),
        ({'$and': [{'uid': {'$eq': 'u1'}}, {'flag': {'$eq': False}}]}, True),
        ({'$and': [{'uid': {'$eq': 'u1'}}, {'flag': {'$eq': True}}]}, False),
        ({'$or': [{'uid': {'$eq': 'u9'}}, {'topics': {'$in': ['sport']}}]}, True),
        ({'$or': [{'uid': {'$eq': 'u9'}}, {'topics': {'$in': ['x']}}]}, False),
        ({'layer': {'$in': ['short_term', 'long_term']}}, True),
    ],
)
def test_filter_language(flt, expected):
    metadata = {
        'uid': 'u1',
        'topics': ['auto', 'sport'],
        'created_at': 150,
        'flag': False,
        'layer': 'long_term',
    }
    assert matches_filter(metadata, flt) is expected


def test_numeric_comparison_ignores_booleans_and_missing():
    assert matches_filter({'n': True}, {'n': {'$gte': 0}}) is False
    assert matches_filter({}, {'n': {'$lte': 10}}) is False


def test_unknown_operator_is_rejected():
    with pytest.raises(ValueError):
        matches_filter({'a': 1}, {'a': {'$regex': '.*'}})
