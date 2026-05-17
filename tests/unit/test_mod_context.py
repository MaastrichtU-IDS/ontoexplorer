from ontoexplorer.modules.mod.context import MOD_CONTEXT


def test_context_has_required_prefixes():
    ctx = MOD_CONTEXT["@context"]
    for prefix in ["dcterms", "dcat", "mod", "owl", "foaf", "skos", "void", "rdf", "rdfs", "xsd", "vann", "schema", "hydra", "sd"]:
        assert prefix in ctx, f"Missing prefix: {prefix}"


def test_mod_namespace():
    assert MOD_CONTEXT["@context"]["mod"] == "https://w3id.org/mod#"


def test_dcat_namespace():
    assert MOD_CONTEXT["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"
