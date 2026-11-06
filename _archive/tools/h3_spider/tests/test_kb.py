# -*- coding: utf-8 -*-
import json
import os
import sqlite3

import pytest

from fanxing import kb

MODEL = r"E:/Models/Embedding/bge-small-zh-v1.5"
pytestmark = pytest.mark.skipif(not os.path.isdir(MODEL),
                                reason="bge-small-zh-v1.5 不在本机")


def _corpus(tmp_path):
    root = tmp_path / "corpus"
    docs = root / "docs"
    secret = root / "密钥"
    docs.mkdir(parents=True)
    secret.mkdir(parents=True)
    (docs / "a.md").write_text(
        "# 舰桥对白\n\n## 状态\nKB23 舰桥行星已经碎裂，只剩碎片环。\n\n"
        "## 首帧\n首帧是女军官侧脸，背景是无框舷窗。\n",
        encoding="utf-8")
    (docs / "b.md").write_text(
        "# 跑前闸\n\nG13 有六个槽，必须由人决定；机器不能代填。\n",
        encoding="utf-8")
    (secret / "密钥.txt").write_text("API KEY = sk-test-fake\n",
                                    encoding="utf-8")
    cfg = {
        "model": MODEL,
        "sources": [{
            "path": str(root),
            "scope": "global",
            "project": "test",
            "include": [".md", ".txt"],
            "exclude": ["密钥", "secret"],
        }],
    }
    cfg_path = tmp_path / "sources.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return cfg_path, tmp_path / "index"


def test_chunk_markdown_headings():
    text = ("# 总\n前言\n\n## 甲\n甲的内容。\n\n"
            "## 乙\n乙的内容。\n")
    chunks = kb.chunk_text(text, is_markdown=True, max_chars=60)
    heads = [c["heading"] for c in chunks]
    assert "甲" in heads and "乙" in heads
    for c in chunks:
        assert c["line_start"] >= 1 and c["line_end"] >= c["line_start"]
        assert c["text"].strip()


def test_build_search_stats_incremental(tmp_path):
    cfg_path, index_dir = _corpus(tmp_path)
    st = kb.build_index(index_dir, cfg_path)
    assert st["files_indexed"] == 2
    assert st["chunks_total"] >= 2
    assert (index_dir / "vectors.faiss").is_file()
    assert (index_dir / "chunks.sqlite").is_file()
    assert (index_dir / "index_meta.json").is_file()

    hits = kb.search(index_dir, "舰桥行星碎裂", k=3)
    assert hits and hits[0]["rel_path"].endswith("a.md")
    assert "碎裂" in hits[0]["text"]
    assert hits[0]["heading"] in ("状态", "舰桥对白")

    hits2 = kb.search(index_dir, "G13 六个槽", k=3)
    assert hits2 and hits2[0]["rel_path"].endswith("b.md")

    conn = sqlite3.connect(str(index_dir / "chunks.sqlite"))
    n = conn.execute("SELECT COUNT(*) FROM chunks WHERE text LIKE '%sk-test%'").fetchone()[0]
    conn.close()
    assert n == 0

    st2 = kb.build_index(index_dir, cfg_path)
    assert st2["files_unchanged"] == 2
    assert st2["chunks_new"] == 0
    stats = kb.stats(index_dir)
    assert stats["chunks"] == st["chunks_total"]
    assert stats["fts_chunks"] == st["chunks_total"]

    conn = sqlite3.connect(str(index_dir / "chunks.sqlite"))
    n_fts = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    conn.close()
    assert n_fts == st["chunks_total"]

    bm25 = kb.search(index_dir, "G13", k=3, mode="bm25")
    assert bm25 and bm25[0]["rel_path"].endswith("b.md")
    dense = kb.search(index_dir, "G13", k=3, mode="dense")
    assert dense
    hybrid = kb.search(index_dir, "G13 六个槽", k=3, mode="hybrid")
    assert hybrid and hybrid[0]["rel_path"].endswith("b.md")


def test_eval(tmp_path):
    cfg_path, index_dir = _corpus(tmp_path)
    kb.build_index(index_dir, cfg_path)
    q = {
        "questions": [{
            "id": "q1",
            "question": "KB23 舰桥的行星状态是什么",
            "expected_paths": ["a.md"],
            "scope": "global",
        }]
    }
    qp = tmp_path / "questions.json"
    qp.write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
    rep = kb.evaluate(index_dir, qp, k=3)
    assert rep["total"] == 1
    assert rep["recall"] == 1.0
    assert rep["results"][0]["hit"] is True


