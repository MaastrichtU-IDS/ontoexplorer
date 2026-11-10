"""Encoding-corruption detection and clean-label fallback (label_quality)."""
import pytest

from ontoexplorer.modules.search.label_quality import (
    clean_display_label,
    count_corrupt,
    is_corrupt_label,
    local_name,
)


class TestIsCorruptLabel:
    # Real samples pulled from the affected ontologies (linkedgeodata, chebi).
    @pytest.mark.parametrize(
        "text",
        [
            "V??a de tren abandonada",            # 'Vía' (es)
            "ferr??e",                            # 'ferrée' (fr)
            "Voie ferr??e abandonn??e",
            "Zru??en?? ??elezni??n?? tra??",      # cs, diacritics
            "?????? ???????? ????????????",       # ar, whole label
            "??????????",                         # mk/ru, whole label
            "3,???4-???Dimethyl-???5-???propyl-2-???furanundecanoic acid",  # chebi
            "{11-hydroxy-16,18-dioxo-6,8,19-trioxapentacyclo[10.7.0.0?,?.0?,?.0??,??]one}",
            "?????",
            "a??b",                               # minimal run
        ],
    )
    def test_corrupt_detected(self, text):
        assert is_corrupt_label(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Abandoned Railway",
            "Verlassene Bahnstrecke",
            "programmed cell death",
            "Diabetes mellitus",
            "mitochondrion",
            "What is life?",                      # single, legitimate '?'
            "Is it so?",
            "2-aminophenyl hydrogen sulfate",
            "Vía de tren abandonada",             # proper UTF-8 is NOT corrupt
            "",
            "   ",
            "a?",                                  # only one '?'
        ],
    )
    def test_clean_not_flagged(self, text):
        assert is_corrupt_label(text) is False

    def test_none_is_safe(self):
        assert is_corrupt_label(None) is False


class TestCountCorrupt:
    def test_counts_only_corrupt(self):
        labels = ["Abandoned Railway", "V??a", "ferr??e", "mitochondrion", None, "What?"]
        assert count_corrupt(labels) == 2

    def test_empty(self):
        assert count_corrupt([]) == 0


class TestLocalName:
    def test_hash(self):
        assert local_name("http://ex.org/onto#AbandonedRailway") == "AbandonedRailway"

    def test_slash(self):
        assert local_name("http://linkedgeodata.org/ontology/AbandonedRailway") == "AbandonedRailway"

    def test_trailing_separator(self):
        assert local_name("http://ex.org/onto/wine/") == "wine"


class TestCleanDisplayLabel:
    def test_clean_primary_kept(self):
        assert clean_display_label("Abandoned Railway", "http://x/AbandonedRailway") == "Abandoned Railway"

    def test_corrupt_primary_falls_back_to_clean_alternative(self):
        assert clean_display_label(
            "V??a de tren abandonada",
            "http://x/AbandonedRailway",
            alternatives=["??????", "Abandoned Railway"],
        ) == "Abandoned Railway"

    def test_corrupt_primary_no_alt_falls_back_to_humanized_iri(self):
        assert clean_display_label(
            "V??a", "http://linkedgeodata.org/ontology/AbandonedRailway"
        ) == "Abandoned Railway"

    def test_all_corrupt_still_returns_iri_name_not_garbage(self):
        out = clean_display_label("????", "http://x/onto#SomeClass", alternatives=["??", "???"])
        assert out == "Some Class"
        assert "?" not in out
