"""Tests of arras.model"""
# pylint: disable=missing-function-docstring,redefined-outer-name,protected-access,too-many-lines,line-too-long

import os
import json
import doctest
import logging

import pytest

import arras.model
from arras.oclass import Class, ClassError
from arras.model import Model, ModelError, Object

DATA = os.path.join(os.path.dirname(__file__), "data")

@pytest.fixture(autouse=True)
def registry():
    """Start and end each test with an empty class registry"""
    Class.reset()
    saved = Model.module_loader
    yield
    Model.module_loader = saved
    Class.reset()

def powerflow():
    """Register a few classes as the powerflow module publishes them"""
    node = Class("node", module="powerflow")
    node.publish("phases", "set", keywords={"A":1, "B":2, "C":4, "N":8}, flags="REQUIRED")
    node.publish("voltage_A[V]", "complex")
    node.publish("nominal_voltage[V]", "double")
    node.publish("bustype", "enumeration", keywords={"PQ":0, "PV":1, "SWING":2})
    node.publish("service_status", "bool")
    node.publish("count", "int16")
    node.publish("code", "char8")
    node.publish("start", "timestamp")
    node.publish("notes", "string")
    load = Class("load", module="powerflow")
    load.set_parent("node")
    load.publish("constant_power_A[VA]", "complex")
    link = Class("link", module="powerflow")
    link.publish("from", "object")
    link.publish("to", "object")
    link.publish("mode", "set", keywords={"OPEN":1, "CLOSED":2})

@pytest.fixture
def model():
    powerflow()
    m = Model()
    m.load_module("powerflow")
    return m

def same(a:Model, b:Model) -> bool:
    return {k: dict(v) for k, v in a.objects.items()} == {k: dict(v) for k, v in b.objects.items()}

SAMPLE = """\
// test model
#define VNOM=2401.7771
clock {
    timezone "UTC";
    starttime '2020-01-01 00:00:00';
    stoptime "2020-01-02 00:00:00";
}
#set randomseed=5
module powerflow {
    solver_method NR;
}
class node { double extra[kW]; }
class mytest {
    int32 count;
    char8 tag;
    enumeration {NO=0, YES=1} flag;
    on_init "python:x.y";
}
schedule sched1 {
    * * * * * 1.0;
}
filter f1(z,1h) = 1/(z-0.5);
object powerflow.node {
    name n1; // a comment
    phases ABCN;
    nominal_voltage ${VNOM};
    voltage_A 2401.7771-0.5j kV;
    bustype SWING;
    extra 2 MW;
    object load:..2 {
        phases AN;
        nominal_voltage inherit;
        constant_power_A 1+2j kVA;
    };
}
object link { from n1; to n2; mode "OPEN|CLOSED"; }
object node { name n2; phases "A|B"; nominal_voltage sched1*2+1; latitude 37.5; notes "a // b; \\"c\\""; }
object mytest:10 { count 0x10; tag "abc"; flag YES; }
modify n2.bustype PV;
"""

#
# Documentation
#
def test_doctest():
    result = doctest.testmod(arras.model)
    assert result.failed == 0 and result.attempted > 0

#
# Objects and classes
#
def test_object_basics(model):
    name = model.add_object("node", phases="A")
    assert name == "node:0"
    obj = model["node:0"]
    assert isinstance(obj, Object) and obj.id == 0 and repr(obj) == "<Object node:0>"
    assert obj == {"id": "0", "class": "node", "phases": "A"}
    assert len(model) == 1 and list(model) == ["node:0"] and "node:0" in model
    assert repr(model) == "<Model (1 objects)>"
    with pytest.raises(ModelError, match="object 'x' is not found"):
        _ = model["x"]

def test_find_class(model):
    assert model.find_class("powerflow.node").name == "node"
    assert model.find_class(Class.find("link")).name == "link"
    with pytest.raises(ModelError, match="class 'nothing' is not known"):
        model.find_class("nothing")
    model.add_object("load", "l1")
    assert set(model.classes) >= {"node", "load", "link"}
    assert model.modules == {"powerflow": {"major": 0, "minor": 0}}

def test_add_object_names_and_ids(model):
    assert model.add_object("node", "a", oid=5) == "a"
    assert model.add_object("node") == "node:6"
    assert model.add_object("node", properties={"phases": "B"}) == "node:7"
    with pytest.raises(ModelError, match="already exists"):
        model.add_object("node", "a")
    with pytest.raises(ModelError, match="id 5 is already used"):
        model.add_object("node", "b", oid=5)
    with pytest.raises(ModelError, match="not valid"):
        model.add_object("node", "b", oid=-1)
    for bad in ("", "a b", "a;b", 'a"b'):
        with pytest.raises(ModelError, match="is not valid"):
            model.add_object("node", bad)
    with pytest.raises(ModelError, match="must start with a letter"):
        model.add_object("node", "1abc")
    model.globals.set("relax_naming_rules", "TRUE")
    assert model.add_object("node", "1abc") == "1abc"
    with pytest.raises(ModelError, match="reserved for an unnamed object"):
        model.add_object("node", "link:99")
    with pytest.raises(ModelError, match="class 'nothing' is not known"):
        model.add_object("nothing")