class _FakeReranker:
    def predict(self, pairs, **kwargs):
        return [1.0 if "碎裂" in text else 0.0 for _, text in pairs]


def test_rerank_reorders(monkeypatch):
    candidates = [
        {"chunk_id": "b", "text": "G13 六个槽", "heading": "跑前闸",
         "rel_path": "b.md", "source_path": "", "score": 0.9},
        {"chunk_id": "a", "text": "舰桥行星碎裂", "heading": "状态",
         "rel_path": "a.md", "source_path": "", "score": 0.1},
    ]
    monkeypatch.setattr(kb, "_get_reranker", lambda path: _FakeReranker())
    out = kb.rerank("舰桥行星", candidates, model_path="fake")
    assert out[0]["chunk_id"] == "a"
    assert "rerank_score" in out[0]


def _corpus_two_projects(tmp_path):
    root = tmp_path / "corpus2"
    a = root / "a"
    b = root / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "a.md").write_text("# A\n舰桥行星已经碎裂，只剩碎片环。\n",
                            encoding="utf-8")
    (b / "b.md").write_text("# B\n舰桥行星碎裂，副官在控制台前报告。\n",
                            encoding="utf-8")
    cfg = {
        "model": MODEL,
        "sources": [
            {"path": str(a), "scope": "global", "project": "A",
             "include": [".md"]},
            {"path": str(b), "scope": "global", "project": "B",
             "include": [".md"]},
        ],
    }
    cfg_path = tmp_path / "sources2.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return cfg_path, tmp_path / "index2"


def test_source_weights(tmp_path):
    cfg_path, index_dir = _corpus_two_projects(tmp_path)
    kb.build_index(index_dir, cfg_path)
    base = kb.search(index_dir, "舰桥行星碎裂", k=2, mode="hybrid")
    assert {r["project"] for r in base} == {"A", "B"}
    hit_b = kb.search(index_dir, "舰桥行星碎裂", k=1, mode="hybrid",
                      weights={"B": 2.0})
    assert hit_b[0]["project"] == "B"
    hit_a = kb.search(index_dir, "舰桥行星碎裂", k=1, mode="hybrid",
                      weights={"A": 2.0})
    assert hit_a[0]["project"] == "A"


def test_audit_clean(tmp_path):
    cfg_path, index_dir = _corpus(tmp_path)
    kb.build_index(index_dir, cfg_path)
    rep = kb.audit(index_dir, cfg_path)
    assert rep["overall"] == "PASS"
    ids = {c["id"] for c in rep["checks"]}
    assert {"integrity", "sources", "citations", "secrets", "duplicates",
            "coverage"} <= ids


def test_audit_detects_stale_and_secret(tmp_path):
    cfg_path, index_dir = _corpus(tmp_path)
    kb.build_index(index_dir, cfg_path)
    a = tmp_path / "corpus" / "docs" / "a.md"
    a.write_text(a.read_text(encoding="utf-8") +
                 "\nsk-1234567890abcdef\n", encoding="utf-8")
    rep = kb.audit(index_dir, cfg_path)
    assert rep["overall"] == "BLOCK"
    by = {c["id"]: c for c in rep["checks"]}
    assert by["sources"]["status"] == "fail"
    assert by["secrets"]["status"] == "fail"


def test_audit_detects_missing_source(tmp_path):
    cfg_path, index_dir = _corpus(tmp_path)
    kb.build_index(index_dir, cfg_path)
    (tmp_path / "corpus" / "docs" / "b.md").unlink()
    rep = kb.audit(index_dir, cfg_path)
    assert rep["overall"] == "BLOCK"
    by = {c["id"]: c for c in rep["checks"]}
    assert by["sources"]["status"] == "fail"


def test_dedup_build(tmp_path):
    root = tmp_path / "dup"
    a = root / "a"
    b = root / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    text = "# 舰桥\n行星已经碎裂，只剩碎片环。\n"
    (a / "a.md").write_text(text, encoding="utf-8")
    (b / "b.md").write_text(text, encoding="utf-8")
    cfg = {
        "model": MODEL,
        "sources": [
            {"path": str(a), "scope": "global", "project": "A", "include": [".md"]},
            {"path": str(b), "scope": "global", "project": "B", "include": [".md"]},
        ],
    }
    cfg_path = tmp_path / "sources_dup.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    index_dir = tmp_path / "index_dup"
    st = kb.build_index(index_dir, cfg_path)
    assert st["chunks_total"] == 1
    assert st["dupes_deleted"] == 1
    assert st["dupe_refs"] == 1
    hits = kb.search(index_dir, "舰桥行星碎裂", k=3, mode="hybrid")
    assert len(hits) == 1
    assert len(hits[0]["duplicates"]) == 1
    rep = kb.audit(index_dir, cfg_path)
    by = {c["id"]: c for c in rep["checks"]}
    assert by["duplicates"]["status"] == "ok"
    assert "已合并引用 1" in by["duplicates"]["summary"]


