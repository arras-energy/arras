"""Tests of arras.oclass"""

import doctest
import logging

import pytest

import arras.oclass
from arras.oclass import Class, ClassError, Property, PASSCONFIG, \
    PROPERTY_TYPES, FLAGS, RESERVED, GSO_NOINTERNALS, GSO_NOMACROS
from arras.units import Units, UnitsError

@pytest.fixture(autouse=True)
def fixture_reset():
    """Start each test with an empty class registry"""
    Class.reset()
    yield
    Class.reset()

@pytest.fixture(name="powerflow")
def fixture_powerflow():
    """A small module class hierarchy: node <- load"""
    node = Class("node", module="powerflow", passconfig="PRETOPDOWN|BOTTOMUP|POSTTOPDOWN")
    node.publish("voltage_A[V]", "complex", description="bus voltage, phase A")
    node.publish("bustype", "enumeration", keywords={"PQ":0, "PV":1, "SWING":2})
    load = Class("load", module="powerflow", passconfig="PRETOPDOWN|BOTTOMUP|POSTTOPDOWN")
    load.set_parent("node")
    load.publish("constant_power_A[VA]", "complex", flags="REQUIRED")
    return node, load

#
# Tables
#
def test_property_types():
    names = list(PROPERTY_TYPES)
    assert len(names) == 25
    assert names[:4] == ["double", "complex", "enumeration", "set"]
    assert names[-2:] == ["string", "python"]
    assert PROPERTY_TYPES["bool"] == ("string", "FALSE")
    assert PROPERTY_TYPES["object"] == ("string", None)
    assert "void" not in PROPERTY_TYPES

def test_passconfig_bits():
    assert PASSCONFIG["PRETOPDOWN"] | PASSCONFIG["BOTTOMUP"] | PASSCONFIG["POSTTOPDOWN"] == 7
    assert PASSCONFIG["OBSERVER"] == 0x0400

#
# Registration
#
def test_register():
    a = Class("a")
    b = Class("b", module="m", passconfig=PASSCONFIG["BOTTOMUP"])
    assert (a.id, b.id) == (0, 1)
    assert Class.registry == [a, b]
    assert a.module is None and b.module == "m"
    assert b.has_pass("BOTTOMUP") and not b.has_pass("PRETOPDOWN")
    assert repr(a) == "<Class a>"
    assert a.numobjs == 0 and a.trl == 0

def test_register_passconfig_string():
    c = Class("c", passconfig="PRETOPDOWN | POSTTOPDOWN")
    assert c.passconfig == 5
    assert Class("d", passconfig=None).passconfig == 0
    with pytest.raises(ClassError, match="'BAD' is not a valid passconfig"):
        Class("e", passconfig="BAD")

def test_register_duplicate():
    Class("x", module="m")
    with pytest.raises(ClassError, match="already registered by module m"):
        Class("x", module="m")
    other = Class("x", module="n")
    glm = Class("x")
    assert (other.id, glm.id) == (1, 2)
    with pytest.raises(ClassError, match="already registered"):
        Class("x")

@pytest.mark.parametrize("name", ["", "a.b", None, "x"*64])
def test_register_bad_name(name):
    with pytest.raises(ClassError):
        Class(name)

def test_register_long_name_ok():
    assert Class("x"*63).name == "x"*63

def test_reset():
    Class("a")
    Class.reset()
    assert not Class.registry
    assert Class("b").id == 0

def test_find():
    a = Class("x", module="m")
    b = Class("x", module="n")
    c = Class("y")
    assert Class.find("x") is a
    assert Class.find("x", module="n") is b
    assert Class.find("n.x") is b
    assert Class.find("m.y") is None
    assert Class.find("y") is c
    assert Class.find("z") is None

#
# GLM class blocks
#
def test_declare_new_and_existing():
    a = Class.declare("test")
    assert a.module is None and a.parent is None
    assert Class.declare("test") is a

def test_declare_inherit():
    base = Class.declare("base")
    for inherit in ("public", "protected", "private"):
        child = Class.declare(f"child_{inherit}", "base", inherit)
        assert child.parent is base and child.inherit == inherit
    obj = Class.declare("child_obj", base)
    assert obj.parent is base

