"""The `residential` package: docstrings, registration, globals, published
properties, the enduse internal item, and handler errors"""
# pylint: disable=missing-function-docstring,line-too-long

import doctest
import importlib

import pytest

import residential
from residential._common import ResidentialError, Members
from arras.oclass import Class
from arras.module import Module
from arras.model import Model

MODULES = ["residential", "residential.residential_enduse", "residential.house", "residential.zipload"]

@pytest.mark.parametrize("name", MODULES)
def test_doctests(name):
    """The docstring examples give the output shown"""
    result = doctest.testmod(importlib.import_module(name), optionflags=doctest.ELLIPSIS)
    assert result.failed == 0

def test_load():
    """GLM `module residential;` registers the classes in order with their
    parents, pass configurations, and readiness levels, the enduse internal
    item once, and the globals"""
    m = Model()
    m.read_glm("module residential;\nmodule residential;\n")
    assert [x.name for x in residential.classes()] == ["residential_enduse", "house", "ZIPload"]
    house = Class.find("house", module="residential")
    zipload = Class.find("ZIPload", module="residential")
    assert house.parent.name == zipload.parent.name == "residential_enduse"
    assert house.trl == 9
    assert [item[0] for item in Module.internals["enduse"]].count(residential.enduse_syncall) == 1
    assert residential._common.g(m, "implicit_enduses") == 0x03170303 # pylint: disable=protected-access
    assert m.globals.getvalue("residential::default_outdoor_temperature") == 74.0
    assert m.globals.getvalue("residential::system_dwell_time") == 1.0
    assert m.globals.getvalue("residential::default_etp_iterations") == 100
    assert m.globals.get("residential::curtailment_enduses") == "DISHWASHER|MICROWAVE|RANGE|EVCHARGER|CLOTHESWASHER|DRYER"

def test_properties():
    """Published properties: the enduse parts, the house's own, aliases, and
    keyword values as gridlabd publishes them"""
    Model().read_glm("module residential;\n")
    enduse = Class.find("residential_enduse", module="residential")
    assert [p.name for p in enduse.properties()][:5] == ["shape", "load", "energy", "power", "peak_demand"]
    assert enduse.find_property("configuration").keywords == {"IS220": 1, "IS110": 0}
    house = Class.find("house", module="residential")
    assert house.find_property("floor_area").unit == "sf"
    assert house.find_property("panel.energy").ptype == "complex"
    assert house.find_property("panel.energy").unit == "kVAh"
    assert house.find_property("include_solar_quadrant").keywords["W"] == 16
    assert house.find_property("include_solar_quadrant").default == "ALLWALLS"
    assert house.find_property("cooling_system_type").keywords["HEAT_PUMP"] == 2
    assert house.find_property("load_power_fraction").default == "+0.8"
    zipload = Class.find("ZIPload", module="residential")
    assert zipload.find_property("heat_fraction").default == "0.9"
    assert zipload.find_property("demand_rate").unit == "1/h"

def test_globals_set():
    """The module block sets globals"""
    m = Model()
    m.read_glm("module residential { implicit_enduses NONE; system_dwell_time 60; }\n")
    assert m.globals.get("residential::implicit_enduses") == "NONE"
    assert m.globals.getvalue("residential::system_dwell_time") == 60.0

def test_implicit_enduses_refused(helpers):
    """A house fails to initialize with implicit enduses"""
    r = helpers.run("object house { name h; }", module="")
    assert r.returncode != 0
    assert any("implicit enduses are not implemented" in x for x in helpers.errors(r))

def test_static_data(helpers):
    """Without climate or parent meter, a house warns and uses the default
    weather and static voltages"""
    r = helpers.run("object house { name h; air_temperature 70; mass_temperature 70; }", stop="2020-01-01 06:00:00")
    assert r.returncode == 0, r.stderr
    warnings = helpers.warnings(r)
    assert any("no climate data found, using static data" in x for x in warnings)
    assert any("has no parent triplex_meter defined; using static voltages" in x for x in warnings)
    assert residential.get_double(r.model, "h", "outdoor_temperature") == 74.0

def test_enduse_energy(helpers):
    """`energy` accumulates `power` at each time step and `heatgain` is
    cleared by the enduse internal item; a house panel sums its circuits"""
    r = helpers.run("""
        object house { name h; heating_system_type NONE; cooling_system_type NONE; auxiliary_system_type NONE; fan_type NONE;
            air_temperature 70; mass_temperature 70;
            object ZIPload { name z; base_power 2; heat_fraction 0.5; };
        }
        object house { name h2; heating_system_type NONE; cooling_system_type NONE; air_temperature 70; mass_temperature 70; }
        """, stop="2020-01-01 06:00:00")
    assert r.returncode == 0, r.stderr
    m = r.model
    assert residential.get_complex(m, "z", "power") == pytest.approx(2)
    energy = residential.get_complex(m, "z", "energy").real
    clock = m.globals.timestamp_from_string(m.get_property("h", "clock"))
    assert energy == pytest.approx(2*(clock - m.globals.getvalue("starttime"))/3600)
    assert residential.get_complex(m, "h", "panel.energy").real == pytest.approx(energy)
    assert residential.get_double(m, "z", "heatgain") == pytest.approx(0.5*2*3412)

def test_handlers_outside_run():
    """The handlers work only in a run"""
    Model().read_glm("module residential;\nobject house { name h; }\n")
    with pytest.raises(ResidentialError):
        residential.init("h", 0)

def test_members_aliases():
    """`Members` takes the alias the model sets, else the last alias's value"""
    m = Model()
    m.read_glm("module residential;\nobject house { name h; power_fraction 0.4; }\nobject house { name h2; }\n")
    from residential.house import HouseMembers # pylint: disable=import-outside-toplevel
    a = HouseMembers(m, "h")
    a.read()
    assert a.load.power_fraction == 0.4
    b = HouseMembers(m, "h2")
    b.read()
    assert b.load.power_fraction == 0.8
    assert isinstance(b, Members)
