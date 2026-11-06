# -*- coding: utf-8 -*-
"""繁星知识库 P0：Markdown 切块 + bge-small + FAISS + SQLite。

只做文本知识；不索引图片/视频/模型/密钥。索引目录结构：
  sources.json      源白名单（顶层 sources = legacy；collections = 分层源）
  chunks.sqlite     chunk 元数据 + 向量 BLOB + 文件哈希（legacy 根索引）
  vectors.faiss     IndexIDMap2(IndexFlatIP)
  index_meta.json   模型/切块器/计数
  collections/<core|project|archive|skills|memory>/
                   每个 collection 独立 SQLite/FAISS/meta/audit
"""
import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Dict, Iterable, List, Optional

DEFAULT_INDEX_DIR = r"E:/繁星/60_知识库"
DEFAULT_MODEL = r"E:/Models/Embedding/bge-small-zh-v1.5"
DEFAULT_RERANK_MODEL = r"E:/Models/Reranker/bge-reranker-v2-m3"
CHUNK_VERSION = "kb-p0-1"
MAX_FILE_BYTES = 2_000_000
MIN_CHUNK_CHARS = 4
SKIP_DIRS = {
    ".git", ".svn", "__pycache__", "node_modules", ".cache", ".venv", "venv",
    "_frames", "frames", "images", "videos", "outputs", "assets", "图片",
    "_待归类_20260928", "_统一备份",
}
DEFAULT_INCLUDE = [".md", ".txt"]

_MODEL = None
_MODEL_PATH = None
_RERANKER = None
_RERANKER_PATH = None
_JIEBA = None
RRF_K = 60
FTS_VERSION = "fts-jieba-1"
COLLECTIONS = ("core", "project", "archive", "skills", "memory")
NEAR_DUP_SHINGLE = 5
NEAR_DUP_THRESHOLD = 0.90
NEAR_DUP_MAX_DF = 400


def collection_dir(index_dir: str, collection: str) -> str:
    """每个 collection 一个独立 SQLite/FAISS 目录，避免记忆/技能混进 knowledge。"""
    if collection not in COLLECTIONS:
        raise ValueError("collection 只能是 %s" % "/".join(COLLECTIONS))
    return os.path.join(os.path.abspath(index_dir), "collections", collection)


def list_collections(index_dir: str) -> List[str]:
    root = os.path.join(os.path.abspath(index_dir), "collections")
    return [c for c in COLLECTIONS
            if os.path.isfile(os.path.join(root, c, "chunks.sqlite"))]


def collection_sources(cfg: Dict, collection: Optional[str]) -> List[Dict]:
    if collection is None:
        return cfg.get("sources") or []
    srcs = (cfg.get("collections") or {}).get(collection)
    if not srcs:
        raise ValueError("sources.json 的 collections.%s 没有源" % collection)
    return srcs


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_model(model_path: str):
    global _MODEL, _MODEL_PATH
    if _MODEL is not None and _MODEL_PATH == model_path:
        return _MODEL
    from sentence_transformers import SentenceTransformer
    _MODEL = SentenceTransformer(model_path, device="cpu")
    _MODEL_PATH = model_path
    return _MODEL


def _get_reranker(model_path: str):
    global _RERANKER, _RERANKER_PATH
    if _RERANKER is not None and _RERANKER_PATH == model_path:
        return _RERANKER
    from sentence_transformers import CrossEncoder
    _RERANKER = CrossEncoder(model_path, device="cpu")
    _RERANKER_PATH = model_path
    return _RERANKER


def rerank(query: str, candidates: List[Dict],
           model_path: Optional[str] = None,
           top_k: Optional[int] = None) -> List[Dict]:
    """CrossEncoder 重排；输入/输出都是 search 的结果 dict。"""
    if not candidates:
        return []
    model = _get_reranker(model_path or DEFAULT_RERANK_MODEL)
    pairs = [(query, ((c.get("heading") or "") + "\n" +
                      (c.get("text") or "")).strip()[:2000])
             for c in candidates]
    scores = model.predict(pairs, batch_size=16, show_progress_bar=False)
    out = []
    for c, score in zip(candidates, scores):
        d = dict(c)
        d["rerank_score"] = float(score)
        out.append(d)
    out.sort(key=lambda x: -x["rerank_score"])
    return out[:top_k] if top_k else out


def _jieba_module():
    global _JIEBA
    if _JIEBA is None:
        import logging
        import jieba
        jieba.setLogLevel(logging.ERROR)
        _JIEBA = jieba
    return _JIEBA


def fts_tokens(text: str) -> str:
    """jieba 分词后转成空格分隔的 FTS5 token。"""
    toks = []
    for piece in _jieba_module().cut((text or "").lower(), cut_all=False):
        for m in re.findall(r"[0-9a-z_\-一-鿿]+", piece):
            if m:
                toks.append(m)
    return " ".join(toks)


def fts_query(text: str) -> str:
    """把查询转成 FTS5 MATCH 表达式；空查询返回空串。"""
    toks = []
    for t in fts_tokens(text).split():
        if t and t not in toks:
            toks.append(t)
    if not toks:
        return ""
    return " OR ".join('"%s"' % t.replace('"', '""') for t in toks[:32])


def _window_lines(lines, max_chars: int, overlap: int):
    """把 [(lineno, text)] 按字符数切窗口，返回 (text, start, end)。"""
    if not lines:
        return []
    out = []
    buf = []
    buf_len = 0
    for lineno, line in lines:
        if buf and buf_len + len(line) + 1 > max_chars:
            text = "\n".join(x[1] for x in buf).strip()
            if text:
                out.append((text, buf[0][0], buf[-1][0]))
            tail = []
            tail_len = 0
            for x in reversed(buf):
                if tail_len + len(x[1]) + 1 > overlap:
                    break
                tail.insert(0, x)
                tail_len += len(x[1]) + 1
            buf = tail
            buf_len = tail_len
        buf.append((lineno, line))
        buf_len += len(line) + 1
    text = "\n".join(x[1] for x in buf).strip()
    if text:
        out.append((text, buf[0][0], buf[-1][0]))
    return out


