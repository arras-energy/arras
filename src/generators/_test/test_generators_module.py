"""Module registration: classes, properties, globals, handlers, and the
docstring examples"""

import doctest
import importlib

import pytest

from arras.model import Model
from arras.oclass import Class
from arras.module import Module

import generators
from generators import GeneratorsError
from generators.inverter import Inverter
from generators.solar import Solar

def test_load_registers_classes_and_globals():
    """Loading the module registers inverter and solar and the globals"""
    m = Model()
    m.read_glm("module generators;\n")
    assert [x.name for x in generators.classes()] == ["inverter", "solar"]
    assert Module.find("generators") is not None
    assert m.globals.get("generators::enable_subsecond_models") == "FALSE"
    assert m.globals.isdefined("generators::deltamode_timestep")
    assert m.globals.isdefined("generators::message_flags")

def test_load_twice():
    """A second model gets the globals without registering the classes again"""
    Model().read_glm("module generators;\n")
    m = Model()
    m.read_glm("module generators;\n")
    assert len(generators.classes()) == 2
    assert m.globals.isdefined("generators::enable_subsecond_models")

@pytest.mark.parametrize("cls,count,first,last", [
    (Inverter, 163, "inverter_type", "volt_var_control_lockout"),
    (Solar, 40, "generator_mode", "orientation"),
])
def test_properties(cls, count, first, last):
    """Every property gridlabd publishes is published, in its order"""
    Model().read_glm("module generators;\n")
    oclass = Class.find(cls.NAME, module="generators")
    names = [p.name for p in oclass.properties()]
    assert len(names) == count
    assert names[0] == first and names[-1] == last
    assert oclass.get_event("sync") == "python:generators.sync"

def test_defaults():
    """Defaults are those of the C++ create() functions"""
    m = Model()
    m.read_glm("module generators;\nobject inverter { name i; }\nobject solar { name s; }\n")
    assert m.get_property("i", "four_quadrant_control_mode") == "CONSTANT_PF"
    assert m.get_property("i", "pf_reg") == "EXCLUDED"
    assert float(m.get_property("i", "battery_soc").split()[0]) == -1
    assert m.get_property("i", "generator_mode") == "UNKNOWN"
    assert m.get_property("s", "SOLAR_TILT_MODEL") == "DEFAULT"
    assert m.get_property("s", "tilt_angle").startswith("45")

def test_handlers_need_a_run():
    """The handlers work only during a run"""
    m = Model()
    m.read_glm("module generators;\nobject solar { name s; }\n")
    with pytest.raises(GeneratorsError):
        generators.init("s", 0)

@pytest.mark.parametrize("name", ["generators", "generators.inverter", "generators.solar"])
def test_doctests(name):
    """The docstring examples give the output shown"""
    result = doctest.testmod(importlib.import_module(name), optionflags=doctest.ELLIPSIS)
    assert result.failed == 0
