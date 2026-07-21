"""Unit tests for pg_rows_to_completions — wrapping Postgres autocomplete rows
into MOS Completions with correct quote/insert handling."""
from ontoexplorer.modules.search.autocomplete import pg_rows_to_completions


def _row(label, iri, short="GO_1", etype="class"):
    return {"label": label, "iri": iri, "short": short, "type": etype}


def test_bare_single_word_inserts_unquoted_with_trailing_space():
    [c] = pg_rows_to_completions([_row("cell", "http://x/cell")], close_quote=False)
    assert c.text == "cell"
    assert c.insert == "cell "
    assert c.iri == "http://x/cell"


def test_bare_multi_word_is_quoted():
    [c] = pg_rows_to_completions([_row("cell division", "http://x/cd")], close_quote=False)
    assert c.text == "cell division"
    assert c.insert == "'cell division' "


def test_open_quote_closes_the_quote():
    [c] = pg_rows_to_completions([_row("cell division", "http://x/cd")], close_quote=True)
    # User already typed the opening quote; insert only closes it.
    assert c.insert == "cell division'"


def test_same_label_collision_is_disambiguated_by_short():
    rows = [
        _row("apoptosis", "http://x/a1", short="GO_1"),
        _row("apoptosis", "http://x/a2", short="GO_2"),
    ]
    cs = pg_rows_to_completions(rows, close_quote=False)
    texts = {c.text for c in cs}
    assert texts == {"apoptosis (GO_1)", "apoptosis (GO_2)"}