def chunk_text(text: str, is_markdown: bool = True,
               max_chars: int = 800, overlap: int = 80) -> List[Dict]:
    """返回 [{text, heading, line_start, line_end}]；行号 1 基。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    sections = []
    if is_markdown:
        cur_heading = ""
        cur_lines = []
        cur_start = 1
        heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
        for i, line in enumerate(lines, 1):
            m = heading_re.match(line)
            if m:
                if cur_lines:
                    sections.append((cur_heading, cur_lines, cur_start))
                cur_heading = m.group(2).strip()
                cur_lines = []
                cur_start = i + 1
            else:
                if not cur_lines:
                    cur_start = i
                cur_lines.append((i, line))
        if cur_lines:
            sections.append((cur_heading, cur_lines, cur_start))
    else:
        sections.append(("", [(i, line) for i, line in enumerate(lines, 1)], 1))

    chunks = []
    for heading, sec_lines, _start in sections:
        for body, ls, le in _window_lines(sec_lines, max_chars, overlap):
            if len(body.strip()) < MIN_CHUNK_CHARS:
                continue
            chunks.append({
                "text": body,
                "heading": heading,
                "line_start": ls,
                "line_end": le,
            })
    return chunks


def load_sources(config_path: str) -> Dict:
    if not os.path.isfile(config_path):
        raise FileNotFoundError("sources.json 不存在：%s" % config_path)
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg.get("sources"), list) or not cfg["sources"]:
        raise ValueError("sources.json 缺 sources 列表")
    cols = cfg.get("collections")
    if cols is not None and not isinstance(cols, dict):
        raise ValueError("sources.json 的 collections 必须是对象")
    if isinstance(cols, dict):
        for name, srcs in cols.items():
            if name not in COLLECTIONS:
                raise ValueError("未知 collection：%s" % name)
            if not isinstance(srcs, list):
                raise ValueError("collections.%s 必须是源列表" % name)
    return cfg


def iter_source_files(cfg: Dict, collection: Optional[str] = None) -> Iterable[Dict]:
    seen = set()
    for src in collection_sources(cfg, collection):
        root = os.path.abspath(src["path"])
        if not os.path.isdir(root):
            continue
        include = set(x.lower() for x in (src.get("include") or DEFAULT_INCLUDE))
        excludes = [x.lower() for x in (src.get("exclude") or [])]
        exclude_files = set()
        for x in (src.get("exclude_files") or []):
            p = x if os.path.isabs(x) else os.path.join(root, x)
            exclude_files.add(os.path.normcase(os.path.abspath(p)))
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
                and not any(p in d.lower() for p in excludes)
            ]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in include:
                    continue
                path = os.path.abspath(os.path.join(dirpath, fn))
                if os.path.normcase(path) in exclude_files:
                    continue
                low = path.lower()
                if any(p in low for p in excludes):
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if st.st_size > MAX_FILE_BYTES or st.st_size == 0:
                    continue
                key = os.path.normcase(path)
                if key in seen:
                    continue
                seen.add(key)
                rel = os.path.relpath(path, root).replace("\\", "/")
                yield {
                    "path": path,
                    "rel_path": rel,
                    "scope": src.get("scope") or "global",
                    "project": src.get("project") or "",
                    "kind": ext.lstrip("."),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }


def _schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS files (
      path TEXT PRIMARY KEY, sha1 TEXT, mtime REAL, size INTEGER,
      chunks INTEGER, scope TEXT, project TEXT
    );
    CREATE TABLE IF NOT EXISTS chunks (
      id TEXT PRIMARY KEY, faiss_id INTEGER UNIQUE, path TEXT, rel_path TEXT,
      scope TEXT, project TEXT, heading TEXT, line_start INTEGER,
      line_end INTEGER, text TEXT, sha1 TEXT, mtime REAL, kind TEXT,
      vector BLOB, dupe_sources TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
    CREATE INDEX IF NOT EXISTS idx_chunks_scope ON chunks(scope, project);
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
      chunk_id UNINDEXED, text_tokens, heading_tokens, path_tokens,
      tokenize='unicode61 remove_diacritics 0'
    );
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
    if "dupe_sources" not in cols:
        conn.execute("ALTER TABLE chunks ADD COLUMN dupe_sources TEXT")


def _meta_get(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _meta_set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                 (key, str(value)))


def _load_existing(conn):
    files = {}
    for path, sha1, mtime, size in conn.execute(
            "SELECT path,sha1,mtime,size FROM files"):
        files[path] = {"sha1": sha1, "mtime": mtime, "size": size}
    return files


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _chunk_id(path: str, start: int, text: str) -> str:
    return sha1_bytes(("%s|%d|%s" % (path, start, text)).encode("utf-8"))[:16]


def _faiss_write(index, path: str):
    """用 serialize_index 写字节，避开 FAISS C++ 在中文路径上的限制。"""
    import faiss
    import numpy as np
    arr = np.asarray(faiss.serialize_index(index), dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(arr.tobytes())


def _faiss_read(path: str):
    import faiss
    import numpy as np
    with open(path, "rb") as f:
        buf = f.read()
    return faiss.deserialize_index(np.frombuffer(buf, dtype=np.uint8))


def _rebuild_faiss(conn, index_dir: str):
    import faiss
    import numpy as np
    dim = int(_meta_get(conn, "dim") or 0)
    if not dim:
        raise ValueError("index 缺 dim")
    rows = list(conn.execute(
        "SELECT faiss_id, vector FROM chunks WHERE vector IS NOT NULL ORDER BY faiss_id"))
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
    if rows:
        ids = np.array([r[0] for r in rows], dtype="int64")
        vecs = np.vstack([np.frombuffer(r[1], dtype="float32") for r in rows])
        index.add_with_ids(vecs, ids)
    _faiss_write(index, os.path.join(index_dir, "vectors.faiss"))


def _rebuild_fts(conn):
    try:
        conn.execute("DELETE FROM chunks_fts")
    except sqlite3.OperationalError:
        conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          chunk_id UNINDEXED, text_tokens, heading_tokens, path_tokens,
          tokenize='unicode61 remove_diacritics 0'
        );
        """)
        conn.execute("DELETE FROM chunks_fts")
    rows = conn.execute("SELECT id,text,heading,rel_path FROM chunks").fetchall()
    payload = [(r[0], fts_tokens(r[1]), fts_tokens(r[2]), fts_tokens(r[3]))
               for r in rows]
    if payload:
        conn.executemany(
            "INSERT INTO chunks_fts(chunk_id,text_tokens,heading_tokens,path_tokens) "
            "VALUES(?,?,?,?)", payload)
    conn.commit()
    return len(payload)


