# -*- coding: utf-8 -*-
"""坏样本语料门：每条 bad case 必须命中预期错误码；干净基稿必须 0 error。"""
import pytest

from h3_spider.corpus.audit import evaluate


REPORT = evaluate()


def test_corpus_recall():
    miss = [r for r in REPORT["results"] if not r["hit"]]
    assert not miss, "未命中：\n" + "\n".join(
        "%s 期望 %s，实得 %s" % (
            r["id"], r["expect"],
            [e["leg"] + "/" + str(e["code"]) for e in r["errors"]])
        for r in miss
    )


def test_holdout_recall():
    miss = [r for r in REPORT["holdout_results"] if not r["hit"]]
    assert not miss, "holdout 未命中：\n" + "\n".join(
        "%s 期望 %s，实得 %s" % (
            r["id"], r["expect"],
            [e["leg"] + "/" + str(e["code"]) for e in r["errors"]])
        for r in miss
    )


def test_task_types_match_official():
    from h3_official_spec import TASK_TYPES as OFFICIAL
    from h3_spider.legs.l1_format import TASK_TYPES
    assert set(TASK_TYPES) == set(OFFICIAL)


def test_corpus_clean_controls():
    bad = [c for c in REPORT["clean"] if not c["ok"]]
    assert not bad, "干净基稿出现误报：\n" + "\n".join(
        "%s: %s" % (c["base"],
                    [e["leg"] + "/" + str(e["code"]) for e in c["errors"]])
        for c in bad
    )


@pytest.mark.parametrize("case_id", [r["id"] for r in REPORT["results"]])
def test_corpus_case(case_id):
    r = next(x for x in REPORT["results"] if x["id"] == case_id)
    assert r["hit"], "%s 期望 %s，实得 %s" % (
        r["id"], r["expect"],
        [e["leg"] + "/" + str(e["code"]) for e in r["errors"]])


@pytest.mark.parametrize("case_id", [r["id"] for r in REPORT["holdout_results"]])
def test_holdout_case(case_id):
    r = next(x for x in REPORT["holdout_results"] if x["id"] == case_id)
    assert r["hit"], "%s 期望 %s，实得 %s" % (
        r["id"], r["expect"],
        [e["leg"] + "/" + str(e["code"]) for e in r["errors"]])