def test_add_objects_atomic(model):
    with pytest.raises(ModelError, match="has no property 'voltage'"):
        model.add_objects([{"class": "node", "name": "a"}, {"class": "node", "name": "b", "voltage": 1}])
    assert not model.objects
    with pytest.raises(ModelError, match="has no class"):
        model.add_objects([{"name": "a"}])
    with pytest.raises(ModelError, match="already exists"):
        model.add_objects([{"class": "node", "name": "a"}, {"class": "node", "name": "a"}])
    with pytest.raises(ModelError, match="object 'zz' is not found"):
        model.add_objects([{"class": "link", "name": "x", "from": "zz"}])
    with pytest.raises(ModelError, match="parent loop"):
        model.add_objects({"a": {"class": "node", "parent": "b"}, "b": {"class": "node", "parent": "a"}})
    assert not model.objects
    names = model.add_objects({"x": {"class": "link", "from": "a", "to": "b"},
        "a": {"class": "node"}, "b": {"class": "node", "parent": "a", "id": "7"}})
    assert names == ["x", "a", "b"]
    assert model["b"].id == 7 and model["x"]["from"] == "a"

def test_numobjs(model):
    node = Class.find("node")
    model.add_object("node", "a")
    assert node.numobjs == 1
    with pytest.raises(ClassError, match="after class has been instantiated"):
        node.add_property("other", "double")
    model.delete_object("a")
    assert node.numobjs == 0

def test_delete(model):
    model.add_objects({"a": {"class": "node"}, "b": {"class": "load", "parent": "a"},
        "c": {"class": "load", "parent": "b"}, "x": {"class": "link", "from": "a", "to": "c"}})
    with pytest.raises(ModelError, match="cannot delete a: referred to by b, x"):
        model.delete_object("a")
    with pytest.raises(ModelError, match="children='bad' is not valid"):
        model.delete_object("a", children="bad")
    with pytest.raises(ModelError, match="object 'q' is not found"):
        model.delete_objects(["c", "q"])
    assert "c" in model
    assert model.delete_objects(["x", "c"]) == ["x", "c"]
    model.add_object("link", "x", **{"from": "a", "to": "b"})
    assert model.delete_object("b", children="orphan") == ["b"]
    assert "to" not in model["x"]
    model.add_objects({"b": {"class": "load", "parent": "a"}, "c": {"class": "load", "parent": "b"}})
    assert model.delete_object("a", children="delete") == ["a", "b", "c"]
    assert list(model.objects) == ["x"] and "from" not in model["x"]
    assert model.delete_objects("x") == ["x"]

def test_rename(model):
    model.add_objects({"a": {"class": "node"}, "b": {"class": "load", "parent": "a"},
        "x": {"class": "link", "from": "a", "to": "b"}})
    objects = model.objects
    model.rename("a", "a2")
    assert model.objects is objects
    model.rename("b", "b")
    assert list(model.objects) == ["a2", "b", "x"]
    assert model["b"]["parent"] == "a2" and model["x"]["from"] == "a2"
    with pytest.raises(ModelError, match="already exists"):
        model.rename("b", "x")
    with pytest.raises(ModelError, match="not found"):
        model.rename("q", "r")

def test_find(model):
    model.add_objects({"n1": {"class": "node", "bustype": "PV"}, "n2": {"class": "node"},
        "l1": {"class": "load", "parent": "n1"}, "x": {"class": "link"}})
    assert model.find("^n") == ["n1", "n2"]
    assert model.find("PV", prop="bustype") == ["n1"]
    assert model.find("^0$", prop="bustype") == ["n2", "l1"]
    assert model.find(".", oclass="node") == ["n1", "n2", "l1"]
    assert model.find("load", prop="class") == ["l1"]
    assert model.find("n1", prop="parent") == ["l1"]
    assert model.find("^0$", prop="id") == ["n1"]
    assert model.find(".", prop="nothing") == []
    import re # pylint: disable=import-outside-toplevel
    assert model.find(re.compile("1$")) == ["n1", "l1"]
    with pytest.raises(ModelError, match="not valid"):
        model.find("(")