def _dedup_chunks(conn):
    """精确文本去重：保留最早 faiss_id 的 chunk，其余来源记入 duplicates。"""
    rows = conn.execute(
        "SELECT id,faiss_id,path,rel_path,line_start,line_end,text,dupe_sources "
        "FROM chunks ORDER BY faiss_id").fetchall()
    groups = {}
    for r in rows:
        key = " ".join((r[6] or "").split())
        if key:
            groups.setdefault(key, []).append(r)
    deleted = 0
    merged_refs = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        canonical = min(group, key=lambda r: r[1] or 0)
        refs = []
        for r in group:
            if r[7]:
                try:
                    refs.extend(json.loads(r[7]))
                except Exception:
                    pass
            if r[0] != canonical[0]:
                refs.append({"path": r[2], "rel_path": r[3],
                             "line_start": r[4], "line_end": r[5]})
        can_key = (canonical[2], canonical[4], canonical[5])
        seen = set()
        clean = []
        for x in refs:
            k = (x.get("path"), x.get("line_start"), x.get("line_end"))
            if k == can_key or k in seen:
                continue
            seen.add(k)
            clean.append(x)
        conn.execute("UPDATE chunks SET dupe_sources=? WHERE id=?",
                     (json.dumps(clean, ensure_ascii=False), canonical[0]))
        for r in group:
            if r[0] != canonical[0]:
                conn.execute("DELETE FROM chunks WHERE id=?", (r[0],))
                deleted += 1
        merged_refs += len(clean)
    conn.execute("UPDATE files SET chunks=(SELECT COUNT(*) FROM chunks "
                 "WHERE chunks.path=files.path)")
    conn.commit()
    return deleted, merged_refs


def _norm_shingle_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _shingles(text: str, n: int = NEAR_DUP_SHINGLE):
    s = _norm_shingle_text(text)
    if not s:
        return set()
    if len(s) <= n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _chunk_ref(row):
    return {"id": row[0], "faiss_id": row[1], "path": row[2],
            "rel_path": row[3], "line_start": row[4], "line_end": row[5]}


def _union_find_groups(pairs):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups = {}
    for x in list(parent):
        groups.setdefault(find(x), []).append(x)
    return list(groups.values())


def near_duplicate_groups(conn, threshold: float = NEAR_DUP_THRESHOLD,
                          shingle: int = NEAR_DUP_SHINGLE,
                          max_df: int = NEAR_DUP_MAX_DF):
    """按字符 shingle 的 Jaccard 相似度找近似重复 chunk（只读）。

    相似簇用并查集连通；threshold=0.9 表示两个 chunk 的 shingle 集合
    Jaccard >= 0.9。它找的是"同一段文字的小改/多版"，不是同主题。
    """
    rows = conn.execute(
        "SELECT id,faiss_id,path,rel_path,line_start,line_end,text "
        "FROM chunks ORDER BY faiss_id").fetchall()
    if len(rows) < 2:
        return []
    by_id = {r[0]: r for r in rows}
    sets = {r[0]: _shingles(r[6], shingle) for r in rows}
    inverted = {}
    for cid, sh in sets.items():
        for token in sh:
            inverted.setdefault(token, []).append(cid)
    overlap = {}
    for token, ids in inverted.items():
        if len(ids) < 2 or len(ids) > max_df:
            continue
        ids = sorted(ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j])
                overlap[key] = overlap.get(key, 0) + 1
    pairs = {}
    for (a, b), common in overlap.items():
        sa, sb = sets[a], sets[b]
        m = min(len(sa), len(sb))
        if not m:
            continue
        mx = max(len(sa), len(sb))
        jac = common / len(sa | sb) if (sa | sb) else 0.0
        containment = common / m
        length_ratio = m / mx if mx else 0.0
        # 整段复制常见形态是"一边是另一边的近子集"：Jaccard 会被长度差
        # 拉低，所以长度接近时再允许 containment 达标。
        score = max(jac, containment) if length_ratio >= 0.8 else jac
        if score >= threshold:
            pairs[(a, b)] = round(score, 4)
    if not pairs:
        return []
    out = []
    for comp in _union_find_groups(pairs.keys()):
        if len(comp) < 2:
            continue
        members = [by_id[c] for c in comp]
        members.sort(key=lambda r: r[1] or 0)
        scores = [v for (a, b), v in pairs.items() if a in comp and b in comp]
        out.append({
            "size": len(members),
            "max_score": round(max(scores), 4) if scores else 0.0,
            "canonical": _chunk_ref(members[0]),
            "members": [_chunk_ref(m) for m in members],
        })
    out.sort(key=lambda g: (-g["size"], -g["max_score"]))
    return out


def _apply_near_dup(conn, groups):
    """把近似重复簇并到最早 faiss_id 的 chunk，来源写进 dupe_sources。"""
    merged = 0
    refs_total = 0
    for g in groups:
        keep = min(g["members"], key=lambda m: m["faiss_id"] or 0)
        row = conn.execute("SELECT dupe_sources FROM chunks WHERE id=?",
                           (keep["id"],)).fetchone()
        refs = []
        if row and row[0]:
            try:
                refs = json.loads(row[0])
            except Exception:
                refs = []
        seen = {(keep["path"], keep["line_start"], keep["line_end"])}
        for x in refs:
            seen.add((x.get("path"), x.get("line_start"), x.get("line_end")))
        for m in g["members"]:
            if m["id"] == keep["id"]:
                continue
            key = (m["path"], m["line_start"], m["line_end"])
            if key not in seen:
                refs.append({"path": m["path"], "rel_path": m["rel_path"],
                             "line_start": m["line_start"],
                             "line_end": m["line_end"]})
                seen.add(key)
            conn.execute("DELETE FROM chunks WHERE id=?", (m["id"],))
            merged += 1
        conn.execute("UPDATE chunks SET dupe_sources=? WHERE id=?",
                     (json.dumps(refs, ensure_ascii=False), keep["id"]))
        refs_total += len(refs)
    conn.execute("UPDATE files SET chunks=(SELECT COUNT(*) FROM chunks "
                 "WHERE chunks.path=files.path)")
    conn.commit()
    return merged, refs_total