def test_declare_inherit_errors():
    Class.declare("base")
    with pytest.raises(ClassError, match="missing inheritance qualifier"):
        Class.declare("child", "base", "friend")
    with pytest.raises(ClassError, match="inherits from undefined class nothing"):
        Class.declare("child", "nothing")

def test_declare_existing_keeps_parent():
    base = Class.declare("base")
    child = Class.declare("child")
    assert Class.declare("child", base) is child
    assert child.parent is None

#
# Inheritance
#
def test_set_parent_glm():
    base = Class("base", module="m")
    child = Class.declare("child")
    child.set_parent("base")
    assert child.parent is base
    child.set_parent(Class.declare("other"))
    assert child.parent.name == "other"
    with pytest.raises(ClassError, match="parent class 'nothing' not found"):
        child.set_parent("nothing")

def test_set_parent_module(powerflow):
    node, load = powerflow
    assert load.parent is node
    with pytest.raises(ClassError, match="already inherits properties from class node"):
        load.set_parent("node")
    Class("other", module="residential")
    house = Class("house", module="powerflow")
    with pytest.raises(ClassError, match="'other' is not defined"):
        house.set_parent("other")
    with pytest.raises(ClassError, match="'other' is not defined"):
        house.set_parent(Class.find("other"))

def test_set_parent_loop():
    a = Class.declare("a")
    b = Class.declare("b", "a")
    with pytest.raises(ClassError, match="inheritance loop"):
        a.set_parent("b")
    with pytest.raises(ClassError, match="inheritance loop"):
        a.set_parent(a)
    assert a.parent is None and b.parent is a

def test_set_parent_override_warnings(caplog):
    Class("parent", module="m", passconfig="PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT")
    child = Class("child", module="m", passconfig="BOTTOMUP")
    with caplog.at_level(logging.WARNING):
        child.set_parent("parent")
    text = caplog.text
    assert "PRETOPDOWN sync behavior" in text
    assert "POSTTOPDOWN sync behavior" in text
    assert "BOTTOMUP sync behavior" not in text
    assert "does not assert UNSAFE_OVERRIDE_OMIT" in text

def test_set_parent_override_allowed(caplog):
    Class("parent", module="m", passconfig="BOTTOMUP|UNSAFE_OVERRIDE_OMIT")
    child = Class("child", module="m", passconfig="PARENT_OVERRIDE_OMIT")
    with caplog.at_level(logging.WARNING):
        child.set_parent("parent")
    assert caplog.text == ""

def test_isa(powerflow):
    node, load = powerflow
    assert load.isa("load") and load.isa("node")
    assert not node.isa("load")

#
# Properties
#
def test_publish(powerflow):
    node, load = powerflow
    prop = node.find_property("voltage_A")
    assert isinstance(prop, Property)
    assert (prop.oclass, prop.ptype, prop.unit, prop.default) == (node, "complex", "V", "0+0i")
    assert prop.description == "bus voltage, phase A"
    assert not prop.is_extended and prop.access == "PUBLIC"
    assert load["constant_power_A"].has_flag("REQUIRED")
    assert list(node.find_property("bustype").keywords) == ["PQ", "PV", "SWING"]

def test_publish_options():
    c = Class("c", module="m")
    p = c.publish("x", "double", unit="MW", access="REFERENCE",
        flags=FLAGS["OUTPUT"]|FLAGS["DYNAMIC"], default="1.5")
    assert (p.unit, p.access, p.default) == ("MW", "REFERENCE", "1.5")
    assert p.has_flag("OUTPUT") and p.has_flag("DYNAMIC")
    assert c.publish("y[kW]", "double", unit="kW").unit == "kW"
    assert c.publish("s", "char32").default == ""

@pytest.mark.parametrize("name", RESERVED)
def test_publish_reserved(name):
    with pytest.raises(ClassError, match="conflicts with built-in property"):
        Class("c", module="m").publish(name, "double")