#
# Properties
#
def test_get_set(model):
    model.add_objects({"a": {"class": "node", "phases": "A"}, "b": {"class": "load"}})
    assert model.get_property("a", "phases") == "A"
    assert model.get_property("a", "name") == "a"
    assert model.get_property("a", "id") == "0"
    assert model.get_property("a", "bustype") == "0"
    assert model.get_property("a", "parent") is None
    assert model.get_property("b", "voltage_A") == "0+0i"
    with pytest.raises(ModelError, match="has no property 'q'"):
        model.get_property("a", "q")
    assert model.get_properties("a") == {"id": "0", "class": "node", "phases": "A"}
    assert model.get_properties(["a", "b"], ["phases"]) == {"a": {"phases": "A"}, "b": {"phases": "0"}}
    model.set_property("b", "parent", "a")
    model.set_properties(["a", "b"], {"bustype": "PV", "code": "x"})
    assert model.get_property("b", "bustype") == "PV"
    model.set_property("b", "code", None)
    assert "code" not in model["b"]
    with pytest.raises(ModelError, match="has no property 'q'"):
        model.set_property("b", "q", None)
    for key in ("id", "class"):
        with pytest.raises(ModelError, match="cannot be set"):
            model.set_property("a", key, "x")
    with pytest.raises(ModelError, match="use rename"):
        model.set_property("a", "name", "x")
    with pytest.raises(ModelError, match="object 'q' is not found"):
        model.set_property("a", "parent", "q")
    with pytest.raises(ModelError, match="parent loop"):
        model.set_property("a", "parent", "b")
    with pytest.raises(ModelError, match="not a keyword"):
        model.set_properties(["a", "b"], {"code": "y", "bustype": "XX"})
    assert model["a"]["code"] == "x"
    with pytest.raises(ModelError, match="is read-only"):
        model._validate(model["a"], "id", "1")
    model.set_property("a", "on_init", "python:m.f")
    assert model.get_property("a", "on_init") == "python:m.f"
    assert model.get_property("b", "on_commit") is None

@pytest.mark.parametrize("prop,value,expected", [
    ("nominal_voltage", "120", "120"),
    ("nominal_voltage", 120, "120.0"),
    ("nominal_voltage", 1.5, "1.5"),
    ("nominal_voltage", "120 V", "120 V"),
    ("nominal_voltage", "1.2 kV", "1200.0 V"),
    ("nominal_voltage", "1.2kV", "1200.0 V"),
    ("nominal_voltage", "nan", "nan"),
    ("nominal_voltage", "-inf", "-inf"),
    ("nominal_voltage", "random.normal(120,1)", "random.normal(120,1)"),
    ("nominal_voltage", "other.nominal_voltage*2", "other.nominal_voltage*2"),
    ("voltage_A", "1+2j", "1+2j"),
    ("voltage_A", "1-2i V", "1-2i V"),
    ("voltage_A", "1+2j kV", "1000.0+2000.0j V"),
    ("voltage_A", "1+30d kV", "1000.0+30.0d V"),
    ("voltage_A", "2.4", "2.4"),
    ("voltage_A", "nan+0j V", "nan+0j V"),
    ("voltage_A", 3, "3.0+0.0j"),
    ("voltage_A", complex(1, -2), "1.0-2.0j"),
    ("voltage_A", [1, 2], "1.0+2.0j"),
    ("voltage_A", [1, 2, "kV"], "1000.0+2000.0j V"),
    ("voltage_A", {"real": 1, "imag": 2}, "1.0+2.0j"),
    ("voltage_A", {"mag": 1, "ang": 30, "unit": "V"}, "1.0+30.0d V"),
    ("voltage_A", {"mag": 1, "arg": 0.5}, "1.0+0.5r"),
    ("count", "-32768", "-32768"),
    ("count", "0x7fff", "0x7fff"),
    ("count", 12, "12"),
    ("service_status", "true", "TRUE"),
    ("service_status", "0", "FALSE"),
    ("service_status", True, "TRUE"),
    ("bustype", "SWING", "SWING"),
    ("bustype", "7", "7"),
    ("phases", "ABCN", "ABCN"),
    ("phases", "A|N", "A|N"),
    ("phases", ["A", "B"], "A|B"),
    ("phases", "9", "9"),
    ("phases", "", ""),
    ("code", "1234567", "1234567"),
    ("start", "2020-01-01 00:00:00 UTC", "2020-01-01 00:00:00 UTC"),
    ("start", "'2020-01-01 00:00:00'", "2020-01-01 00:00:00"),
    ("start", "2020-01-01 00:00:00 PST", "2020-01-01 00:00:00 PST"),
    ("start", "NEVER", "NEVER"),
    ("start", "3600", "3600"),
    ("notes", "any text at all", "any text at all"),
    ("latitude", "37.5", "37.5"),
    ("latitude", "37N24:30.0", "37N24:30.0"),
    ("rng_state", "4281928187", "4281928187"),
    ("guid", "FFD5863212215B3E8196DD5D8D5E7D", "FFD5863212215B3E8196DD5D8D5E7D"),
    ("flags", "0x100", "0x100"),
    ("clock", "INIT", "INIT"),
    ("groupid", "feeder1", "feeder1"),
])
def test_values_accepted(model, prop, value, expected):
    model.schedules["sched"] = "* * * * * 1"
    model.add_object("node", "a", properties={prop: value})
    assert model.get_property("a", prop) == expected

