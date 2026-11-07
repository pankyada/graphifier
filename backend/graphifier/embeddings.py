"""Optional snapshot-scoped embeddings with portable SQLite vector storage."""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import ssl
import time
import urllib.error
import urllib.request
from itertools import islice

import certifi

from .db import connect, json_data


def configuration():
    model = os.environ.get("GRAPHIFIER_EMBEDDING_MODEL", "").strip()
    base = os.environ.get("GRAPHIFIER_EMBEDDING_BASE_URL", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
    key = os.environ.get("GRAPHIFIER_EMBEDDING_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    return model, base, key


def chunks(content, max_chars=4000, max_lines=80):
    """Preserve exact line evidence, including oversized individual lines."""
    lines = content.splitlines(keepends=True)
    start, parts, size = 1, [], 0
    for line_number, line in enumerate(lines, 1):
        if parts and (size + len(line) > max_chars or len(parts) >= max_lines):
            yield {"start_line": start, "end_line": line_number - 1, "content": "".join(parts)}
            parts, size = [], 0
        if not parts:
            start = line_number
        if len(line) > max_chars:
            for offset in range(0, len(line), max_chars):
                yield {"start_line": line_number, "end_line": line_number, "content": line[offset:offset + max_chars]}
        else:
            parts.append(line)
            size += len(line)
    if parts:
        yield {"start_line": start, "end_line": len(lines), "content": "".join(parts)}


def _embed(texts):
    model, base, key = configuration()
    if not model:
        raise ValueError("Configure GRAPHIFIER_EMBEDDING_MODEL to enable embeddings")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(f"{base}/embeddings", data=json.dumps({"model": model, "input": texts, "encoding_format": "float"}).encode(), headers=headers, method="POST")
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or certifi.where())
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as response:
                data = json.load(response).get("data", [])
            break
        except urllib.error.HTTPError as exc:
            if attempt == 2 or exc.code not in {408, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"Embedding endpoint returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError("Embedding endpoint unavailable or timed out") from exc
        time.sleep(2 ** attempt)
    if len(data) != len(texts) or {item.get("index") for item in data} != set(range(len(texts))):
        raise RuntimeError("Embedding endpoint returned missing or duplicate vectors")
    vectors = [item.get("embedding") for item in sorted(data, key=lambda item: item["index"])]
    dimension = len(vectors[0]) if vectors and isinstance(vectors[0], list) else 0
    for vector in vectors:
        if not isinstance(vector, list) or not dimension or len(vector) != dimension or any(not isinstance(x, (float, int)) or isinstance(x, bool) or not math.isfinite(x) for x in vector):
            raise RuntimeError("Embedding endpoint returned invalid vectors")
        if not any(vector):
            raise RuntimeError("Embedding endpoint returned a zero vector")
    return vectors


def index_snapshot(repo_id, snapshot_id, cancelled=None, progress=None):
    model, base, _ = configuration()
    if not model:
        raise ValueError("Configure GRAPHIFIER_EMBEDDING_MODEL to enable embeddings")
    provider = hashlib.sha256(base.encode()).hexdigest()
    batch_size = max(1, min(128, int(os.environ.get("GRAPHIFIER_EMBEDDING_BATCH_SIZE", "16"))))
    with connect() as c:
        exists = c.execute("SELECT 1 FROM snapshots WHERE id=? AND repo_id=?", (snapshot_id, repo_id)).fetchone()
        if not exists:
            raise ValueError("Snapshot does not belong to repository")
        c.execute("INSERT OR REPLACE INTO embedding_indexes(snapshot_id,repo_id,model,provider,status,chunk_count) VALUES(?,?,?,?, 'building',0)", (snapshot_id, repo_id, model, provider))
        c.execute("DELETE FROM code_chunks WHERE snapshot_id=?", (snapshot_id,))
    count, dimension = 0, None
    try:
        with connect() as reader:
            sources = reader.execute("SELECT file,content,sha256 FROM source_files WHERE repo_id=? AND snapshot_id=? ORDER BY file", (repo_id, snapshot_id))
            for source in sources:
                iterator = iter(chunks(source["content"]))
                while batch := list(islice(iterator, batch_size)):
                    if cancelled and cancelled():
                        raise RuntimeError("Embedding indexing cancelled")
                    vectors = _embed([item["content"] for item in batch])
                    if dimension is not None and dimension != len(vectors[0]):
                        raise RuntimeError("Embedding dimensions changed during indexing")
                    dimension = len(vectors[0])
                    with connect() as writer:
                        for item, vector in zip(batch, vectors):
                            writer.execute("INSERT INTO code_chunks(snapshot_id,repo_id,file,start_line,end_line,content,source_sha256,vector,norm) VALUES(?,?,?,?,?,?,?,?,?)", (snapshot_id, repo_id, source["file"], item["start_line"], item["end_line"], item["content"], source["sha256"], json_data(vector), math.sqrt(sum(x*x for x in vector))))
                    count += len(batch)
                    if progress:
                        progress(count)
        if cancelled and cancelled():
            raise RuntimeError("Embedding indexing cancelled")
        with connect() as c:
            c.execute("UPDATE embedding_indexes SET status='completed',chunk_count=?,dimensions=? WHERE snapshot_id=?", (count, dimension or 0, snapshot_id))
        return {"chunks": count, "model": model}
    except Exception:
        with connect() as c:
            c.execute("UPDATE embedding_indexes SET status='failed' WHERE snapshot_id=?", (snapshot_id,))
            c.execute("DELETE FROM code_chunks WHERE snapshot_id=?", (snapshot_id,))
        raise


def _scope(repo_id, environment):
    # Latest completed analysis per repository/environment only. Older vectors
    # never silently substitute for a newly indexed snapshot lacking embeddings.
    clauses, params = ["j.status='completed'"], []
    if repo_id:
        clauses.append("s.repo_id=?")
        params.append(repo_id)
    if environment:
        clauses.append("j.environment=?")
        params.append(environment)
    return "WITH ranked AS (SELECT s.id,s.repo_id,ROW_NUMBER() OVER (PARTITION BY s.repo_id,j.environment ORDER BY s.created_at DESC,s.rowid DESC) AS rank FROM snapshots s JOIN jobs j ON j.id=s.job_id WHERE " + " AND ".join(clauses) + ") ", params


def status(repo_id=None, environment=None):
    model, base, _ = configuration()
    prefix, params = _scope(repo_id, environment)
    with connect() as c:
        row = c.execute(prefix + "SELECT COUNT(*) AS snapshots,COALESCE(SUM(i.chunk_count),0) AS chunks FROM embedding_indexes i JOIN ranked r ON r.id=i.snapshot_id WHERE r.rank=1 AND i.status='completed' AND i.model=? AND i.provider=?", (*params, model, hashlib.sha256(base.encode()).hexdigest())).fetchone()
    return {"enabled": bool(model), "model": model, "indexed_chunks": row["chunks"], "indexed_snapshots": row["snapshots"]}


def search(query, repo_id=None, environment=None, limit=10):
    if not isinstance(query, str) or not query.strip() or len(query) > 8000:
        raise ValueError("Query must contain 1 to 8000 characters")
    limit = max(1, min(100, int(limit)))
    model, base, _ = configuration()
    prefix, params = _scope(repo_id, environment)
    if not status(repo_id, environment)["indexed_chunks"]:
        return {"matches": [], "model": model}
    vector = _embed([query])[0]
    norm = math.sqrt(sum(x*x for x in vector))
    best = []
    with connect() as c:
        rows = c.execute(prefix + "SELECT ch.* FROM code_chunks ch JOIN ranked r ON r.id=ch.snapshot_id JOIN embedding_indexes i ON i.snapshot_id=ch.snapshot_id WHERE r.rank=1 AND i.status='completed' AND i.model=? AND i.provider=? AND i.dimensions=?", (*params, model, hashlib.sha256(base.encode()).hexdigest(), len(vector)))
        for row in rows:
            stored = json.loads(row["vector"])
            score = sum(a*b for a,b in zip(vector, stored)) / (norm * row["norm"])
            item = {key: row[key] for key in ("repo_id", "snapshot_id", "file", "start_line", "end_line", "content", "source_sha256")}
            item["score"] = score
            entry = (score, row["id"], item)
            if len(best) < limit:
                heapq.heappush(best, entry)
            elif entry[:2] > best[0][:2]:
                heapq.heapreplace(best, entry)
    return {"matches": [entry[2] for entry in sorted(best, reverse=True)], "model": model}