def test_publish_errors():
    c = Class("c", module="m")
    c.publish("x", "double")
    with pytest.raises(ClassError, match="already defined"):
        c.publish("x", "double")
    with pytest.raises(ClassError, match="not recognized"):
        c.publish("y", "void")
    with pytest.raises(ClassError, match="keys not permitted"):
        c.publish("y", "int32", keywords={"A":1})
    with pytest.raises(ClassError, match="access 'OPEN' is not valid"):
        c.publish("y", "int32", access="OPEN")
    with pytest.raises(ClassError, match="'NONE' is not a valid property flag"):
        c.publish("y", "int32", flags="NONE")
    with pytest.raises(ClassError, match="too big"):
        c.publish("y"*64, "int32")
    with pytest.raises(ClassError, match="not valid"):
        c.publish("", "int32")
    with pytest.raises(ClassError, match="differs from unit"):
        c.publish("y[W]", "double", unit="kW")

def test_add_property():
    c = Class.declare("test")
    x = c.add_property("x", "double", unit="MW")
    assert x.is_extended and x.unit == "MW" and x.default is None
    assert c.add_property("x", "double") is x
    assert c.add_property("y[kW]", "complex").unit == "kW"
    e = c.add_property("mode", "enumeration", keywords={"OFF":0, "ON":1})
    assert e.keywords == {"OFF":0, "ON":1}
    assert c.add_property("name", "char32").name == "name"
    assert c.extended_count() == 4

def test_add_property_inherited(powerflow):
    _, load = powerflow
    child = Class.declare("child")
    child.set_parent(load)
    assert child.add_property("voltage_A", "complex").oclass.name == "node"
    with pytest.raises(ClassError, match="defined in class child as type complex"):
        child.add_property("voltage_A", "double")

def test_add_property_errors():
    c = Class.declare("test")
    with pytest.raises(ClassError, match="property type void is not recognized"):
        c.add_property("x", "void")
    with pytest.raises(ClassError, match="units not permitted for type int32"):
        c.add_property("x", "int32", unit="W")
    with pytest.raises(ClassError, match="keys not permitted for type int32"):
        c.add_property("x", "int32", keywords={"A":1})
    c.numobjs = 1
    with pytest.raises(ClassError, match="after class has been instantiated"):
        c.add_property("x", "int32")

def test_find_property(powerflow):
    node, load = powerflow
    assert load.find_property("constant_power_A").oclass is load
    assert load.find_property("bustype").oclass is node
    assert load.find_property("nothing") is None
    assert node.find_property("constant_power_A") is None
    assert "bustype" in load and "nothing" not in load
    with pytest.raises(KeyError):
        _ = load["nothing"]

def test_properties_order(powerflow):
    node, load = powerflow
    assert [p.name for p in load.properties()] == ["constant_power_A"]
    assert list(load) == ["constant_power_A", "voltage_A", "bustype"]
    assert len(load) == 3 and len(node) == 2

def test_deprecated_notice(caplog):
    c = Class("c", module="m")
    c.publish("old", "double", flags="DEPRECATED")
    with caplog.at_level(logging.WARNING):
        c.find_property("old")
        c.find_property("old")
    assert caplog.text.count("property 'old' is deprecated") == 1

def test_define_keyword():
    c = Class("c", module="m")
    c.publish("mode", "enumeration")
    c.define_keyword("mode", "OFF", 0)
    c.define_keyword("mode", "ON", 1)
    assert list(c["mode"].keywords) == ["ON", "OFF"]
    c.define_keyword("mode", "OFF", 2)
    assert c["mode"].keywords == {"OFF":2, "ON":1}

def test_define_keyword_charset():
    c = Class("c", module="m")
    c.publish("phases", "set")
    c.define_keyword("phases", "A", 1)
    c.define_keyword("phases", "B", 2)
    assert c["phases"].has_flag("CHARSET")
    c.define_keyword("phases", "AB", 3)
    assert not c["phases"].has_flag("CHARSET")
    assert c.publish("p2", "set", keywords={"A":1, "B":2}).has_flag("CHARSET")
    assert not c.publish("p3", "set", keywords={"A":1, "BC":2}).has_flag("CHARSET")