@pytest.mark.parametrize("prop,value,message", [
    ("nominal_voltage", "abc", "is not a valid double"),
    ("nominal_voltage", "1 kg", "mismatched units"),
    ("nominal_voltage", "1 xyz", "xyz"),
    ("count", "1.5", "is not a valid int16"),
    ("count", "32768", "out of range"),
    ("count", "0x10000", "out of range"),
    ("service_status", "maybe", "is not a valid bool"),
    ("bustype", "XX", "not a keyword"),
    ("phases", "AX", "'X' is not a keyword"),
    ("phases", "A|Q", "'Q' is not a keyword"),
    ("code", "12345678", "longer than 7"),
    ("start", "yesterday", "not a valid timestamp"),
    ("voltage_A", "1+", "is not a valid complex"),
    ("voltage_A", {"x": 1}, "is not a valid complex"),
    ("parent", "a b", "is not a valid object name"),
    ("latitude", "north", "is not a valid double"),
])
def test_values_refused(model, prop, value, message):
    with pytest.raises(ModelError, match=message):
        model.add_object("node", "a", properties={prop: value})

def test_unit_on_unitless(model):
    Class.declare("plain").add_property("x", "double")
    Class.find("plain").add_property("z", "complex")
    with pytest.raises(ModelError, match="unit 'V' given to unitless property"):
        model.add_object("plain", x="1 V")
    with pytest.raises(ModelError, match="unit 'V' given to unitless property"):
        model.add_object("plain", z="1+1j V")

def test_transforms(model):
    with pytest.raises(ModelError, match="not a valid double"):
        model.add_object("node", nominal_voltage="sched*2+1")
    with pytest.raises(ModelError, match="not a valid double"):
        model.add_object("node", nominal_voltage="f1(x)")
    model.schedules["sched"] = "* * * * * 1"
    model.filters["f1"] = "f1(z,1h) = 1/z"
    model.add_object("node", "a", nominal_voltage="sched*2+1")
    model.add_object("node", "b", nominal_voltage="f1(x)")
    assert model["b"]["nominal_voltage"] == "f1(x)"

def test_not_strict(model, caplog):
    model.strict = False
    with caplog.at_level(logging.WARNING):
        model.add_object("node", "a", bustype="XX", count=1.5)
    assert model["a"]["bustype"] == "XX" and model["a"]["count"] == "1.5"
    assert "stored as given" in caplog.text
    with pytest.raises(ModelError, match="has no property"):
        model.add_object("node", "b", nothing=1)

def test_check(model):
    model.add_objects({"a": {"class": "node", "phases": "A"}, "b": {"class": "load", "parent": "a"}})
    assert model.check() == ["b.phases: required property is not set"]
    model["b"]["phases"] = "A"
    model["a"]["parent"] = "b"
    model["b"]["phases"] = "A"
    assert model.check() == ["a.parent: 'b' makes a parent loop", "b.parent: 'a' makes a parent loop"]
    model["a"]["parent"] = "zz"
    assert model.check() == ["a.parent: object 'zz' is not found"]

#
# GLM
#
def test_glm_sample(model):
    model.read_glm(SAMPLE)
    assert list(model.objects) == ["n1", "load:1", "load:2", "link:3", "n2", "mytest:10"]
    assert model["n1"] == {"id": "0", "class": "node", "phases": "ABCN", "nominal_voltage": "2401.7771",
        "voltage_A": "2401777.1-500.0j V", "bustype": "SWING", "extra": "2000.0 kW"}
    assert model["load:2"] == {"id": "2", "class": "load", "parent": "n1", "phases": "AN",
        "nominal_voltage": "2401.7771", "constant_power_A": "1000.0+2000.0j VA"}
    assert model["n2"]["bustype"] == "PV" and model["n2"]["notes"] == 'a // b; "c"'
    assert model["mytest:10"]["count"] == "0x10"
    assert model.schedules == {"sched1": "* * * * * 1.0;"}
    assert model.filters == {"f1": "f1(z,1h) = 1/(z-0.5)"}
    assert model.globals.get("powerflow::solver_method") == "NR"
    assert model.globals.get("randomseed") == "5"
    assert model.globals.get("starttime") == "2020-01-01 00:00:00 UTC"
    assert Class.find("mytest").get_event("on_init") == "python:x.y"
    assert model.check() == []

