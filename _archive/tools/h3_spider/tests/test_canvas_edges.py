# -*- coding: utf-8 -*-
import copy

import pytest

from h3_spider.canvas_edges import EdgeError, apply_edges, auto_edges, topo_order


SHOTS = [
    {"id": "U01", "image": "a.png", "mode": "i2va"},
    {"id": "U02", "image": "b.png", "mode": "ref2va", "images": ["cmdr"]},
    {"id": "U03", "image": "c.png", "mode": "ref2va"},
]


def test_topo_order_reorders():
    edges = [
        {"from": "U02", "to": "U01", "type": "order"},
        {"from": "U01", "to": "U03", "type": "order"},
    ]
    assert topo_order(["U01", "U02", "U03"], edges) == ["U02", "U01", "U03"]


def test_topo_order_rejects_cycle():
    edges = [
        {"from": "U01", "to": "U02", "type": "order"},
        {"from": "U02", "to": "U01", "type": "order"},
    ]
    with pytest.raises(EdgeError):
        topo_order(["U01", "U02"], edges)


def test_topo_order_without_edges_keeps_input():
    assert topo_order(["U01", "U02"], []) == ["U01", "U02"]


def test_no_order_edges_does_not_require_connectivity():
    assert topo_order(["U01", "U02", "U03"], []) == ["U01", "U02", "U03"]


def test_chain_sets_target_image():
    edges = [{"from": "U01", "to": "U02", "type": "chain", "binding": "U01_end.png"}]
    out = apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": "cmdr"})
    assert out[1]["image"] == "U01_end.png"


def test_chain_without_binding_rejected():
    edges = [{"from": "U01", "to": "U02", "type": "chain"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


def test_chain_blank_binding_rejected():
    edges = [{"from": "U01", "to": "U02", "type": "chain", "binding": "   "}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


@pytest.mark.parametrize("binding", [123, {"path": "x.png"}, ["x.png"], True])
def test_chain_non_string_binding_rejected(binding):
    edges = [{"from": "U01", "to": "U02", "type": "chain", "binding": binding}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


def test_chain_binding_message_names_edge():
    edges = [{"from": "U01", "to": "U02", "type": "chain", "binding": " "}]
    with pytest.raises(EdgeError) as exc:
        apply_edges(copy.deepcopy(SHOTS), edges, {})
    assert "U01 -> U02" in str(exc.value)


def test_ref_before_chain_uses_chain_image():
    shots = [
        {"id": "U01", "image": "a.png", "mode": "i2va"},
        {"id": "U02", "mode": "ref2va"},
        {"id": "U03", "mode": "ref2va"},
    ]
    edges = [
        {"from": "U03", "to": "U02", "type": "ref"},
        {"from": "U01", "to": "U02", "type": "chain", "binding": "b2.png"},
    ]
    out = apply_edges(shots, edges, {})
    assert out[1]["image"] == "b2.png"
    assert out[2]["images"] == ["b2.png"]


def test_unknown_edge_type_rejected():
    edges = [{"from": "U01", "to": "U02", "type": "bogus"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


def test_ref_adds_anchor_and_dedupes():
    edges = [
        {"from": "U03", "to": "@cmdr", "type": "ref"},
        {"from": "U03", "to": "@cmdr", "type": "ref"},
    ]
    out = apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": "cmdr"})
    assert out[2]["images"] == ["cmdr"]


def test_ref_rejects_i2va():
    edges = [{"from": "U01", "to": "@cmdr", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": "cmdr"})


def test_chain_unknown_source_rejected():
    edges = [{"from": "U99", "to": "U02", "type": "chain", "binding": "x.png"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


def test_chain_self_rejected():
    edges = [{"from": "U02", "to": "U02", "type": "chain", "binding": "x.png"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


def test_ref_anchor_empty_rejected():
    edges = [{"from": "U03", "to": "@cmdr", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": ""})


def test_ref_anchor_non_string_rejected():
    edges = [{"from": "U03", "to": "@cmdr", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": None})


def test_ref_self_rejected():
    edges = [{"from": "U02", "to": "U02", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


def test_anchors_none_allowed_when_no_anchor_referenced():
    edges = [
        {"from": "U01", "to": "U02", "type": "chain", "binding": "a_end.png"},
        {"from": "U03", "to": "U02", "type": "ref"},
    ]
    out = apply_edges(copy.deepcopy(SHOTS), edges, None)
    assert out[1]["image"] == "a_end.png"
    assert out[2]["images"] == ["a_end.png"]


def test_anchors_none_rejected_when_anchor_referenced():
    edges = [{"from": "U03", "to": "@cmdr", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, None)


def test_ref_shot_to_shot_happy_path():
    edges = [{"from": "U03", "to": "U02", "type": "ref"}]
    shots = copy.deepcopy(SHOTS)
    shots[2].pop("images", None)
    out = apply_edges(shots, edges, {})
    assert out[2]["images"] == ["b.png"]


def test_ref_source_without_image_rejected():
    shots = copy.deepcopy(SHOTS) + [{"id": "U04", "mode": "ref2va"}]
    edges = [{"from": "U03", "to": "U04", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(shots, edges, {})


def test_ref_non_list_images_rejected():
    shots = copy.deepcopy(SHOTS)
    shots[2]["images"] = "x"
    edges = [{"from": "U03", "to": "@cmdr", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(shots, edges, {"cmdr": "cmdr"})


def test_auto_edges_creates_order_chain():
    edges = auto_edges(SHOTS)
    assert [e["type"] for e in edges] == ["order", "order"]
    assert edges[0]["from"] == "U01" and edges[0]["to"] == "U02"