def test_define_keyword_errors():
    c = Class("c", module="m")
    c.publish("x", "double")
    with pytest.raises(ClassError, match="not found"):
        c.define_keyword("y", "A", 1)
    with pytest.raises(ClassError, match="not an enumeration or set"):
        c.define_keyword("x", "A", 1)

def test_property_hidden():
    c = Class("c", module="m")
    c.publish("secret", "double", access="HIDDEN")
    c.publish("ref", "double", access="REFERENCE")
    assert c["secret"].is_hidden and not c["ref"].is_hidden
    assert "secret" not in c.modhelp()

def test_property_repr(powerflow):
    node, _ = powerflow
    assert repr(node["voltage_A"]) == "<Property node.voltage_A:complex[V]>"
    assert repr(node["bustype"]) == "<Property node.bustype:enumeration>"

def test_property_bad_type():
    with pytest.raises(ClassError, match="not recognized"):
        Property(Class("c"), "x", "void")

#
# Units
#
def test_units_shared():
    units = Class.get_units()
    assert isinstance(units, Units)
    assert Class.get_units() is units
    Class.reset()
    assert Class.units is units

def test_add_property_unit_spec():
    c = Class.declare("test")
    x = c.add_property("x", "double", unit="MW")
    assert x.unit_spec.name == "MW"
    assert x.unit_spec.compatible(Class.get_units().find("W"))
    assert not x.unit_spec.compatible(Class.get_units().find("m"))
    assert c.add_property("v", "complex", unit="kV").unit_spec.name == "kV"
    assert c.add_property("r", "randomvar", unit="m/s").unit_spec.name == "m/s"
    assert c.add_property("n", "double").unit_spec is None

def test_add_property_bad_unit():
    c = Class.declare("test")
    with pytest.raises(ClassError, match="unit 'xyz' is not found"):
        c.add_property("x", "double", unit="xyz")
    with pytest.raises(ClassError, match="unit 'xyz' is not found"):
        c.add_property("x[xyz]", "double")
    assert c.find_property("x") is None

def test_publish_unit_spec(powerflow):
    node, load = powerflow
    assert node["voltage_A"].unit_spec.name == "V"
    assert load["constant_power_A"].unit_spec.compatible(Class.get_units().find("W"))
    c = Class("c", module="m")
    assert c.publish("count", "int32", unit="W").unit_spec.name == "W"

def test_publish_bad_unit():
    c = Class("c", module="m")
    with pytest.raises(ClassError, match="property 'x' unit 'xyz' is not recognized"):
        c.publish("x[xyz]", "double")
    with pytest.raises(ClassError, match="property 'x' unit 'xyz' is not recognized"):
        c.publish("x", "double", unit="xyz")
    with pytest.raises(ClassError, match="cannot have unit 'W' because it is not a double or complex value"):
        c.publish("x[W]", "int32")
    assert c.find_property("x") is None

def test_custom_units(tmp_path):
    path = tmp_path / "unitfile.txt"
    path.write_text("m=0,0,0,0,0,0,1,0,6\nfurlong=201.168 m\n")
    Class.units = Units(str(path))
    try:
        c = Class.declare("test")
        assert c.add_property("x", "double", unit="furlong").unit_spec.a == pytest.approx(201.168)
        with pytest.raises(ClassError, match="unit 'W' is not found"):
            c.add_property("y", "double", unit="W")
    finally:
        Class.units = None

def test_units_load_error(monkeypatch):
    def fail(*args, **kwargs):
        raise UnitsError("no unit file")
    monkeypatch.setattr(arras.oclass, "Units", fail)
    monkeypatch.setattr(Class, "units", None)
    with pytest.raises(ClassError, match="unable to load units"):
        Class.declare("test").add_property("x", "double", unit="W")

#
# Functions and events
#
def test_functions():
    c = Class("c", module="m")
    def func(*args):
        return len(args)
    c.define_function("count", func)
    assert c.get_function("count") is func
    assert c.get_function("nothing") is None
    with pytest.raises(ClassError, match="has already been defined"):
        c.define_function("count", func)
    with pytest.raises(ClassError, match="not callable"):
        c.define_function("other", 1)
    child = Class("child", module="m")
    child.set_parent(c)
    assert child.get_function("count") is None

