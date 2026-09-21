"""Display-label quality helpers: humanizing bare IRI local names, and short
tokens for external namespaces bioregistry can't resolve."""
from ontoexplorer.modules.search.indexer import (
    humanize_local_name,
    short_namespace_token,
)


class TestHumanizeLocalName:
    def test_camel_case_splits_into_words(self):
        assert humanize_local_name("AccidentInvolvingMassTransitVehicle") == (
            "Accident Involving Mass Transit Vehicle"
        )

    def test_acronym_boundary_preserved(self):
        assert humanize_local_name("RNAPolymerase") == "RNA Polymerase"

    def test_snake_and_kebab(self):
        assert humanize_local_name("top_data_property") == "top data property"
        assert humanize_local_name("G-protein-coupled") == "G protein coupled"

    def test_single_word_unchanged(self):
        assert humanize_local_name("Mail") == "Mail"

    def test_empty_is_safe(self):
        assert humanize_local_name("") == ""


class TestShortNamespaceToken:
    def test_strips_file_extension(self):
        assert short_namespace_token(
            "http://ontology.cybershare.utep.edu/ELSEWeb/elseweb-data.owl#"
        ) == "elseweb-data"

    def test_skips_version_like_last_segment(self):
        # v1 is a version segment -> fall back to the meaningful one
        assert short_namespace_token("http://purl.org/goodrelations/v1#") == "goodrelations"

    def test_example_ontology_segment(self):
        assert short_namespace_token(
            "http://www.w3.org/TR/2003/PR-owl-guide-20031209/wine#"
        ) == "wine"

    def test_owl_file_namespace(self):
        assert short_namespace_token("http://www.hozo.jp/owl/EXPOApr19.xml/") == "EXPOApr19"

    def test_empty_is_safe(self):
        assert short_namespace_token("") == ""

    # Import-IRI forms (no trailing separator) — used to label owl:imports
    # sources so '.../dogont.owl' reads 'dogont', not 'dogont.owl'.
    def test_import_owl_iri_strips_extension(self):
        assert short_namespace_token("http://elite.polito.it/ontologies/dogont.owl") == "dogont"
        assert short_namespace_token("http://www.loa-cnr.it/ontologies/DUL.owl") == "DUL"

    def test_import_rdf_iri_strips_extension(self):
        assert short_namespace_token(
            "http://iserve.kmi.open.ac.uk/ns/msm/msm-2014-09-03.rdf"
        ) == "msm-2014-09-03"

    def test_import_without_extension_unchanged(self):
        assert short_namespace_token("http://purl.oclc.org/NET/ssnx/ssn") == "ssn"