def test_glm_roundtrip(model, tmp_path):
    model.read_glm(SAMPLE)
    text = model.write_glm()
    assert "#define VNOM=2401.7771\n" in text and "#set randomseed=5\n" in text
    assert "#set randomstate" not in text and "version" not in text
    assert "\tstarttime \"2020-01-01 00:00:00 UTC\";\n" in text
    assert "object powerflow.node:0 {\n\tname \"n1\";\n" in text
    assert "class node {\n\tdouble extra[kW];\n}\n" in text
    assert "\tenumeration {NO=0, YES=1} flag;\n" in text
    other = Model()
    other.read_glm(text)
    assert same(model, other)
    assert other.schedules == model.schedules and other.filters == model.filters
    path = str(tmp_path / "model.glm")
    model.write(path)
    third = Model(path)
    assert same(model, third)

def test_glm_file_and_include(model, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "part.glm").write_text("object node { name inc; }\n")
    (tmp_path / "main.glm").write_text('#include "sub/part.glm"\nobject node { name main; parent inc; }\n')
    model.read_glm(str(tmp_path / "main.glm"))
    assert list(model.objects) == ["inc", "main"]
    (tmp_path / "loop.glm").write_text('#include "loop.glm"\n')
    with pytest.raises(ModelError, match="nesting is too deep"):
        model.read_glm(str(tmp_path / "loop.glm"))
    with pytest.raises(ModelError, match="unable to read"):
        model.read_glm(str(tmp_path / "missing.glm"))
    with pytest.raises(ModelError, match=r"\(text\)\(1\): #include file 'none.glm' is not found"):
        model.read_glm("#include <none.glm>\n")

def test_include_search(model, tmp_path, monkeypatch):
    work, user = tmp_path / "work", tmp_path / "user"
    for folder in (work, user / "include", user / "share", tmp_path / "glpath"):
        folder.mkdir(parents=True)
    (user / "include" / "inc.glm").write_text("object node { name from_include; }\n")
    (user / "share" / "shared.glm").write_text("object node { name from_share; }\n")
    (tmp_path / "glpath" / "old.glm").write_text("object node { name from_glpath; }\n")
    monkeypatch.chdir(work)
    monkeypatch.setenv("ARRAS_USERDIR", str(user))
    monkeypatch.setenv("GLPATH", str(tmp_path / "glpath"))
    model.read_glm("#include <inc.glm>\n#include <shared.glm>\n")
    assert list(model.objects) == ["from_include", "from_share"]
    with pytest.raises(ModelError, match="#include file 'old.glm' is not found"):
        model.read_glm("#include <old.glm>\n")
    (work / "shared.glm").write_text("object node { name from_work; }\n")
    model.read_glm("#include <shared.glm>\n")
    assert "from_work" in model.objects

def test_glm_macros(model, caplog):
    with caplog.at_level(logging.INFO):
        model.read_glm("#print hello ${randomseed}\n#warning careful\n")
    assert "hello 0" in caplog.text and "careful" in caplog.text
    model.read_glm("#ifdef NOTDEFINED\nobject nothing {}\n#else\n#define X=1\n#endif\n"
        "#ifndef X\n#set bad=1\n#endif\n#set mod::x=2\n#set X=\"two\"\n")
    assert model.globals.get("X") == "two" and model.globals.get("mod::x") == "2"
    for text, message in [
            ("#error stop here\n", r"\(text\)\(1\): #error stop here"),
            ("\n#for x in 1 2\n", r"\(text\)\(2\): macro '#for' is not supported"),
            ("#set nothing=1\n", "strict naming"),
            ("#set nothing\n", "not formatted as NAME=VALUE"),
            ("#else\n", "#else without"),
            ("#endif\n", "#endif without"),
            ("#ifdef X\n", "missing #endif"),
            ("object node { name ${undefined}; }\n", "global 'undefined' is not defined"),
            ]:
        with pytest.raises(ModelError, match=message):
            model.read_glm(text)

def test_glm_values(model):
    model.read_glm('object node {\n name a;\n notes """line 1\nline \\t2 "q" ""\n"""; code {x};\n}\n'
        'object node { name b; parent a; code inherit; notes @a; }\n'
        'object node:20..21 { phases A; }\nobject node { name c; parent a; root; }\n')
    assert model["a"]["notes"] == 'line 1\nline \t2 "q" ""\n'
    assert model["a"]["code"] == "{x}"
    assert model["b"]["code"] == "{x}" and model["b"]["notes"] == model["a"]["notes"]
    assert "node:20" in model and "node:21" in model and "parent" not in model["c"]
    other = Model()
    other.read_glm(model.write_glm())
    assert same(model, other)

