import json
from ontoexplorer.modules.search.evaluator import _pick_label


def test_pick_label_prefers_requested_lang():
    detail = {
        "labels": json.dumps([
            {"value": "cell death", "lang": "en"},
            {"value": "mort cellulaire", "lang": "fr"},
        ]),
        "primary_label": "cell death",
    }
    label, lang = _pick_label(detail, "fr")
    assert label == "mort cellulaire"
    assert lang == "fr"


def test_pick_label_falls_back_to_primary():
    detail = {
        "labels": json.dumps([{"value": "cell death", "lang": "en"}]),
        "primary_label": "cell death",
    }
    label, lang = _pick_label(detail, "fr")
    assert label == "cell death"
    assert lang == "en"


def test_pick_label_no_lang_returns_primary():
    detail = {"primary_label": "cell death", "labels": "[]"}
    label, lang = _pick_label(detail, None)
    assert label == "cell death"
    assert lang is None