def test_events():
    c = Class.declare("test")
    c.set_event("on_init", "python:mod.init")
    c.set_event("commit", "/bin/true")
    assert c.events == {"init":"python:mod.init", "commit":"/bin/true"}
    assert c.get_event("on_commit") == "/bin/true"
    assert c.get_event("sync") is None
    with pytest.raises(ClassError, match="event 'on_bad' is not valid"):
        c.set_event("on_bad", "x")

#
# Output
#
def test_modhelp(powerflow):
    _, load = powerflow
    load.define_function("f", print)
    load.publish("status", "set", keywords={"A":1, "B":2}, flags="OUTPUT|DYNAMIC", description="status")
    load.publish("big", "enumeration", keywords={"NEG":-1})
    assert load.modhelp() == (
        "class load {\n"
        "\tparent node;\n"
        "\tclass node {\n"
        "\t\tcomplex voltage_A[V]; // bus voltage, phase A\n"
        "\t\tenumeration {PQ=0, PV=1, SWING=2} bustype;\n"
        "\t}\n"
        "\n"
        "\tfunction f();\n"
        "\tcomplex constant_power_A[VA]; // (REQUIRED) \n"
        "\tset {A=1, B=2} status; // (OUTPUT,DYNAMIC) status\n"
        "\tenumeration {NEG=18446744073709551615} big;\n"
        "}\n"
        "\n")

def test_to_glm(powerflow):
    _, load = powerflow
    load.define_function("f", print)
    load.publish("a.b", "double")
    load.add_property("user", "double")
    assert load.to_glm() == "class load {\n}\n"
    assert load.to_glm(GSO_NOMACROS) == (
        "class load {\n"
        "#ifdef INCLUDE_PARENT_CLASS\n\tparent node;\n#endif\n"
        "#ifdef INCLUDE_FUNCTIONS\n\tfunction f();\n#endif\n"
        "\tcomplex constant_power_A;\n"
        "#ifdef INCLUDE_DOTTED_PROPERTIES\n\tdouble a.b;\n#endif\n"
        "\tdouble user;\n"
        "}\n")
    assert load.to_glm(GSO_NOMACROS|GSO_NOINTERNALS) == "class load {\n\tdouble user;\n}\n"

def test_saveall(powerflow):
    node, _ = powerflow
    Class.declare("test").add_property("x", "double")
    text = Class.saveall(GSO_NOINTERNALS|GSO_NOMACROS)
    assert text == ("\n////////////////////////////////////////////////////////\n// classes\n"
        "class test {\n\tdouble x;\n}\n")
    assert "class node" not in text
    assert node.to_glm(GSO_NOINTERNALS) == ""
    assert Class.saveall().count("class ") == 3

def test_to_xml(powerflow):
    _, load = powerflow
    load.define_function("f", print)
    assert load.to_xml() == (
        "\t\t<class name=\"load\">\n"
        "\t\t<parent>node</parent>\n"
        "\t\t<function>f</function>\n"
        "\t\t\t<property type=\"complex\">constant_power_A</property>\n"
        "\t\t</class>\n")
    text = Class.saveall_xml()
    assert text.startswith("\t<classes>\n\t\t<class name=\"node\">")
    assert text.endswith("\t</classes>\n")

def test_to_dict(powerflow):
    _, load = powerflow
    load.set_event("init", "python:m.f")
    data = load.to_dict()
    assert "unit_spec" not in data["properties"]["constant_power_A"]
    assert data["name"] == "load" and data["module"] == "powerflow"
    assert data["parent"] == "node"
    assert data["passconfig"] == ["PRETOPDOWN", "BOTTOMUP", "POSTTOPDOWN"]
    assert data["events"] == {"init":"python:m.f"}
    assert data["properties"]["constant_power_A"]["flags"] == ["REQUIRED"]
    assert data["properties"]["constant_power_A"]["unit"] == "VA"
    assert Class.find("node").to_dict()["parent"] is None

#
# Documentation
#
def test_docstring_examples():
    result = doctest.testmod(arras.oclass, optionflags=doctest.ELLIPSIS)
    assert result.failed == 0 and result.attempted > 0
