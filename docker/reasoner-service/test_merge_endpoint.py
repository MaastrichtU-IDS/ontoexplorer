from fastapi.testclient import TestClient
import main

def test_merge_folds_ofn_into_ntriples():
    c = TestClient(main.app)
    ofn = ("Declaration(Class(<http://x#DemoRole>))\n"
           "SubClassOf(<http://x#DemoRole> <https://w3id.org/sulo/Role>)")
    base = "<http://x#A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> ."
    r = c.post("/merge", json={"ntriples": base, "ofn": ofn})
    assert r.status_code == 200
    nt = r.json()["ntriples"]
    assert "http://x#A" in nt and "http://x#DemoRole" in nt

def test_merge_empty_ofn_returns_base():
    c = TestClient(main.app)
    r = c.post("/merge", json={"ntriples": "<a> <b> <c> .", "ofn": ""})
    assert r.status_code == 200 and "<a>" in r.json()["ntriples"]

def test_merge_bad_ofn_422():
    c = TestClient(main.app)
    r = c.post("/merge", json={"ntriples": "", "ofn": "not valid ofn ((("})
    assert r.status_code == 422
