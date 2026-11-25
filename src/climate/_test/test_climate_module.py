"""The `climate` package: docstrings, registration, classes, and globals"""

import os
import json
import doctest
import importlib

import pytest

import climate
from arras.oclass import Class
from arras.module import Module
from arras.model import Model, ModelError
from arras.runner import Runner
from arras import exitcodes

MODULES = ["climate", "climate.climate", "climate.weather", "climate.csv_reader", "climate.tmy",
    "climate.solar_angles", "climate.cloud", "climate._common"]

@pytest.mark.parametrize("name", MODULES)
def test_doctests(name, tmp_path, monkeypatch):
    """The docstring examples give the output shown"""
    monkeypatch.chdir(tmp_path)
    result = doctest.testmod(importlib.import_module(name), optionflags=doctest.ELLIPSIS)
    assert result.failed == 0

def test_load(helpers):
    """GLM `module climate;` registers the module, its classes, and its
    globals"""
    m = helpers.model("")
    assert [x.name for x in climate.classes()] == ["climate", "weather", "csv_reader"]
    assert Module.find("climate") is not None
    assert set(m.classes) >= {"climate", "weather", "csv_reader"}
    var = m.globals.find("climate::message_flags")
    assert var.ptype == "set" and set(var.keywords) == {"QUIET", "WARNING", "DEBUG", "VERBOSE"}
    assert m.globals.get("climate::library_path") == os.path.join(m.globals.get("datadir"), "weather", "US")

def test_load_twice():
    """A second model gets the globals; the classes are registered once"""
    first = Model()
    first.read_glm("module climate;\n")
    second = Model()
    second.read_glm("module climate { library_path \"/data/weather\"; }\n")
    assert len(climate.classes()) == 3
    assert second.globals.get("climate::library_path") == "/data/weather"
    assert first.globals.get("climate::library_path") != "/data/weather"

DIFFERENCES = {("climate", "wind_dir"): {"unit": "deg", "description": "current direction in degrees"}}
"""Published property attributes that differ from gridlabd on purpose
(see the Differences of `climate.climate`)"""

def test_modhelp():
    """`modhelp()` prints what `gridlabd --modhelp climate` prints, except
    the `wind_dir` unit"""
    Model().read_glm("module climate;\n")
    with open(os.path.join(os.path.dirname(__file__), "data", "reference", "modhelp.txt"), encoding="utf-8") as fh:
        expected = fh.read().replace("double wind_dir[rad]; // (OUTPUT) current direction in radians",
            "double wind_dir[deg]; // (OUTPUT) current direction in degrees").split("\n\n")
    actual = [Class.find(name, module="climate").modhelp().strip() + "\n" for name in ("climate", "csv_reader", "weather")]
    assert [x.strip() for x in actual] == [x.strip() for x in expected]

def test_properties():
    """Property types, units, defaults, flags, access, and keywords are
    those of `gridlabd --modhelp=json climate`"""
    Model().read_glm("module climate;\n")
    with open(os.path.join(os.path.dirname(__file__), "data", "reference", "modhelp.json"), encoding="utf-8") as fh:
        data = json.load(fh)["classes"]
    for name in ("climate", "weather", "csv_reader"):
        oclass = Class.find(name, module="climate")
        expected = {key: value for key, value in data[f"climate.{name}"].items() if isinstance(value, dict)}
        assert [x.name for x in oclass.properties()] == list(expected)
        for prop in oclass.properties():
            info = {**expected[prop.name], **DIFFERENCES.get((name, prop.name), {})}
            assert prop.ptype == info["type"], prop
            assert prop.unit == info.get("unit"), prop
            assert prop.access == info["access"], prop
            assert set(x for x in str(info.get("flags", "")).split("|") if x) == \
                {x for x in ("REQUIRED", "OUTPUT") if prop.has_flag(x)}, prop
            if "default" in info:
                assert prop.default == info["default"], prop
            if "keywords" in info:
                assert prop.keywords == {k: int(v, 0) for k, v in info["keywords"].items()}, prop

def test_class_settings():
    """Pass configuration, readiness levels, functions, and handlers"""
    Model().read_glm("module climate;\n")
    cls = Class.find("climate", module="climate")
    assert cls.passconfig == 0x0201
    assert list(cls.functions) == ["calculate_solar_radiation_degrees", "calculate_solar_radiation_radians",
        "calculate_solar_radiation_shading_degrees", "calculate_solar_radiation_shading_radians",
        "calculate_solar_radiation_shading_position_radians", "calculate_solpos_radiation_shading_position_radians",
        "calc_solar_ideal_shading_position_radians"]
    assert cls.get_event("init") == "python:climate.init"
    assert cls.get_event("presync") == "python:climate.presync"
    assert cls.trl == 0
    weather = Class.find("weather", module="climate")
    assert weather.passconfig == 0 and weather.trl == 2 and not weather.events
    reader = Class.find("csv_reader", module="climate")
    assert reader.passconfig == 0 and reader.get_event("init") == "python:climate.reader_init"

def test_handlers_outside_run(helpers):
    """The handlers need a running simulation and an object of their class"""
    helpers.model("object climate { name c; }\nobject weather { name w; }")
    for call in (climate.init, climate.presync, climate.reader_init):
        with pytest.raises(climate.ClimateError):
            call("c", 0)

def test_handlers_wrong_class(helpers):
    """A handler on an object of another class fails the run"""
    r = helpers.run('object weather { name w; on_init "python:climate.init"; }')
    assert r.returncode == exitcodes.INIERR
    assert "is not a climate object" in r.stderr[-1]
    r = helpers.run('object weather { name w; on_init "python:climate.reader_init"; }')
    assert r.returncode == exitcodes.INIERR
    assert "is not a csv_reader object" in r.stderr[-1]

def test_entry_point_error(monkeypatch):
    """An error in `load()` is a `ModelError` of the model"""
    def fail(model):
        raise climate.ClimateError("broken")
    monkeypatch.setattr(climate, "load", fail)
    with pytest.raises(ModelError):
        Model().read_glm("module climate;\n")

def test_runner_with_model(helpers):
    """A model without a weather file runs with the values it sets"""
    r = helpers.run('object climate { name c; temperature 80; humidity 0.5; }', stop="2006-01-01 01:00:00")
    assert isinstance(r, Runner) and r.returncode == 0 and r.stderr == []
    assert r.model.get_property("c", "temperature") == "80"
