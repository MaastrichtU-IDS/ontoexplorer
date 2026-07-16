"""Pinned regression test for the py-whelk flush-after-remove issue.

py-whelk 0.4.0 / whelk-rs: `reasoner.flush()` correctly invalidates the
cached classification after `onto.add_axiom(...)` but NOT after
`onto.remove_axiom(...)`. The removed axiom continues to report as
entailed.

We test BOTH directions:
- add+flush → correctly turns on entailment (this works upstream)
- remove+flush → SHOULD turn off entailment but currently leaves it on

If the second assertion ever starts failing in the *opposite* direction
(i.e. is_entailed returns False after remove, as it should), the
upstream bug has been fixed and the comment in justification.py can be
removed alongside enabling a persistent-reasoner code path.

Test is `xfail` (expected to fail) for the remove case so CI signals
when upstream lands a fix.
"""
import sys
import os
import io

sys.path.insert(0, os.path.dirname(__file__))

import pytest

_pywhelk = pytest.importorskip("pywhelk")
_pyhornedowl = pytest.importorskip("pyhornedowl")
_pyoxigraph = pytest.importorskip("pyoxigraph")


def _make_minimal_ontology():
    """Two classes, no axioms. Returns (onto, reasoner, classes_dict)."""
    import pyhornedowl
    import pyoxigraph
    import pywhelk

    nt = (
        '<http://example.org/A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> '
        '<http://www.w3.org/2002/07/owl#Class> .\n'
        '<http://example.org/B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> '
        '<http://www.w3.org/2002/07/owl#Class> .\n'
    )
    triples = pyoxigraph.parse(io.BytesIO(nt.encode()), format=pyoxigraph.RdfFormat.N_TRIPLES)
    rdfxml = pyoxigraph.serialize(triples, format=pyoxigraph.RdfFormat.RDF_XML)
    onto = pyhornedowl.open_ontology_from_string(rdfxml.decode(), serialization="rdf")
    reasoner = pywhelk.create_reasoner(onto)
    return onto, reasoner, {
        "A": onto.class_("http://example.org/A"),
        "B": onto.class_("http://example.org/B"),
    }


def test_flush_after_add_picks_up_new_axiom():
    """Baseline: flush correctly invalidates after add. (Should pass.)"""
    from pyhornedowl import model
    onto, reasoner, cls = _make_minimal_ontology()
    sco = model.SubClassOf(cls["A"], cls["B"])
    assert reasoner.is_entailed(sco) is False
    onto.add_axiom(sco)
    reasoner.flush()
    assert reasoner.is_entailed(sco) is True, (
        "flush() after add_axiom failed to invalidate — this means upstream "
        "py-whelk has regressed badly."
    )


def test_flush_after_remove_picks_up_axiom_removal():
    """Was xfail-marked under upstream py-whelk 0.4.0 (index_remove was a
    no-op stub). Patched py-whelk records remove_axiom in a pending_remove
    queue and flush() applies it before re-asserting. Now expected to pass;
    the persistent-reasoner path in justification.py relies on this."""
    from pyhornedowl import model
    onto, reasoner, cls = _make_minimal_ontology()
    sco = model.SubClassOf(cls["A"], cls["B"])
    onto.add_axiom(sco)
    reasoner.flush()
    assert reasoner.is_entailed(sco) is True  # state from setup
    onto.remove_axiom(sco)
    reasoner.flush()
    # SHOULD be False (axiom is gone) — currently returns True due to upstream bug.
    assert reasoner.is_entailed(sco) is False