@pytest.mark.parametrize("text,message", [
    ("foo bar;", r"\(text\)\(1\): 'foo' is not a supported GLM directive"),
    ("\n123;", r"\(text\)\(2\): '123' is not a supported GLM directive"),
    ("object node { name a }", "missing ';'"),
    ("object node { name a;\n code x\n; }", r"\(text\)\(2\): missing ';' at end of value"),
    ("object node { name a;", "expected property name"),
    ("object node { notes \"\"\"abc; }", "unterminated multi-line"),
    ("object node { 9 x; }", "expected property name"),
    ("object node:x { }", "is not a valid object class and id"),
    ("object nothing { }", "class 'nothing' is not known"),
    ("object node ;", "expected '{'"),
    ("object node { name a; }\nobject node { name a; }", r"\(text\)\(2\): an object named 'a' already exists"),
    ("object node { nothing 1; }", r"\(text\)\(1\): class 'node' has no property 'nothing'"),
    ("object node { code inherit; }", "cannot inherit code"),
    ("object node { code @zz; }", "object 'zz' is not found"),
    ("object node { parent zz; }", "object 'zz' is not found"),
    ("object node:1 { }\nobject node:1 { }", "id 1 is already used"),
    ("clock { starttime nonsense; }", "clock starttime"),
    ("clock { ; }", "expected clock property"),
    ("module ;", "expected module name"),
    ("module powerflow { major x; }", "module powerflow major"),
    ("module powerflow { ; }", "expected module powerflow property"),
    ("module powerflow x", "to open module"),
    ("class { }", "expected class name"),
    ("class t : public nothing { }", "undefined class"),
    ("class t { int32 x }", "missing ';'"),
    ("class t { function f(); }", "not a supported class member"),
    ("class t { enumeration {A} e; }", "not formatted as NAME=VALUE"),
    ("class t { double x[nothing]; }", "unit 'nothing' is not found"),
    ("class t { parent nothing; }", "not found"),
    ("class t ;", "to open class"),
    ("global x;", "not formatted as TYPE NAME"),
    ("global int32 x abc;", "global x"),
    ("modify nothing.x 1;", "does not name an object property"),
    ("object node { name a; }\nmodify a.count abc;", "not a valid int16"),
    ("schedule { }", "expected schedule name"),
    ("schedule s { ", "missing '}'"),
    ("filter 9;", "not formatted as NAME"),
])
def test_glm_errors(model, text, message):
    with pytest.raises(ModelError, match=message):
        model.read_glm(text + "\n")

def test_glm_directives(model):
    model.read_glm('module powerflow { major 4; minor 3; class meter; gamma 1; }\nmodule other;\n'
        'global double g1[MW] 5 MW;\nglobal int32 randomseed 9;\n'
        'class t : public node { int32 x; parent node; on_commit "python:a.b"; }\n'
        'clock { tz "UTC"; }\n;\nobject t { phases A; x 2; }\n')
    assert model.modules["powerflow"] == {"major": 4, "minor": 3}
    assert "other" in model.modules
    assert Class.find("meter", module="powerflow") is not None
    assert model.globals.get("powerflow::gamma") == "1"
    assert model.globals.get("g1") == "+5 MW" and model.globals.get("randomseed") == "9"
    assert Class.find("t").parent is Class.find("node")
    model.read_glm("module powerflow { gamma 2; }\n")
    assert model.globals.get("powerflow::gamma") == "2"
    text = model.write_glm()
    assert "module other;\n" in text and "\tgamma \"2\";\n" in text
    assert "class t : public node {\n\tint32 x;\n\ton_commit \"python:a.b\";\n}\n" in text
    assert "#define g1=+5 MW\n" in text

def test_module_loader():
    prop = {"type": "double", "unit": "MW", "access": "PUBLIC"}
    data = {"application": "gridlabd", "classes": {"gen.unit": {"P": prop}}}
    calls = []
    def loader(name):
        calls.append(name)
        return data if name == "gen" else None
    Model.module_loader = loader
    m = Model()
    m.read_glm("module gen;\nmodule other;\nobject unit { P 1 kW; }\n")
    assert calls == ["gen", "other"]
    assert m["unit:0"]["P"] == "0.001 MW"