def _corpus_collections(tmp_path):
    root = tmp_path / "layers"
    docs = {}
    for name, body in {
        "core": "# 核心规则\nG13 六个槽必须由人填。\n",
        "project": "# 项目\nKB23 舰桥行星碎裂。\n",
        "memory": "# 记忆\n上次决定保留无框舷窗。\n",
        "skills": "# 技能\n反套壳审查的触发条件是交付前。\n",
        "archive": "# 归档\n旧版流程已经停止使用。\n",
    }.items():
        d = root / name
        d.mkdir(parents=True)
        (d / (name + ".md")).write_text(body, encoding="utf-8")
        docs[name] = d
    cfg = {
        "model": MODEL,
        "sources": [{"path": str(docs["core"]), "scope": "global",
                     "project": "core", "include": [".md"]}],
        "collections": {
            name: [{"path": str(d), "scope": "global", "project": name,
                    "include": [".md"]}]
            for name, d in docs.items()
        },
    }
    cfg_path = tmp_path / "sources_layers.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return cfg_path, tmp_path / "index_layers"


def test_collection_build_search_stats_audit(tmp_path):
    cfg_path, index_dir = _corpus_collections(tmp_path)
    st = kb.build_index(index_dir, cfg_path, collection="core")
    assert st["collection"] == "core"
    assert (index_dir / "collections" / "core" / "chunks.sqlite").is_file()
    assert (index_dir / "collections" / "core" / "vectors.faiss").is_file()

    hits = kb.search(index_dir, "G13 六个槽", k=3, collection="core")
    assert hits and hits[0]["collection"] == "core"
    assert hits[0]["rel_path"].endswith("core.md")

    stats = kb.stats(index_dir, collection="core")
    assert stats["collection"] == "core"
    assert stats["files"] == 1

    rep = kb.audit(index_dir, cfg_path, collection="core")
    assert rep["collection"] == "core"
    assert rep["overall"] == "PASS"


def test_collection_all_search_and_stats(tmp_path):
    cfg_path, index_dir = _corpus_collections(tmp_path)
    kb.build_index(index_dir, cfg_path, collection="core")
    kb.build_index(index_dir, cfg_path, collection="project")
    hits = kb.search(index_dir, "舰桥行星", k=4, collection="all")
    assert any(r["collection"] == "project" for r in hits)
    stats = kb.stats(index_dir, collection="all")
    assert {"core", "project"} <= set(stats["collections"])
    assert stats["totals"]["files"] == 2


def test_exclude_files_by_relative_path(tmp_path):
    root = tmp_path / "exfile"
    root.mkdir()
    (root / "keep.md").write_text("# keep\n保留\n", encoding="utf-8")
    (root / "secret.md").write_text("# secret\nAPI KEY = sk-1234567890abcdef\n",
                                    encoding="utf-8")
    cfg = {
        "model": MODEL,
        "sources": [{
            "path": str(root), "scope": "global", "project": "ex",
            "include": [".md"], "exclude_files": ["secret.md"],
        }],
    }
    cfg_path = tmp_path / "sources_exfile.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    names = [f["rel_path"] for f in kb.iter_source_files(kb.load_sources(str(cfg_path)))]
    assert names == ["keep.md"]


def test_collection_eval_filters_questions(tmp_path):
    cfg_path, index_dir = _corpus_collections(tmp_path)
    kb.build_index(index_dir, cfg_path, collection="core")
    kb.build_index(index_dir, cfg_path, collection="project")
    q = {"questions": [
        {"id": "c1", "question": "G13 六个槽", "expected_paths": ["core.md"]},
        {"id": "p1", "question": "KB23 舰桥行星", "expected_paths": ["project.md"]},
    ]}
    qp = tmp_path / "questions_layers.json"
    qp.write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
    core = kb.evaluate(index_dir, str(qp), k=3, collection="core")
    assert core["total"] == 1 and core["hits"] == 1
    project = kb.evaluate(index_dir, str(qp), k=3, collection="project")
    assert project["total"] == 1 and project["hits"] == 1


