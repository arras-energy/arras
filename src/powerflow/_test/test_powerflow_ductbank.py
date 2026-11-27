"""Class `ductbank`: registration, configurations, cables and air gap, cable
temperature, status, sources, and errors"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import pytest

import powerflow
from powerflow.ductbank import read_configurations
from powerflow.scheduled_load import find_data_file
from powerflow._common import PowerflowError
from arras.oclass import Class
from arras.model import Model

def feeder(duct:str, power:str="2 MVA", extra:str="") -> str:
    """gridlabd's test_ductbank.glm without the weather"""
    return f"""
object node {{ name source; bustype SWING; nominal_voltage 12.47 kV; phases ABCN; }}
object load {{ name sink; nominal_voltage 12.47 kV; phases ABCN; constant_power_A {power}; constant_power_B {power}; constant_power_C {power}; }}
object underground_line {{ phases ABCN; name line; from source; to sink; length 1 mile; configuration lc; ductbank duct; }}
object ductbank {{ name duct; {duct} }}
object underground_line_conductor {{ name ct; outer_diameter 1.06 in; conductor_gmr 0.0111 ft; neutral_gmr 0.01113 ft; conductor_diameter 0.368 in;
    conductor_resistance 0.97 Ohm/mile; neutral_resistance 0.607 Ohm/mile; insulation_relative_permitivitty 2.3; shield_gmr 0.0365 ft;
    shield_resistance 4.2786 Ohm/mile; shield_diameter 0.88 in; shield_thickness 0.005 in; {extra} }}
object line_configuration {{ name lc; conductor_A ct; conductor_B ct; conductor_C ct; conductor_N ct; spacing ls; }}
object line_spacing {{ name ls; distance_AB 2.5; distance_AC 4.5; distance_BC 7.0; distance_BN 0.25; distance_AN 0.25; distance_CN 0.25; }}
"""

def get(m, prop:str) -> float:
    return powerflow.get_double(m, "duct", prop)

def test_registration():
    m = Model()
    m.read_glm("module powerflow;\n")
    oclass = Class.find("ductbank", module="powerflow")
    assert oclass.trl == 9 and oclass.parent is None
    assert list(oclass.find_property("cable_status").keywords) == ["UNKNOWN", "ALERT", "WARNING", "OK"]
    assert m.globals.getvalue("powerflow::ground_temperature") == 25.0 and m.globals.getvalue("powerflow::alert_cable_temperature") == 90.0
    assert m.globals.getvalue("powerflow::ductbank_configuration_file") == "ductbank_configurations.csv"
    assert [x.name for x in powerflow.classes()][-2:] == ["ductbank", "zipload"]

def test_configurations():
    data = read_configurations(find_data_file("ductbank_configurations.csv"))
    assert data["default"] == (0.1, 1.0, 0.3, 1) and data["box4x2"][3] == 8

def test_temperature(helpers):
    r = helpers.run(feeder('configuration "default";'), stop="2020-01-01 01:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert (get(m, "duct_area"), get(m, "fill_R"), get(m, "duct_R"), int(m.get_property("duct", "channels"))) == (0.1, 1.0, 0.3, 1)
    # four cables of 1.06 in, insulation 10 K/W each in parallel
    cable = 4*(1.06/39.4)**2*math.pi/4
    assert get(m, "insulation_R") == pytest.approx(2.5)
    assert get(m, "air_R") == pytest.approx(1/(0.2/(math.sqrt(0.1 - cable)/2)))
    heat = abs(powerflow.get_complex(m, "line", "power_losses"))/(5280*12*2.54/100)
    assert heat > 0 and get(m, "heatgain") == pytest.approx(heat)
    total = 1.0 + 0.3 + get(m, "air_R") + 2.5
    assert get(m, "surface_temperature") == 25 and get(m, "cable_temperature") == pytest.approx(25 + heat/total)
    assert get(m, "peak_temperature") == get(m, "cable_temperature") and m.get_property("duct", "cable_status") == "OK"

def test_explicit_values_and_source(helpers):
    """No configuration (gridlabd crashes); the surface temperature from a
    global, converted to degC"""
    glm = feeder('duct_area 0.2; fill_R 2; duct_R 0.5; channels 2; air_R 1; insulation_R 5; temperature_source "powerflow::warning_cable_temperature";', extra="insulation_R 20;")
    r = helpers.run(glm, module="warning_cable_temperature 30 degC; ground_temperature 10;", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert get(m, "insulation_R") == pytest.approx(1/(1/5 + 4/20))
    cable = 4*(1.06/39.4)**2*math.pi/4
    assert get(m, "air_R") == pytest.approx(1/(1 + 0.2/(math.sqrt((0.2 - cable)/2)/2)))
    assert get(m, "surface_temperature") == pytest.approx(30)
    assert m.get_property("duct", "cable_status") == "WARNING" # 30 degC plus the cables' rise is above the 30 degC warning
    assert any("duct: cable temperature warning" in x for x in helpers.warnings(r))

def test_alert(helpers):
    r = helpers.run(feeder('configuration "default";', power="8 MVA"), module="alert_cable_temperature 30;", lines=False)
    assert r.returncode == 0, r.stderr
    assert r.model.get_property("duct", "cable_status") == "ALERT"
    assert any("duct: cable temperature alert (" in x for x in helpers.warnings(r))

def test_ground_temperature(helpers):
    r = helpers.run(feeder('configuration "box3x2";'), module="ground_temperature 15;", lines=False)
    m = r.model
    assert get(m, "surface_temperature") == 15 and int(m.get_property("duct", "channels")) == 6

def test_cables_do_not_fit(helpers):
    r = helpers.run(feeder('configuration "default"; duct_area 0.001;'), lines=False)
    assert r.returncode != 0 and any("duct: cannot fit anymore cables" in x for x in helpers.errors(r))

@pytest.mark.parametrize("duct,message", [
    ('configuration "nothing";', "duct: ductbank configuration 'nothing' not found"),
    ("duct_area 0.1; fill_R 1; duct_R 0.3;", "duct: channels must be positive"),
    ('configuration "default"; temperature_source "nothing.x";', "duct: temperature source 'nothing.x' is not valid"),
])
def test_errors(helpers, duct, message):
    r = helpers.run(feeder(duct), lines=False)
    assert r.returncode != 0 and any(message in x for x in helpers.errors(r)), helpers.errors(r)

def test_file_errors(helpers):
    with open("bad.csv", "w", encoding="utf-8") as file:
        file.write("name,area\n")
    with pytest.raises(PowerflowError, match="invalid header"):
        read_configurations("bad.csv")
    r = helpers.run(feeder('configuration "default";'), module='ductbank_configuration_file "missing.csv";', lines=False)
    assert r.returncode != 0 and any("unable to open ductbank configuration file 'missing.csv'" in x for x in helpers.errors(r))