#
# JSON
#
def test_json_roundtrip(model, tmp_path):
    model.read_glm(SAMPLE)
    data = model.to_json()
    assert data["application"] == "gridlabd" and data["version"].count(".") == 2
    assert data["modules"] == {"powerflow": {"major": "0", "minor": "0"}}
    assert data["header"]["parent"] == {"type": "object", "access": "PROTECTED"}
    assert data["classes"]["node"]["phases"] == {"type": "set", "access": "PUBLIC",
        "keywords": {"A": "0x1", "B": "0x2", "C": "0x4", "N": "0x8"}, "flags": "CHARSET|REQUIRED"}
    assert data["classes"]["load"]["parent"] == "node"
    assert data["classes"]["node"]["extra"]["flags"] == "EXTENDED"
    assert data["globals"]["randomseed"] == {"type": "int32", "access": "PUBLIC", "value": "5"}
    assert data["globals"]["glm_save_options"]["keywords"]["MINIMAL"] == "0xf"
    assert data["objects"]["load:1"]["parent"] == "n1"
    assert data["filters"] == {"f1": "f1(z,1h) = 1/(z-0.5)"}
    path = str(tmp_path / "model.json")
    model.write(path)
    other = Model(path)
    assert other.to_json()["objects"] == data["objects"]
    assert other["load:1"]["voltage_A"] == "0+0i"
    Class.reset()
    fresh = Model()
    fresh.read_json(json.dumps(data))
    assert fresh.to_json()["objects"] == data["objects"]
    assert Class.find("node").find_property("extra").is_extended
    assert fresh.write_json(indent=None) == json.dumps(fresh.to_json()) + "\n"

def test_json_header_aliases(model):
    model.add_object("node", "a", in_svc="2020-01-01 00:00:00 UTC", out_svc="NEVER")
    data = model.to_json()["objects"]["a"]
    assert data["in"] == "2020-01-01 00:00:00 UTC" and data["out"] == "NEVER"
    other = Model()
    other.read_json(model.to_json())
    assert other["a"]["in_svc"] == "2020-01-01 00:00:00 UTC"
    assert other.get_property("a", "in") == "2020-01-01 00:00:00 UTC"

def test_load_classes():
    m = Model()
    data = {"application": "gridlabd", "modules": {"pf": {"major": "4", "minor": "3"}}, "classes": {
        "pf.child": {"parent": "base", "x": {"type": "int32", "access": "PUBLIC"}},
        "pf.base": {"trl": "5", "v": {"type": "complex", "unit": "V", "access": "RW", "flags": "OUTPUT|BOGUS",
            "default": "1+0j", "description": "voltage"},
            "e": {"type": "enumeration", "access": "PUBLIC", "keywords": {"A": "0x0", "B": 1}}},
        "rt": {"y": {"type": "double", "access": "PUBLIC"}}}}
    classes = m.load_classes(data)
    assert [x.name for x in classes] == ["child", "base", "rt"]
    base = Class.find("pf.base")
    assert base.trl == 5 and Class.find("child").parent is base and Class.find("rt").module is None
    prop = base.find_property("v")
    assert prop.access == "PUBLIC" and prop.has_flag("OUTPUT") and prop.default == "1+0j" and prop.description == "voltage"
    assert base.find_property("e").keywords == {"A": 0, "B": 1}
    assert m.modules["pf"] == {"major": 4, "minor": 3}
    assert m.load_classes(data) == classes
    assert m.to_json()["classes"]["base"]["v"] == {"type": "complex", "access": "PUBLIC", "flags": "OUTPUT",
        "unit": "V", "default": "1+0j", "description": "voltage"}
    with pytest.raises(ModelError, match="is defined as type int32, not double"):
        m.load_classes({"application": "gridlabd", "classes": {"pf.child": {"x": {"type": "double"}}}})
    with pytest.raises(ModelError, match="class 'zz': parent property class name 'nothing'"):
        m.load_classes({"application": "gridlabd", "classes": {"pf.zz": {"parent": "nothing"}}})
    with pytest.raises(ModelError, match="class 'bad.x.y'"):
        m.load_classes({"application": "gridlabd", "classes": {"bad.x.y": {}}})
    with pytest.raises(ModelError, match="unit 'nothing' is not recognized"):
        m.load_classes({"application": "gridlabd",
            "classes": {"pf.w": {"z": {"type": "double", "unit": "nothing"}}}})

def test_json_errors(tmp_path):
    m = Model()
    with pytest.raises(ModelError, match="not from gridlabd"):
        m.read_json({"application": "other"})
    with pytest.raises(ModelError, match="unable to read JSON"):
        m.read_json("{not json")
    with pytest.raises(ModelError, match="unable to read JSON"):
        m.read_json(str(tmp_path / "missing.json"))
    with pytest.raises(ModelError, match="class 'nothing' is not known"):
        m.read_json({"application": "gridlabd", "objects": {"a": {"id": "0", "class": "nothing"}}})
    with pytest.raises(ModelError, match="file type '.txt' is not supported"):
        m.read("model.txt")
    with pytest.raises(ModelError, match="file type '.txt' is not supported"):
        m.write("model.txt")