def test_eval_support_and_split(tmp_path):
    cfg_path, index_dir = _corpus(tmp_path)
    kb.build_index(index_dir, cfg_path)
    q = {"questions": [
        {"id": "d1", "split": "dev", "question": "KB23 舰桥的行星状态",
         "expected_paths": ["a.md"], "answer_terms": ["碎裂", "碎片环"]},
        {"id": "h1", "split": "holdout", "question": "G13 六个槽谁决定",
         "expected_paths": ["b.md"], "answer_terms": ["人决定", "机器不能"]},
    ]}
    qp = tmp_path / "questions_split.json"
    qp.write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
    dev = kb.evaluate(index_dir, str(qp), k=3, split="dev")
    assert dev["total"] == 1 and dev["hits"] == 1
    assert dev["support_total"] == 1 and dev["support"] == 1
    assert dev["support_rate"] == 1.0
    hold = kb.evaluate(index_dir, str(qp), k=3, split="holdout")
    assert hold["total"] == 1 and hold["hits"] == 1
    bad = kb.evaluate(index_dir, str(qp), k=3, split="dev",
                      questions=[dict(q["questions"][0],
                                      answer_terms=["不存在的词"])])
    assert bad["support_total"] == 1 and bad["support"] == 0
    rep = kb.audit(index_dir, cfg_path, questions_path=str(qp), k=3,
                   split="dev")
    by = {c["id"]: c for c in rep["checks"]}
    assert by["grounding"]["status"] == "ok"


def test_near_dup_report_and_apply(tmp_path):
    root = tmp_path / "near"
    a = root / "a"
    b = root / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    base = ("# 舰桥\n行星已经碎裂，只剩碎片环，副官在控制台前报告损失。"
            "指挥官站在无框舷窗前，要求把剩余舰队的坐标重新核对一遍，"
            "并且把伤员名单和弹药存量一起报上来。\n")
    (a / "a.md").write_text(base, encoding="utf-8")
    (b / "b.md").write_text(base.replace("报告损失。", "报告损失了。"),
                            encoding="utf-8")
    cfg = {
        "model": MODEL,
        "sources": [
            {"path": str(a), "scope": "global", "project": "A", "include": [".md"]},
            {"path": str(b), "scope": "global", "project": "B", "include": [".md"]},
        ],
    }
    cfg_path = tmp_path / "sources_near.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    index_dir = tmp_path / "index_near"
    kb.build_index(index_dir, cfg_path)
    conn = sqlite3.connect(str(index_dir / "chunks.sqlite"))
    groups = kb.near_duplicate_groups(conn)
    conn.close()
    assert len(groups) == 1 and groups[0]["size"] == 2
    rep = kb.neardup(index_dir, threshold=0.9)
    assert rep["groups"] == 1 and rep["chunks_merged"] == 0
    assert rep["chunks"] == 2
    applied = kb.neardup(index_dir, threshold=0.9, apply=True)
    assert applied["chunks_merged"] == 1 and applied["chunks"] == 1
    hits = kb.search(index_dir, "舰桥行星碎裂", k=3)
    assert len(hits) == 1


def test_collection_weights_reorder(tmp_path):
    root = tmp_path / "cw"
    c1 = root / "c1"
    c2 = root / "c2"
    c1.mkdir(parents=True)
    c2.mkdir(parents=True)
    (c1 / "c1.md").write_text("# A\n舰桥行星碎裂，副官报告。\n", encoding="utf-8")
    (c2 / "c2.md").write_text("# B\n舰桥行星碎裂，指挥官报告。\n", encoding="utf-8")
    cfg = {
        "model": MODEL,
        "collections": {
            "core": [{"path": str(c1), "scope": "global",
                      "project": "c1", "include": [".md"]}],
            "project": [{"path": str(c2), "scope": "global",
                         "project": "c2", "include": [".md"]}],
        },
        "sources": [{"path": str(c1), "scope": "global",
                     "project": "c1", "include": [".md"]}],
    }
    cfg_path = tmp_path / "sources_cw.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    index_dir = tmp_path / "index_cw"
    kb.build_index(index_dir, cfg_path, collection="core")
    kb.build_index(index_dir, cfg_path, collection="project")
    base = kb.search(index_dir, "舰桥行星碎裂", k=2, collection="all")
    assert {r["collection"] for r in base} == {"core", "project"}
    weighted = kb.search(index_dir, "舰桥行星碎裂", k=2, collection="all",
                         collection_weights={"project": 3.0})
    assert weighted[0]["collection"] == "project"

