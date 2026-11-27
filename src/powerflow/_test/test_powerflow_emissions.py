"""Class `emissions`: registration, initialization, energy, merit-order
dispatch, emissions, and the cycle"""
# pylint: disable=missing-function-docstring,line-too-long

import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model

VNOM = 2401.7771

def feeder(extra:str, parent:str="parent n1;") -> str:
    return f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
object meter {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object load {{ name ld; parent n1; phases ABCN; nominal_voltage {VNOM}; constant_power_A 100000; constant_power_B 100000; constant_power_C 100000; }}
object emissions {{ name em; {parent} {extra} }}
"""

SOURCES = "Nuclear_Max_Out 100; Coal_Max_Out 50; Naturalgas_Max_Out 1000; Coal_Conv_Eff 10000; Coal_CO2 0.0002; Coal_SO2 0.00001; Naturalgas_Conv_Eff 7000; Naturalgas_CO2 0.0001;"

def test_registration():
    Model().read_glm("module powerflow;\n")
    em = Class.find("emissions", module="powerflow")
    assert em.parent is None and em.trl == 0 and em.find_property("phases") is None
    assert em.find_property("Coal_Order").default == "6" and em.find_property("Petroleum_Order").default == "9"
    assert em.find_property("Coal_CO2").unit == "lb/Btu" and em.find_property("Wind_Conv_Eff").unit == "Btu/kWh"
    assert em.find_property("Total_emissions_NOx").unit == "lb" and em.find_property("cycle_interval").unit == "s"

def test_dispatch(helpers):
    """Each cycle's energy (300 kW for 900 s: 75 kWh) goes to the sources in
    merit order, each up to its maximum output in the cycle"""
    r = helpers.run(feeder(SOURCES), stop="2020-01-01 01:00:00")
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "em", "cycle_interval") == 900
    get = lambda x: powerflow.get_double(m, "em", x) # pylint: disable=unnecessary-lambda-assignment
    assert get("Nuclear_Out") == pytest.approx(25) and get("Hydroelectric_Out") == 0 and get("Coal_Out") == pytest.approx(12.5)
    assert get("Naturalgas_Out") == pytest.approx(37.5, rel=1e-6) and get("Total_energy_out") == pytest.approx(75, rel=1e-6)
    assert get("Coal_emissions_CO2") == pytest.approx(12.5*10000*0.0002) and get("Coal_emissions_SO2") == pytest.approx(12.5*10000*0.00001)
    assert get("Total_emissions_CO2") == pytest.approx(25 + 37.5*7000*0.0001, rel=1e-6)
    assert get("Nuclear_Max_Out") == 100 # not rescaled (gridlabd scales it at every new time)

def test_leftover(helpers):
    """Energy left after every source goes to coal, with coal's emissions"""
    m = helpers.run(feeder("Nuclear_Max_Out 100; Coal_Max_Out 50; Coal_Conv_Eff 10000; Coal_CO2 0.0002;"), stop="2020-01-01 00:15:00").model
    assert powerflow.get_double(m, "em", "Coal_Out") == pytest.approx(75 - 25, rel=1e-6)
    assert powerflow.get_double(m, "em", "Coal_emissions_CO2") == pytest.approx(50*10000*0.0002, rel=1e-6)

def test_disabled(helpers):
    """A source of order 0 produces nothing"""
    m = helpers.run(feeder(SOURCES + " Nuclear_Order 0;"), stop="2020-01-01 00:15:00").model
    assert powerflow.get_double(m, "em", "Nuclear_Out") == 0
    assert powerflow.get_double(m, "em", "Naturalgas_Out") == pytest.approx(62.5, rel=1e-6)

def test_cycle(helpers):
    """The energy of a shorter cycle"""
    m = helpers.run(feeder(SOURCES + " cycle_interval 300;"), stop="2020-01-01 00:15:00").model
    assert powerflow.get_double(m, "em", "Total_energy_out") == pytest.approx(25, rel=1e-6)

@pytest.mark.parametrize("extra, parent, message", [
    ("", "", "emissions:em must be parented to a three-phase meter to work!"),
    ("", "parent ld;", "emissions:em must be parented to a three-phase meter to work!"),
    ("cycle_interval -1;", "parent n1;", "emissions:em must have a positive cycle_interval time"),
])
def test_init_errors(helpers, extra, parent, message):
    r = helpers.run(feeder(extra, parent))
    assert any(message in x and "em emissions (id=" in x for x in helpers.errors(r)), r.stderr