def test_json_globals(caplog):
    m = Model()
    with caplog.at_level(logging.WARNING):
        m.read_json({"application": "gridlabd", "globals": {
            "mod::level": {"type": "double", "access": "PUBLIC", "value": "+5 MW"},
            "mod::mode": {"type": "enumeration", "keywords": {"A": "0x0", "B": "0x1"},
                "access": "PUBLIC", "value": "B"},
            "mod::odd": {"type": "nonsense", "access": "WEIRD", "value": "x"},
            "randomseed": {"type": "int32", "access": "PUBLIC", "value": "abc"},
            "dateformat": {"type": "enumeration", "access": "PUBLIC", "value": "ISO"}}})
    assert m.globals.get("mod::level") == "+5 MW" and m.globals.get("mod::mode") == "B"
    assert m.globals.find("mod::odd").ptype == "char1024" and m.globals.find("mod::odd").access == "PUBLIC"
    assert "global 'randomseed' not set" in caplog.text

def test_gridlabd_json():
    """JSON written by gridlabd 4.3.11 (see data/README.md)"""
    path = os.path.join(DATA, "case14.json")
    m = Model(path)
    assert len(m.objects) == 44 and not m.check()
    assert m.modules["pypower"] == {"major": 4, "minor": 3}
    assert m.find(".", oclass="bus")[:2] == ["pp_bus_1", "pp_bus_2"]
    assert m.get_property("pp_bus_1", "type") == "REF"
    gen = m.find(".", prop="class")
    assert gen == list(m.objects)
    with open(path, encoding="utf-8") as fh:
        original = json.load(fh)
    data = m.to_json()
    for name, values in original["objects"].items():
        assert {key: value for key, value in values.items() if value != ""} == \
            {key: value for key, value in data["objects"][name].items() if value != ""}, name
    Class.reset()
    again = Model()
    again.read_json(data)
    assert same(m, again)
    third = Model()
    third.read_glm(m.write_glm())
    assert same(m, third)

def test_glm_more(model, tmp_path):
    (tmp_path / "part.glm").write_text("object node { name inc; }\n")
    model.read_glm(f"#include {tmp_path / 'part.glm'}\n"
        "schedule s2 {\n  weekday {\n    * * * * 1-5 1;\n  }\n  weekend {\n    * * * * 0,6 2;\n  }\n}\n"
        'global char32 quoted "a\\"b;c";\n')
    assert "inc" in model
    assert model.schedules["s2"].startswith("weekday {\n  * * * * 1-5 1;\n}")
    assert model.globals.get("quoted") == 'a"b;c'
    with pytest.raises(ModelError, match="missing ';' at end of value"):
        model.read_glm("object node { code x")

def test_module_of_class():
    powerflow()
    m = Model()
    m.add_object("powerflow.load", "l")
    assert m.modules == {"powerflow": {"major": 0, "minor": 0}}
    assert list(m.classes) == ["load", "node"]

def test_json_filters():
    m = Model()
    m.read_json({"application": "gridlabd", "filters": {"lp": {"domain": "z", "timestep": 3600,
        "timeskew": 0, "minimum": -1, "numerator": [0.5, 0.5], "denominator": [1, -0.5, 0.25]}}})
    text = m.write_glm()
    assert "filter lp(z,3600,0,minimum=-1) = (0.5+0.5z) / (1-0.5z+0.25z^2);\n" in text
    other = Model()
    other.read_glm(text)
    assert other.filters["lp"] == "lp(z,3600,0,minimum=-1) = (0.5+0.5z) / (1-0.5z+0.25z^2)"

def test_json_defaults(model):
    Class.find("node").publish("hidden_x", "double", access="PROTECTED")
    Class.find("node").publish("target", "object")
    Class.find("node").publish("custom[V]", "double", default="120 V")
    model.add_object("load", "l1", phases="AN", constant_power_A="1+1j VA")
    model.set_property("l1", "on_init", "python:a.b")
    item = model.to_json()["objects"]["l1"]
    assert list(item)[:5] == ["id", "class", "phases", "constant_power_A", "on_init"]
    assert list(item)[5:] == ["voltage_A", "nominal_voltage", "bustype", "service_status",
        "count", "code", "start", "notes", "custom"]
    Class.declare("rt").add_property("y", "int32")
    model.add_object("rt", "r")
    assert model.to_json()["objects"]["r"]["y"] == "0" and model.get_property("r", "y") == "0"
    assert item["voltage_A"] == "0+0i" and item["bustype"] == "0" and item["custom"] == "120 V"
    assert "hidden_x" not in item and "target" not in item
    model.globals.set("filesave_options", "ALLMINIMAL")
    assert model.to_json()["objects"]["l1"] == {"id": "0", "class": "load", "phases": "AN",
        "constant_power_A": "1+1j VA", "on_init": "python:a.b"}