def neardup(index_dir: str, collection: Optional[str] = None,
            threshold: float = NEAR_DUP_THRESHOLD,
            shingle: int = NEAR_DUP_SHINGLE,
            apply: bool = False, limit: int = 20) -> Dict:
    """近似重复报告；apply=True 才真正合并（默认只读）。"""
    targets = (list_collections(index_dir) if collection == "all"
               else [collection] if collection else [None])
    out = {}
    for c in targets:
        target = collection_dir(index_dir, c) if c else os.path.abspath(index_dir)
        db = os.path.join(target, "chunks.sqlite")
        if not os.path.isfile(db):
            out[c or "legacy"] = {"error": "索引不存在", "index_dir": target}
            continue
        conn = sqlite3.connect(db)
        _schema(conn)
        groups = near_duplicate_groups(conn, threshold=threshold,
                                       shingle=shingle)
        merged = 0
        refs = 0
        if apply and groups:
            merged, refs = _apply_near_dup(conn, groups)
            _rebuild_faiss(conn, target)
            fts_n = _rebuild_fts(conn)
            chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            _meta_set(conn, "chunks", chunks_n)
            _meta_set(conn, "fts_chunks", fts_n)
            conn.commit()
        chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conn.close()
        out[c or "legacy"] = {
            "collection": c or "legacy",
            "index_dir": target,
            "threshold": threshold,
            "shingle": shingle,
            "chunks": chunks_n,
            "groups": len(groups),
            "chunks_merged": merged,
            "refs_total": refs,
            "top": groups[:limit],
        }
    return out if collection == "all" else out[targets[0] or "legacy"]


