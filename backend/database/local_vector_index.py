"""Local stand-in for the Pinecone index used by ``database/vector_db.py``.

Self-hosted deployments (``selfhost/``) have no Pinecone account. Setting
``OMI_LOCAL_VECTOR_DB`` to a file path makes ``vector_db`` use this index
instead: vectors live in one SQLite file and queries are brute-force cosine
similarity. That is fast enough for a single account (tens of thousands of
vectors) and needs no extra service.

Only the subset of the Pinecone ``Index`` API that the backend calls is
implemented: ``upsert``, ``query``, ``update``, ``delete``, ``list``,
``fetch`` and ``describe_index_stats``. Results are plain dicts, which the
callers already read with ``[...]``/``.get``. Metadata filters follow the
Pinecone filter language: implicit equality, ``$eq``, ``$ne``, ``$in``,
``$nin``, ``$gt``, ``$gte``, ``$lt``, ``$lte``, ``$exists``, ``$and``, ``$or``.
For list-valued metadata, ``$eq``/``$in`` match when any element matches.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

import numpy as np

_DEFAULT_NAMESPACE = ""
_LIST_PAGE_SIZE = 100


def _as_record(vector: Any) -> tuple[str, List[float], Dict[str, Any]]:
    if isinstance(vector, Mapping):
        return str(vector["id"]), list(vector["values"]), dict(vector.get("metadata") or {})
    if isinstance(vector, (tuple, list)) and len(vector) in (2, 3):
        metadata = dict(vector[2]) if len(vector) == 3 and vector[2] else {}
        return str(vector[0]), list(vector[1]), metadata
    raise ValueError("vector must be a mapping with id/values/metadata or an (id, values[, metadata]) tuple")


def _values_match(stored: Any, wanted: Any) -> bool:
    if isinstance(stored, list):
        return wanted in stored
    return stored == wanted


def _compare(stored: Any, op: str, wanted: Any) -> bool:
    if isinstance(stored, bool) or not isinstance(stored, (int, float)):
        return False
    if isinstance(wanted, bool) or not isinstance(wanted, (int, float)):
        return False
    if op == "$gt":
        return stored > wanted
    if op == "$gte":
        return stored >= wanted
    if op == "$lt":
        return stored < wanted
    return stored <= wanted


def _field_matches(metadata: Mapping[str, Any], field: str, condition: Any) -> bool:
    present = field in metadata
    stored = metadata.get(field)
    if not isinstance(condition, Mapping):
        return present and _values_match(stored, condition)
    for op, wanted in condition.items():
        if op == "$eq":
            ok = present and _values_match(stored, wanted)
        elif op == "$ne":
            ok = not (present and _values_match(stored, wanted))
        elif op == "$in":
            options = list(wanted or [])
            if isinstance(stored, list):
                ok = present and any(item in options for item in stored)
            else:
                ok = present and stored in options
        elif op == "$nin":
            options = list(wanted or [])
            if isinstance(stored, list):
                ok = not (present and any(item in options for item in stored))
            else:
                ok = not (present and stored in options)
        elif op in ("$gt", "$gte", "$lt", "$lte"):
            ok = present and _compare(stored, op, wanted)
        elif op == "$exists":
            ok = present == bool(wanted)
        else:
            raise ValueError(f"unsupported filter operator {op!r}")
        if not ok:
            return False
    return True


def matches_filter(metadata: Mapping[str, Any], flt: Optional[Mapping[str, Any]]) -> bool:
    """Evaluate a Pinecone-style metadata filter against one record."""
    if not flt:
        return True
    for key, condition in flt.items():
        if key == "$and":
            if not all(matches_filter(metadata, part) for part in condition):
                return False
        elif key == "$or":
            if not any(matches_filter(metadata, part) for part in condition):
                return False
        elif key.startswith("$"):
            raise ValueError(f"unsupported filter operator {key!r}")
        elif not _field_matches(metadata, key, condition):
            return False
    return True


class LocalVectorIndex:
    """SQLite-backed index with the Pinecone ``Index`` methods the backend uses."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS vectors ("
            " namespace TEXT NOT NULL,"
            " id TEXT NOT NULL,"
            " dim INTEGER NOT NULL,"
            " vals BLOB NOT NULL,"
            " metadata TEXT NOT NULL,"
            " PRIMARY KEY (namespace, id))"
        )

    # -- writes ---------------------------------------------------------------

    def upsert(self, vectors: Iterable[Any], namespace: str = _DEFAULT_NAMESPACE, **_: Any) -> Dict[str, Any]:
        rows = []
        for vector in vectors:
            vector_id, values, metadata = _as_record(vector)
            array = np.asarray(values, dtype=np.float32)
            rows.append((namespace, vector_id, int(array.shape[0]), array.tobytes(), json.dumps(metadata)))
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.executemany(
                    "INSERT INTO vectors (namespace, id, dim, vals, metadata) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(namespace, id) DO UPDATE SET dim=excluded.dim, vals=excluded.vals, "
                    "metadata=excluded.metadata",
                    rows,
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return {"upserted_count": len(rows)}

    def update(
        self,
        id: str,
        values: Optional[Sequence[float]] = None,
        set_metadata: Optional[Mapping[str, Any]] = None,
        namespace: str = _DEFAULT_NAMESPACE,
        **_: Any,
    ) -> Dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT metadata FROM vectors WHERE namespace = ? AND id = ?", (namespace, id)
            ).fetchone()
            if row is None:
                return {}
            metadata = json.loads(row[0])
            metadata.update(dict(set_metadata or {}))
            if values is not None:
                array = np.asarray(values, dtype=np.float32)
                self._db.execute(
                    "UPDATE vectors SET metadata = ?, dim = ?, vals = ? WHERE namespace = ? AND id = ?",
                    (json.dumps(metadata), int(array.shape[0]), array.tobytes(), namespace, id),
                )
            else:
                self._db.execute(
                    "UPDATE vectors SET metadata = ? WHERE namespace = ? AND id = ?",
                    (json.dumps(metadata), namespace, id),
                )
        return {}

    def delete(
        self,
        ids: Optional[Sequence[str]] = None,
        delete_all: bool = False,
        namespace: str = _DEFAULT_NAMESPACE,
        filter: Optional[Mapping[str, Any]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        with self._lock:
            if delete_all:
                self._db.execute("DELETE FROM vectors WHERE namespace = ?", (namespace,))
            elif ids:
                self._db.executemany(
                    "DELETE FROM vectors WHERE namespace = ? AND id = ?", [(namespace, str(i)) for i in ids]
                )
            elif filter:
                doomed = [
                    vector_id
                    for vector_id, metadata in self._db.execute(
                        "SELECT id, metadata FROM vectors WHERE namespace = ?", (namespace,)
                    )
                    if matches_filter(json.loads(metadata), filter)
                ]
                self._db.executemany(
                    "DELETE FROM vectors WHERE namespace = ? AND id = ?", [(namespace, i) for i in doomed]
                )
        return {}

    # -- reads ----------------------------------------------------------------

    def query(
        self,
        vector: Optional[Sequence[float]] = None,
        top_k: int = 10,
        namespace: str = _DEFAULT_NAMESPACE,
        filter: Optional[Mapping[str, Any]] = None,
        include_values: bool = False,
        include_metadata: bool = False,
        id: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, dim, vals, metadata FROM vectors WHERE namespace = ?", (namespace,)
            ).fetchall()
            if vector is None and id is not None:
                found = self._db.execute(
                    "SELECT vals FROM vectors WHERE namespace = ? AND id = ?", (namespace, id)
                ).fetchone()
                vector = np.frombuffer(found[0], dtype=np.float32) if found else None
        if vector is None:
            return {"matches": [], "namespace": namespace}
        query = np.asarray(vector, dtype=np.float32)
        query_norm = float(np.linalg.norm(query)) or 1.0
        candidates = []
        for vector_id, dim, blob, raw_metadata in rows:
            if dim != query.shape[0]:
                continue  # vectors from a different embedding model never match
            metadata = json.loads(raw_metadata)
            if not matches_filter(metadata, filter):
                continue
            values = np.frombuffer(blob, dtype=np.float32)
            norm = float(np.linalg.norm(values)) or 1.0
            score = float(np.dot(values, query) / (norm * query_norm))
            candidates.append((score, vector_id, values, metadata))
        candidates.sort(key=lambda item: item[0], reverse=True)
        matches = []
        for score, vector_id, values, metadata in candidates[: max(0, int(top_k))]:
            match: Dict[str, Any] = {"id": vector_id, "score": score}
            if include_values:
                match["values"] = values.tolist()
            if include_metadata:
                match["metadata"] = metadata
            matches.append(match)
        return {"matches": matches, "namespace": namespace}

    def fetch(self, ids: Sequence[str], namespace: str = _DEFAULT_NAMESPACE, **_: Any) -> Dict[str, Any]:
        found: Dict[str, Any] = {}
        with self._lock:
            for vector_id in ids:
                row = self._db.execute(
                    "SELECT vals, metadata FROM vectors WHERE namespace = ? AND id = ?", (namespace, str(vector_id))
                ).fetchone()
                if row is not None:
                    found[str(vector_id)] = {
                        "id": str(vector_id),
                        "values": np.frombuffer(row[0], dtype=np.float32).tolist(),
                        "metadata": json.loads(row[1]),
                    }
        return {"vectors": found, "namespace": namespace}

    def list(
        self, prefix: Optional[str] = None, namespace: str = _DEFAULT_NAMESPACE, limit: int = _LIST_PAGE_SIZE, **_: Any
    ) -> Iterator[List[str]]:
        with self._lock:
            ids = [
                row[0]
                for row in self._db.execute(
                    "SELECT id FROM vectors WHERE namespace = ? ORDER BY id", (namespace,)
                ).fetchall()
            ]
        if prefix:
            ids = [vector_id for vector_id in ids if vector_id.startswith(prefix)]
        page = max(1, int(limit))
        for start in range(0, len(ids), page):
            yield ids[start : start + page]

    def describe_index_stats(self, **_: Any) -> Dict[str, Any]:
        with self._lock:
            counts = self._db.execute("SELECT namespace, COUNT(*) FROM vectors GROUP BY namespace").fetchall()
        namespaces = {name: {"vector_count": count} for name, count in counts}
        return {"namespaces": namespaces, "total_vector_count": sum(count for _, count in counts)}