def build_index(index_dir: str, config_path: str,
                model_path: Optional[str] = None,
                log=print, collection: Optional[str] = None) -> Dict:
    cfg = load_sources(config_path)
    model_path = model_path or cfg.get("model") or DEFAULT_MODEL
    target = collection_dir(index_dir, collection) if collection else os.path.abspath(index_dir)
    os.makedirs(target, exist_ok=True)
    db_path = os.path.join(target, "chunks.sqlite")
    conn = sqlite3.connect(db_path)
    _schema(conn)
    _meta_set(conn, "collection", collection or "legacy")
    stored_model = _meta_get(conn, "model")
    if stored_model and stored_model != model_path:
        raise ValueError("索引模型是 %s，当前 %s；换模型请另建索引"
                         % (stored_model, model_path))
    stored_chunk = _meta_get(conn, "chunk_version")
    if stored_chunk and stored_chunk != CHUNK_VERSION:
        raise ValueError("切块器版本变了（%s → %s）；请重建索引"
                         % (stored_chunk, CHUNK_VERSION))

    existing = _load_existing(conn)
    current = list(iter_source_files(cfg, collection))
    seen = set()
    pending = []          # (file, [chunks])
    unchanged = 0
    for f in current:
        path = f["path"]
        seen.add(path)
        f["sha1"] = sha1_file(path)
        old = existing.get(path)
        if old and old["sha1"] == f["sha1"] and int(old["size"]) == f["size"]:
            unchanged += 1
            continue
        text = _read_text(path)
        chunks = chunk_text(text, is_markdown=(f["kind"] in ("md", "markdown")))
        pending.append((f, chunks))

    # 删除已移除/已变更文件的旧 chunk（变更文件先删后插）
    changed_paths = {f["path"] for f, _ in pending}
    removed_paths = set(existing) - seen
    for path in list(changed_paths) + list(removed_paths):
        conn.execute("DELETE FROM chunks WHERE path=?", (path,))
        conn.execute("DELETE FROM files WHERE path=?", (path,))
    conn.commit()

    model = None
    if pending:
        model = _get_model(model_path)
        dim = int(model.get_embedding_dimension())
        _meta_set(conn, "model", model_path)
        _meta_set(conn, "dim", dim)
        _meta_set(conn, "chunk_version", CHUNK_VERSION)
    else:
        dim = int(_meta_get(conn, "dim") or 0)
        if not dim:
            # 空索引也写元数据，避免后续无 dim
            model = _get_model(model_path)
            dim = int(model.get_embedding_dimension())
            _meta_set(conn, "model", model_path)
            _meta_set(conn, "dim", dim)
            _meta_set(conn, "chunk_version", CHUNK_VERSION)
    _meta_set(conn, "chunker", "markdown-window")
    _meta_set(conn, "built_at", now())

    max_row = conn.execute("SELECT COALESCE(MAX(faiss_id),0) FROM chunks").fetchone()
    next_id = int(max_row[0]) + 1
    new_chunks = 0
    for f, chunks in pending:
        if not chunks:
            conn.execute(
                "INSERT OR REPLACE INTO files(path,sha1,mtime,size,chunks,scope,project) "
                "VALUES(?,?,?,?,?,?,?)",
                (f["path"], f["sha1"], f["mtime"], f["size"], 0,
                 f["scope"], f["project"]))
            continue
        texts = [((c["heading"] + "\n") if c["heading"] else "") + c["text"]
                 for c in chunks]
        import numpy as np
        vecs = model.encode(texts, normalize_embeddings=True,
                            batch_size=64, show_progress_bar=False)
        vecs = np.asarray(vecs, dtype="float32")
        for c, v in zip(chunks, vecs):
            cid = _chunk_id(f["path"], c["line_start"], c["text"])
            conn.execute(
                "INSERT OR REPLACE INTO chunks(id,faiss_id,path,rel_path,scope,project,"
                "heading,line_start,line_end,text,sha1,mtime,kind,vector) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, next_id, f["path"], f["rel_path"], f["scope"], f["project"],
                 c["heading"], c["line_start"], c["line_end"], c["text"],
                 f["sha1"], f["mtime"], f["kind"], v.tobytes()))
            next_id += 1
            new_chunks += 1
        conn.execute(
            "INSERT OR REPLACE INTO files(path,sha1,mtime,size,chunks,scope,project) "
            "VALUES(?,?,?,?,?,?,?)",
            (f["path"], f["sha1"], f["mtime"], f["size"], len(chunks),
             f["scope"], f["project"]))
    conn.commit()
    dupes_deleted, dupe_refs = _dedup_chunks(conn)
    _rebuild_faiss(conn, target)
    files_n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    try:
        existing_fts = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    except sqlite3.OperationalError:
        existing_fts = 0
    if pending or removed_paths or existing_fts != chunks_n:
        fts_n = _rebuild_fts(conn)
    else:
        fts_n = existing_fts
    _meta_set(conn, "files", files_n)
    _meta_set(conn, "chunks", chunks_n)
    _meta_set(conn, "fts_chunks", fts_n)
    weights = cfg.get("weights") or {}
    _meta_set(conn, "weights", json.dumps(weights, ensure_ascii=False, sort_keys=True))
    _meta_set(conn, "fts_version", FTS_VERSION)
    _meta_set(conn, "dupe_refs", dupe_refs)
    conn.commit()
    meta = {
        "version": 1,
        "model": model_path,
        "dim": dim,
        "chunk_version": CHUNK_VERSION,
        "chunker": "markdown-window",
        "built_at": _meta_get(conn, "built_at"),
        "files": files_n,
        "chunks": chunks_n,
        "fts_chunks": fts_n,
        "fts_tokenizer": "jieba+unicode61",
        "fts_version": FTS_VERSION,
        "dupe_refs": dupe_refs,
        "weights": weights,
        "collection": collection or "legacy",
        "index_dir": target,
    }
    with open(os.path.join(target, "index_meta.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    conn.close()
    return {
        "collection": collection or "legacy",
        "index_dir": target,
        "files_indexed": len(current),
        "files_unchanged": unchanged,
        "files_changed": len(pending),
        "files_removed": len(removed_paths),
        "chunks_new": new_chunks,
        "chunks_total": chunks_n,
        "fts_chunks": fts_n,
        "dupes_deleted": dupes_deleted,
        "dupe_refs": dupe_refs,
        "model": model_path,
        "dim": dim,
    }


def stats(index_dir: str, collection: Optional[str] = None) -> Dict:
    if collection == "all":
        cols = list_collections(index_dir)
        each = {c: stats(index_dir, collection=c) for c in cols}
        return {
            "index_dir": os.path.abspath(index_dir),
            "collection": "all",
            "collections": each,
            "totals": {
                "files": sum(x["files"] for x in each.values()),
                "chunks": sum(x["chunks"] for x in each.values()),
                "fts_chunks": sum(x["fts_chunks"] for x in each.values()),
                "dupe_refs": sum(x["dupe_refs"] for x in each.values()),
                "faiss_bytes": sum(x["faiss_bytes"] for x in each.values()),
            },
        }
    target = collection_dir(index_dir, collection) if collection else os.path.abspath(index_dir)
    db = os.path.join(target, "chunks.sqlite")
    if not os.path.isfile(db):
        raise FileNotFoundError("索引不存在：%s" % db)
    conn = sqlite3.connect(db)
    _schema(conn)
    files_n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    try:
        fts_n = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    except sqlite3.OperationalError:
        fts_n = 0
    dupe_refs = 0
    for (raw,) in conn.execute("SELECT dupe_sources FROM chunks"):
        if raw:
            try:
                dupe_refs += len(json.loads(raw))
            except Exception:
                pass
    meta = {k: _meta_get(conn, k) for k in
            ("model", "dim", "chunk_version", "chunker", "built_at", "files",
             "chunks", "fts_chunks", "fts_version", "collection")}
    conn.close()
    faiss_path = os.path.join(target, "vectors.faiss")
    return {
        "index_dir": target,
        "collection": meta.get("collection") or (collection or "legacy"),
        "files": files_n,
        "chunks": chunks_n,
        "fts_chunks": fts_n,
        "dupe_refs": dupe_refs,
        "fts_version": meta.get("fts_version"),
        "model": meta.get("model"),
        "dim": int(meta.get("dim") or 0),
        "chunk_version": meta.get("chunk_version"),
        "built_at": meta.get("built_at"),
        "faiss_bytes": os.path.getsize(faiss_path) if os.path.isfile(faiss_path) else 0,
    }


def _row_at(conn, faiss_ids=None, chunk_ids=None):
    """按 faiss_id 或 chunk_id 取行，保持传入顺序。"""
    keys = faiss_ids if faiss_ids is not None else chunk_ids
    if not keys:
        return []
    col = "faiss_id" if faiss_ids is not None else "id"
    q = ",".join("?" * len(keys))
    rows = conn.execute(
        "SELECT faiss_id,id,rel_path,path,scope,project,heading,line_start,line_end,text,dupe_sources "
        "FROM chunks WHERE %s IN (%s)" % (col, q), tuple(keys)).fetchall()
    by = {r[0] if faiss_ids is not None else r[1]: r for r in rows}
    return [by[k] for k in keys if k in by]


def _result(row, score):
    try:
        duplicates = json.loads(row[10]) if row[10] else []
    except Exception:
        duplicates = []
    return {
        "chunk_id": row[1],
        "rel_path": row[2],
        "source_path": row[3],
        "scope": row[4],
        "project": row[5],
        "heading": row[6],
        "line_start": row[7],
        "line_end": row[8],
        "text": row[9],
        "score": float(score),
        "duplicates": duplicates,
    }


def _search_one(index_dir: str, query: str, k: int = 8,
                scope: Optional[str] = None, project: Optional[str] = None,
                mode: str = "hybrid", rerank_on: bool = False,
                rerank_model: Optional[str] = None,
                rerank_n: int = 15,
                weights: Optional[Dict[str, float]] = None,
                collection_label: str = "legacy") -> List[Dict]:
    """mode: dense | bm25 | hybrid（默认 hybrid，RRF 融合）。"""
    import numpy as np
    if mode not in ("dense", "bm25", "hybrid"):
        raise ValueError("mode 只能是 dense/bm25/hybrid")
    db = os.path.join(index_dir, "chunks.sqlite")
    fpath = os.path.join(index_dir, "vectors.faiss")
    if not os.path.isfile(db) or not os.path.isfile(fpath):
        raise FileNotFoundError("索引不存在：%s" % index_dir)
    conn = sqlite3.connect(db)
    _schema(conn)
    model_path = _meta_get(conn, "model")
    if not model_path:
        conn.close()
        raise ValueError("索引缺 model")
    try:
        stored_weights = json.loads(_meta_get(conn, "weights") or "{}")
    except Exception:
        stored_weights = {}
    wmap = dict(stored_weights)
    if weights:
        wmap.update(weights)
    over = max(k * 10, rerank_n if rerank_on else 0, 40)
    dense_ids, bm25_ids = [], []
    dense_score, bm25_score = {}, {}

    if mode in ("dense", "hybrid"):
        import faiss
        model = _get_model(model_path)
        qv = model.encode([query], normalize_embeddings=True,
                          show_progress_bar=False)
        qv = np.asarray(qv, dtype="float32")
        index = _faiss_read(fpath)
        n = min(over, max(1, index.ntotal))
        scores, ids = index.search(qv, n)
        fids = [int(x) for x in ids[0].tolist() if int(x) >= 0]
        for fid, score in zip(fids, scores[0].tolist()):
            dense_score[fid] = float(score)
        rows = _row_at(conn, faiss_ids=fids)
        for row in rows:
            if scope and row[4] != scope:
                continue
            if project and row[5] != project:
                continue
            dense_ids.append(row[1])

    if mode in ("bm25", "hybrid"):
        mq = fts_query(query)
        if mq:
            try:
                rows = conn.execute(
                    "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? "
                    "ORDER BY bm25(chunks_fts) LIMIT ?", (mq, over)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            cids = [r[0] for r in rows]
            for row in _row_at(conn, chunk_ids=cids):
                if scope and row[4] != scope:
                    continue
                if project and row[5] != project:
                    continue
                bm25_ids.append(row[1])

    if mode == "dense":
        ordered = dense_ids
        scores_final = {r[1]: dense_score.get(r[0], 0.0)
                        for r in _row_at(conn, faiss_ids=list(dense_score.keys()))}
    elif mode == "bm25":
        ordered = bm25_ids
        scores_final = {cid: 0.0 for cid in ordered}
    else:
        rrf = {}
        for lst in (dense_ids, bm25_ids):
            for rank, cid in enumerate(lst, 1):
                rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (RRF_K + rank)
        if wmap:
            cand_rows = {r[1]: r for r in _row_at(conn, chunk_ids=list(rrf))}
            weighted = {}
            for cid, base in rrf.items():
                row = cand_rows.get(cid)
                proj = row[5] if row else ""
                weighted[cid] = base * float(wmap.get(proj, 1.0))
            rrf = weighted
        ordered = sorted(rrf, key=lambda c: -rrf[c])
        scores_final = rrf

    ordered = ordered[:max(rerank_n, k) if rerank_on else k]
    rows = _row_at(conn, chunk_ids=ordered)
    by_id = {r[1]: r for r in rows}
    out = [_result(by_id[cid], scores_final.get(cid, 0.0))
           for cid in ordered if cid in by_id]
    conn.close()
    if rerank_on and out:
        out = rerank(query, out, model_path=rerank_model, top_k=k)
    else:
        out = out[:k]
    for r in out:
        r["collection"] = collection_label
    return out


def _search_all(index_dir: str, query: str, k: int = 8,
                scope: Optional[str] = None, project: Optional[str] = None,
                mode: str = "hybrid", rerank_on: bool = False,
                rerank_model: Optional[str] = None,
                rerank_n: int = 15,
                weights: Optional[Dict[str, float]] = None,
                collection_weights: Optional[Dict[str, float]] = None) -> List[Dict]:
    """跨 collection 检索：默认查 active 四库；archive 只走显式 --collection archive。"""
    cols = [c for c in list_collections(index_dir) if c != "archive"]
    cw = collection_weights or {}
    per = []
    for c in cols:
        rows = _search_one(collection_dir(index_dir, c), query,
                           k=max(k, rerank_n if rerank_on else k),
                           scope=scope, project=project, mode=mode,
                           rerank_on=False, weights=weights,
                           collection_label=c)
        per.append((c, rows))
    if not per:
        return []
    fusion, keep = {}, {}
    for c, rows in per:
        cw_value = float(cw.get(c, 1.0))
        for rank, r in enumerate(rows, 1):
            key = (c, r["chunk_id"])
            fusion[key] = (fusion.get(key, 0.0) +
                           cw_value / (RRF_K + rank))
            if key not in keep:
                d = dict(r)
                d["collection_score"] = r.get("score", 0.0)
                d["collection_weight"] = cw_value
                keep[key] = d
    ordered = sorted(fusion, key=lambda x: -fusion[x])
    limit = max(rerank_n, k) if rerank_on else k
    out = []
    for key in ordered[:limit]:
        d = keep[key]
        d["score"] = fusion[key]
        out.append(d)
    if rerank_on and out:
        out = rerank(query, out, model_path=rerank_model, top_k=k)
    else:
        out = out[:k]
    return out


def search(index_dir: str, query: str, k: int = 8,
           scope: Optional[str] = None, project: Optional[str] = None,
           mode: str = "hybrid", rerank_on: bool = False,
           rerank_model: Optional[str] = None,
           rerank_n: int = 15,
           weights: Optional[Dict[str, float]] = None,
           collection_weights: Optional[Dict[str, float]] = None,
           collection: Optional[str] = None) -> List[Dict]:
    if collection == "all":
        return _search_all(index_dir, query, k=k, scope=scope, project=project,
                           mode=mode, rerank_on=rerank_on,
                           rerank_model=rerank_model, rerank_n=rerank_n,
                           weights=weights,
                           collection_weights=collection_weights)
    target = collection_dir(index_dir, collection) if collection else os.path.abspath(index_dir)
    return _search_one(target, query, k=k, scope=scope, project=project,
                       mode=mode, rerank_on=rerank_on,
                       rerank_model=rerank_model, rerank_n=rerank_n,
                       weights=weights, collection_label=collection or "legacy")


def _filter_questions(index_dir: str, collection: Optional[str],
                      questions: List[Dict]) -> List[Dict]:
    """只保留归该 collection 的题；skills/archive 可能为 0 题。

    题目自带 collection 字段时以它为准——同名文件可能同时存在于
    core/skills/memory（例如 prompt-specs-by-engine.md），只看路径会把
    一道 skills 题算进 core。没有 collection 字段时才回落到路径匹配。
    """
    if collection not in COLLECTIONS:
        return questions
    db = os.path.join(collection_dir(index_dir, collection), "chunks.sqlite")
    if not os.path.isfile(db):
        return []
    conn = sqlite3.connect(db)
    paths = []
    for rel, path in conn.execute("SELECT DISTINCT rel_path,path FROM chunks"):
        paths.append(((rel or "").replace("\\", "/"),
                      (path or "").replace("\\", "/")))
    conn.close()
    out = []
    for q in questions:
        declared = q.get("collection")
        if declared and declared != collection:
            continue
        if declared == collection:
            out.append(q)
            continue
        for e in q.get("expected_paths") or []:
            e = e.replace("\\", "/")
            if re.match(r"^[A-Za-z]:/", e):
                hit = any(path == e or path.endswith(e) for _rel, path in paths)
            else:
                hit = any(rel == e or rel.endswith("/" + e) or
                          e.endswith("/" + rel) for rel, _path in paths)
            if hit:
                out.append(q)
                break
    return out


def evaluate(index_dir: str, questions_path: str, k: int = 5,
             mode: str = "hybrid", rerank_on: bool = False,
             rerank_model: Optional[str] = None,
             rerank_n: int = 15,
             weights: Optional[Dict[str, float]] = None,
             collection_weights: Optional[Dict[str, float]] = None,
             collection: Optional[str] = None,
             split: Optional[str] = None,
             questions: Optional[List[Dict]] = None) -> Dict:
    if questions is None:
        with open(questions_path, encoding="utf-8") as f:
            data = json.load(f)
        questions = data.get("questions") or []
    if split and split != "all":
        questions = [q for q in questions
                     if (q.get("split") or "dev") == split]
    questions = _filter_questions(index_dir, collection, questions)
    results = []
    hits = 0
    mrr = 0.0
    support_hits = 0
    support_total = 0
    for q in questions:
        got = search(index_dir, q["question"], k=k, scope=q.get("scope"),
                     mode=mode, rerank_on=rerank_on, rerank_model=rerank_model,
                     rerank_n=rerank_n, weights=weights,
                     collection_weights=collection_weights,
                     collection=collection)
        expected = [x.replace("\\", "/") for x in (q.get("expected_paths") or [])]
        rank = 0
        for i, r in enumerate(got, 1):
            rel = (r.get("rel_path") or "").replace("\\", "/")
            src = (r.get("source_path") or "").replace("\\", "/")
            if any(rel.endswith(e) or e in rel or src.endswith(e) or e in src
                   for e in expected):
                rank = i
                break
        hit = rank > 0
        hits += 1 if hit else 0
        mrr += (1.0 / rank) if rank else 0.0
        terms = [t for t in (q.get("answer_terms") or []) if t]
        supported = False
        support_detail = None
        if terms:
            support_total += 1
            for i, r in enumerate(got, 1):
                blob = (r.get("text") or "") + "\n" + (r.get("heading") or "")
                if all(t in blob for t in terms):
                    supported = True
                    support_detail = i
                    break
            support_hits += 1 if supported else 0
        results.append({
            "id": q.get("id"),
            "split": q.get("split") or "dev",
            "question": q["question"],
            "expected_paths": expected,
            "answer_terms": terms,
            "hit": hit,
            "rank": rank or None,
            "supported": supported if terms else None,
            "support_rank": support_detail,
            "top": [r["rel_path"] for r in got],
        })
    total = len(questions)
    return {
        "total": total,
        "hits": hits,
        "recall": (hits / total) if total else 0.0,
        "mrr": (mrr / total) if total else 0.0,
        "support": support_hits,
        "support_total": support_total,
        "support_rate": (support_hits / support_total) if support_total else 0.0,
        "k": k,
        "mode": mode,
        "rerank": bool(rerank_on),
        "collection": collection or "legacy",
        "split": split or "all",
        "results": results,
    }


SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token)\b"
               r"\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\bpassword\b\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]


SECRET_PLACEHOLDER = re.compile(
    r"(?i)(?:x{5,}|your[_ -]?|example|placeholder|redacted|dummy|test|"
    r"\.\.\.|\$\{?\w+|<[^>]+>)")


def _secret_hit(text: str) -> bool:
    for pat in SECRET_PATTERNS:
        for m in pat.finditer(text):
            if SECRET_PLACEHOLDER.search(m.group(0)):
                continue
            return True
    return False


def _line_count(path: str) -> int:
    try:
        t = _read_text(path).replace("\r\n", "\n").replace("\r", "\n")
        return len(t.split("\n"))
    except OSError:
        return -1


def _check(cid, status, summary, **kw):
    item = {"id": cid, "status": status, "summary": summary}
    item.update({k: v for k, v in kw.items() if v is not None})
    return item


def audit(index_dir: str, config_path: str,
          questions_path: Optional[str] = None,
          k: int = 5, mode: str = "hybrid",
          rerank_on: bool = False,
          rerank_model: Optional[str] = None,
          min_recall: Optional[float] = None,
          collection: Optional[str] = None,
          collection_weights: Optional[Dict[str, float]] = None,
          split: Optional[str] = None,
          min_support: Optional[float] = None) -> Dict:
    """知识库审查：完整性/源新鲜度/引用/密钥/重复/覆盖/检索门。"""
    checks = []
    target = collection_dir(index_dir, collection) if collection else os.path.abspath(index_dir)
    db = os.path.join(target, "chunks.sqlite")
    faiss_path = os.path.join(target, "vectors.faiss")
    if not os.path.isfile(db) or not os.path.isfile(faiss_path):
        checks.append(_check("integrity", "fail",
                             "缺 chunks.sqlite 或 vectors.faiss"))
        rep = {"overall": "BLOCK", "checks": checks, "generated_at": now(),
               "collection": collection or "legacy",
               "index_dir": target}
        with open(os.path.join(target, "audit.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        return rep

    conn = sqlite3.connect(db)
    _schema(conn)
    model = _meta_get(conn, "model")
    dim = int(_meta_get(conn, "dim") or 0)
    chunk_ver = _meta_get(conn, "chunk_version")
    chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    files_n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    try:
        fts_n = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    except sqlite3.OperationalError:
        fts_n = 0
    integrity_bad = []
    if not model or not dim:
        integrity_bad.append("缺 model/dim")
    if chunk_ver != CHUNK_VERSION:
        integrity_bad.append("chunk_version=%r" % chunk_ver)
    if fts_n != chunks_n:
        integrity_bad.append("FTS=%d != chunks=%d" % (fts_n, chunks_n))
    if os.path.getsize(faiss_path) == 0:
        integrity_bad.append("vectors.faiss 为空")
    checks.append(_check(
        "integrity", "fail" if integrity_bad else "ok",
        "; ".join(integrity_bad) if integrity_bad else
        "%d files / %d chunks / %d fts / dim=%d" % (
            files_n, chunks_n, fts_n, dim)))

    # 源新鲜度
    try:
        cfg = load_sources(config_path)
    except Exception as e:
        cfg = None
        checks.append(_check("sources", "fail", "sources.json 不可读：%s" % e))
    if cfg is not None:
        current = {}
        for f in iter_source_files(cfg, collection):
            try:
                f["sha1"] = sha1_file(f["path"])
                current[f["path"]] = f
            except OSError:
                pass
        indexed = {r[0]: r[1] for r in conn.execute(
            "SELECT path,sha1 FROM files")}
        missing = sorted(set(indexed) - set(current))
        new = sorted(set(current) - set(indexed))
        changed = sorted(p for p in set(current) & set(indexed)
                         if current[p]["sha1"] != indexed[p])
        stale = bool(missing or new or changed)
        checks.append(_check(
            "sources", "fail" if stale else "ok",
            "missing=%d new=%d changed=%d" % (
                len(missing), len(new), len(changed)),
            details=(missing + new + changed)[:10]))

        # 密钥扫描（源文件原文）
        secret_hits = []
        for path in current:
            try:
                text = _read_text(path)
            except OSError:
                continue
            if _secret_hit(text):
                secret_hits.append(path)
        checks.append(_check(
            "secrets", "fail" if secret_hits else "ok",
            "命中 %d 个源文件" % len(secret_hits),
            details=secret_hits[:10]))

    # 引用可追溯
    line_cache = {}
    broken = []
    rows = conn.execute(
        "SELECT id,path,line_start,line_end,text FROM chunks").fetchall()
    for cid, path, ls, le, text in rows:
        if not os.path.isfile(path):
            broken.append("%s: 源文件不存在" % cid)
            continue
        if ls is None or le is None or ls < 1 or le < ls:
            broken.append("%s: 行号非法 %s-%s" % (cid, ls, le))
            continue
        if path not in line_cache:
            line_cache[path] = _line_count(path)
        n = line_cache[path]
        if n >= 0 and le > n:
            broken.append("%s: 行号 %d 超出 %d" % (cid, le, n))
        if not (text or "").strip():
            broken.append("%s: 空 chunk" % cid)
    checks.append(_check(
        "citations", "fail" if broken else "ok",
        "坏引用 %d / %d" % (len(broken), chunks_n),
        details=broken[:10]))

    # 精确重复
    seen = {}
    dup = 0
    for (text,) in conn.execute("SELECT text FROM chunks"):
        h = sha1_bytes(" ".join((text or "").split()).encode("utf-8"))
        if h in seen:
            dup += 1
        else:
            seen[h] = True
    ratio = (dup / chunks_n) if chunks_n else 0.0
    merged_refs = 0
    for (raw,) in conn.execute("SELECT dupe_sources FROM chunks"):
        if raw:
            try:
                merged_refs += len(json.loads(raw))
            except Exception:
                pass
    checks.append(_check(
        "duplicates", "warn" if dup else "ok",
        "重复 chunk %d / %d = %.1f%%；已合并引用 %d" % (
            dup, chunks_n, ratio * 100, merged_refs)))

    # 近似重复：只报告，不阻断发布
    try:
        near_groups = near_duplicate_groups(conn)
        near_chunks = sum(g["size"] - 1 for g in near_groups)
        near_max = max((g["size"] for g in near_groups), default=0)
        checks.append(_check(
            "near_duplicates", "warn" if near_groups else "ok",
            "近似重复簇 %d（涉及 %d chunks，最大簇 %d，阈值 %.2f）" % (
                len(near_groups), near_chunks, near_max,
                NEAR_DUP_THRESHOLD),
            details=[g["canonical"]["rel_path"] for g in near_groups[:5]]))
    except Exception as e:
        checks.append(_check("near_duplicates", "warn",
                             "检测失败：%s" % e))

    # 覆盖：零 chunk 文件若在 duplicates 里有引用，算已覆盖
    zero_paths = [r[0] for r in conn.execute(
        "SELECT path FROM files WHERE chunks=0")]
    dup_paths = set()
    for (raw,) in conn.execute("SELECT dupe_sources FROM chunks"):
        if raw:
            try:
                for x in json.loads(raw):
                    if x.get("path"):
                        dup_paths.add(x["path"])
            except Exception:
                pass
    uncovered = [p for p in zero_paths if p not in dup_paths]
    projects = {}
    for proj, n in conn.execute(
            "SELECT project, COUNT(*) FROM chunks GROUP BY project ORDER BY project"):
        projects[proj or "(none)"] = n
    checks.append(_check(
        "coverage", "warn" if uncovered else "ok",
        "零 chunk 文件 %d（合并引用覆盖 %d；未覆盖 %d）；项目 %d" % (
            len(zero_paths), len(zero_paths) - len(uncovered),
            len(uncovered), len(projects)),
        projects=projects, details=uncovered[:10]))

    # 检索门
    if questions_path and os.path.isfile(questions_path):
        try:
            ev = evaluate(index_dir, questions_path, k=k, mode=mode,
                          rerank_on=rerank_on, rerank_model=rerank_model,
                          collection=collection,
                          collection_weights=collection_weights,
                          split=split)
            if ev["total"] == 0:
                checks.append(_check(
                    "retrieval", "warn",
                    "该 collection 无对应题；检索指标不适用"))
            else:
                bad = min_recall is not None and ev["recall"] < min_recall
                support_txt = ""
                if ev.get("support_total"):
                    support_txt = " support@%d=%.4f (%d/%d)" % (
                        k, ev["support_rate"], ev["support"],
                        ev["support_total"])
                checks.append(_check(
                    "retrieval", "fail" if bad else "ok",
                    "Recall@%d=%.4f (%d/%d) MRR=%.4f%s" % (
                        k, ev["recall"], ev["hits"], ev["total"], ev["mrr"],
                        support_txt),
                    metrics=ev))
                if ev.get("support_total"):
                    weak = (min_support is not None and
                            ev["support_rate"] < min_support)
                    checks.append(_check(
                        "grounding", "warn" if weak else "ok",
                        "证据覆盖 support@%d=%.4f (%d/%d)；只衡量 top-k 是否"
                        "含答案词，不等于答案忠实" % (
                            k, ev["support_rate"], ev["support"],
                            ev["support_total"]),
                        metrics={"support": ev["support"],
                                 "support_total": ev["support_total"],
                                 "support_rate": ev["support_rate"]}))
        except Exception as e:
            checks.append(_check("retrieval", "fail", "评测失败：%s" % e))
    else:
        checks.append(_check("retrieval", "warn", "未提供 questions.json"))

    conn.close()
    overall = "BLOCK" if any(c["status"] == "fail" for c in checks) else "PASS"
    rep = {
        "overall": overall,
        "generated_at": now(),
        "collection": collection or "legacy",
        "index_dir": target,
        "checks": checks,
    }
    with open(os.path.join(target, "audit.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    return rep
