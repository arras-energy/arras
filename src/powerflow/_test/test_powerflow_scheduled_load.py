"""Classes `agricultural`, `public_service`, and `industrial`: registration,
schedules, ZIP form, meter, sensitivity, threshold, NAICS composition, and
errors"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import pytest

import powerflow
from powerflow.scheduled_load import parse_schedule, schedule_records, apparent, next_interval
from powerflow._common import PowerflowError
from arras.oclass import Class
from arras.model import Model

VNOM = 7200.0
SWING = f"object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}\n"

def load(cls:str, body:str, phases:str="ABCN") -> str:
    return SWING + f"object {cls} {{ name ld; parent n0; phases {phases}; nominal_voltage {VNOM}; P0 1 MW; {body} }}\n"

def get(m, prop:str) -> float:
    return powerflow.get_double(m, "ld", prop)

def test_registration():
    Model().read_glm("module powerflow;\n")
    for name in ("agricultural", "public_service", "industrial"):
        oclass = Class.find(name, module="powerflow")
        assert oclass.trl == 9 and oclass.parent.name == "load"
        assert oclass.find_property("schedule").ptype == "method"
        assert oclass.find_property("measured_energy_delta_timestep").default == "3600 s"
    assert Class.find("agricultural", module="powerflow").find_property("Pf").default == "+1 pu"
    assert Class.find("industrial", module="powerflow").find_property("Pf") is None
    names = [x.name for x in powerflow.classes()]
    assert names[names.index("pole_mount") + 1:names.index("pole_mount") + 4] == ["industrial", "agricultural", "public_service"]

def test_schedule_parse():
    assert schedule_records("1-12,0-4,12-23,1,0.5,0.5,0.5,0.5,0.5,0.5,0.99,1-12,5-6,0-11,0.1") == ["1-12,0-4,12-23,1,0.5,0.5,0.5,0.5,0.5,0.5,0.99", "1-12,5-6,0-11,0.1"]
    assert schedule_records('"1-2,0-6,0-23,0.5;\n3-3,0-0,1-1,1,0.9"') == ["1-2,0-6,0-23,0.5", "3-3,0-0,1-1,1,0.9"]
    table = parse_schedule("1-12,0-6,0-23,0.5;6-6,0-4,8-9,0.1,0.2,0.3,0.4,0.5,0.6,0.7", 0.9)
    assert len(table) == 12*7*24
    assert table[(0, 6, 23)].aggregate and table[(0, 6, 23)].total == 0.5 and table[(0, 6, 23)].pf == 0.9
    item = table[(5, 4, 9)]
    assert not item.aggregate and item.total == pytest.approx(2.8) and (item.a, item.i, item.pf) == (0.1, 0.7, 0.9)
    assert parse_schedule("1-1,0-0,0-0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,-0.8", 1.0, totals=False)[(0, 0, 0)].total == 0.0
    for text, message in (("0-12,0-6,0-23,1", "month 0-12 is invalid"), ("1-12,0-7,0-23,1", "weekday 0-7 is invalid"),
            ("1-12,0-6,5-24,1", "hours 5-24 is invalid"), ("1-12,0-6,0-23,1,2,3", "missing required value"), ("1-12,0-6", "missing required value")):
        with pytest.raises(PowerflowError, match=message):
            parse_schedule(text, 1.0)

def test_helpers():
    assert apparent(100, 1) == 100 and apparent(100, 0) == 100j
    assert apparent(100, -0.8) == pytest.approx(100 - 75j) and apparent(100, 0.8) == pytest.approx(100 + 75j)

def test_agricultural_zip_and_meter(helpers):
    """Morning half load at pf 0.95, afternoon full load at Pf; the meter's
    energy, deltas, and demand"""
    r = helpers.run(load("agricultural", 'Mc 1 pu; Pz 0; schedule "1-12,0-6,0-11,0.5,0.95"; schedule "1-12,0-6,12-23,1.0";'),
        start="2020-01-01 10:00:00", stop="2020-01-01 13:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("ld", "schedule") == "1-12,0-6,0-11,0.5,0.95;1-12,0-6,12-23,1.0"
    assert get(m, "measured_real_power") == pytest.approx(1e6) and get(m, "measured_reactive_power") == pytest.approx(0, abs=1e-6)
    assert powerflow.get_complex(m, "ld", "constant_power_A") == pytest.approx(1e6/3)
    # 10:00-12:00 at 0.5 MW, 12:00-13:00 at 1 MW
    q = 0.5e6*math.tan(math.acos(0.95))
    assert get(m, "measured_real_energy") == pytest.approx(2e6) and get(m, "measured_reactive_energy") == pytest.approx(2*q)
    assert get(m, "measured_real_energy_delta") == pytest.approx(1e6) and get(m, "measured_demand") == pytest.approx(1e6)
    r = helpers.run(load("agricultural", 'Mc 1 pu; schedule "1-12,0-6,0-11,0.5,0.95";'), start="2020-01-01 10:00:00", lines=False)
    m = r.model
    assert powerflow.get_complex(m, "ld", "constant_power_B") == pytest.approx(complex(0.5e6/3, q/3))
    assert get(m, "base_power_A") == pytest.approx(0.5e6/3/0.95) and get(m, "power_pf_A") == 0.95 and get(m, "power_fraction_A") == 1
    assert get(m, "measured_reactive_power") == pytest.approx(q)

def test_composition_and_phases(helpers):
    """Composite record; a single-phase load takes the whole load; leading
    power factor"""
    r = helpers.run(load("agricultural", 'Pz 1; Pi 1; Ma 2; Pf -0.8; schedule "1-12,0-6,0-23,0.5,0.4,0.3,0.2,0.1,1,1";', phases="AN"), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert any("load components do not sum to 1.0 (sum=4), normalizing automatically" in x for x in helpers.warnings(r))
    assert get(m, "Pz") == 0.25 and get(m, "Ma") == 0.5
    z, i, p = 0.25e6, 0.25e6, 0.5*0.5e6
    assert get(m, "measured_real_power") == pytest.approx(z + i + p) and get(m, "measured_reactive_power") == pytest.approx(-(z + i + p)*0.75)
    assert get(m, "base_power_A") == pytest.approx((z + i + p)/0.8) and get(m, "base_power_B") == 0
    assert get(m, "impedance_fraction_A") == pytest.approx(z/(z + i + p)) and get(m, "current_pf_A") == -0.8

def test_weekdays(helpers):
    """Monday is weekday 0 (2024-01-01 is a Monday)"""
    glm = load("agricultural", 'Mc 1; schedule "1-12,0-0,0-23,1"; schedule "1-12,6-6,0-23,0.25";')
    assert get(helpers.run(glm, start="2024-01-01 05:00:00", lines=False).model, "measured_real_power") == pytest.approx(1e6)
    assert get(helpers.run(glm, start="2024-01-07 05:00:00", lines=False).model, "measured_real_power") == pytest.approx(0.25e6)
    assert get(helpers.run(glm, start="2024-01-03 05:00:00", lines=False).model, "measured_real_power") == 0

def test_top_of_hour(helpers):
    r = helpers.run(load("agricultural", 'Mc 1; schedule "1-12,0-6,0-23,1";'), start="2020-01-01 00:30:00", stop="2020-01-01 00:59:00", lines=False)
    assert get(r.model, "measured_real_power") == 0 and get(r.model, "measured_real_energy") == 0
    r = helpers.run(load("agricultural", 'Mc 1; schedule "1-12,0-6,0-23,1";'), start="2020-01-01 00:30:00", stop="2020-01-01 02:00:00", lines=False)
    assert get(r.model, "measured_real_energy") == pytest.approx(1e6)

def test_sensitivity(helpers):
    glm = load("agricultural", 'Mc 1; schedule "1-12,0-6,0-23,0.5"; sensitivity_source "powerflow::primary_voltage_ratio"; sensitivity_value 1000; sensitivity_base -20000;')
    r = helpers.run(glm, module="primary_voltage_ratio 120;", lines=False)
    assert r.returncode == 0, r.stderr
    assert get(r.model, "measured_real_power") == pytest.approx(0.5e6 + 1000*120 - 20000)

def test_meter_intervals(helpers):
    """Energy delta every 2 h, demand every 3 h (local time); the intervals
    are events"""
    glm = load("agricultural", 'Mc 1; schedule "1-12,0-6,0-23,0.5"; schedule "1-12,0-6,2-3,1"; measured_energy_delta_timestep 2h; measured_demand_timestep 3h;')
    r = helpers.run(glm, start="2020-01-01 00:00:00", stop="2020-01-01 05:00:00", lines=False)
    m = r.model
    assert get(m, "measured_real_energy") == pytest.approx(0.5e6*3 + 1e6*2)
    assert get(m, "measured_real_energy_delta") == pytest.approx(2e6) # 2:00-4:00
    assert get(m, "measured_demand") == pytest.approx(1e6) # 0:00-3:00
    assert next_interval(m, 3600, 7200) == 7200 and next_interval(m, 7200, 7200) == 14400

@pytest.mark.parametrize("body,on", [("", True), ("threshold_source \"powerflow::primary_voltage_ratio\"; threshold_value 100;", True),
    ("threshold_source \"powerflow::primary_voltage_ratio\"; threshold_value 200;", False),
    ("threshold_source \"powerflow::primary_voltage_ratio\"; threshold_value 200; threshold_invert TRUE;", True),
    ("threshold_invert TRUE;", True), ("threshold_source \"n0.nominal_voltage\"; threshold_value 7000;", True)])
def test_public_service(helpers, body, on):
    glm = load("public_service", f'Pi 1; schedule "1-12,0-6,0-23,0.5,0.9"; {body}')
    r = helpers.run(glm, module="primary_voltage_ratio 120;", lines=False)
    assert r.returncode == 0, r.stderr
    assert get(r.model, "measured_real_power") == pytest.approx(0.5e6 if on else 0)
    if on:
        assert get(r.model, "current_fraction_A") == 1 and get(r.model, "current_pf_A") == 0.9

def test_industrial(helpers):
    """MECS_313 (by code and by index): 0.16 0.34 0.02 0 0.18 0.28 0.02; the
    composite record of gridlabd's test_industrial.glm on a Monday"""
    for code in ("MECS_313", "313"):
        r = helpers.run(load("industrial", f'industry_code "{code}"; P0 10 MW; schedule "1-12,0-4,12-23,1,0.5,0.5,0.5,0.5,0.5,0.5,0.99";', phases="ABCD"),
            start="2022-01-03 12:00:00", lines=False)
        assert r.returncode == 0, r.stderr
        m = r.model
        assert [get(m, x) for x in ("Pz", "Pi", "Ma", "Mb", "Mc", "Md", "Pe")] == pytest.approx([0.28, 0.02, 0.16, 0.34, 0.02, 0, 0.18])
        assert get(m, "measured_real_power") == pytest.approx(5.8e6) and get(m, "measured_reactive_power") == pytest.approx(0.826455e6, rel=1e-6)
    r = helpers.run(load("industrial", 'industry_code "MECS_313"; schedule "1-12,0-6,0-23,0.5";'), lines=False)
    assert get(r.model, "measured_reactive_power") == 0 # default power factor 1

def test_industrial_datafile(helpers, here=None): # pylint: disable=unused-argument
    with open("naics.csv", "w", encoding="utf-8") as file:
        file.write("NAICS,Code,Industrial Load Type,IA,IB,IC,MD,PwrEl,Z,I\n1,X1,Test,0.5,0,0,0,0,0.5,0.5\n")
    r = helpers.run(load("industrial", 'industry_code X1; schedule "1-12,0-6,0-23,1";'), module='NAICS_datafile "naics.csv";', lines=False)
    assert r.returncode == 0, r.stderr
    assert any("components do not sum to 1.0 (sum is 1.5)" in x for x in helpers.warnings(r))
    assert get(r.model, "Ma") == pytest.approx(1/3) and get(r.model, "measured_real_power") == pytest.approx(1e6)
    with open("naics.csv", "w", encoding="utf-8") as file:
        file.write("NAICS,Code\n")
    r = helpers.run(load("industrial", 'industry_code X1; schedule "1-12,0-6,0-23,1";'), module='NAICS_datafile "naics.csv";', lines=False)
    assert r.returncode != 0 and any("invalid header line" in x for x in helpers.errors(r))

@pytest.mark.parametrize("glm,message", [
    (load("agricultural", 'Mc 1; schedule "1-12,0-6,0-23,1";').replace("P0 1 MW;", "P0 0;"), "ld: nameplate power P0 must be positive"),
    (load("agricultural", 'schedule "1-12,0-6,0-23,1";'), "ld: load components sum to zero"),
    (load("agricultural", 'Mc 1; schedule "1-12,0-6,0-24,1";'), "ld: composition '1-12,0-6,0-24,1': hours 0-24 is invalid"),
    (load("agricultural", 'Mc 1; schedule "1-12,0-6,0-23,1"; sensitivity_source "nothing.x";'), "ld: sensitivity source 'nothing.x' is not valid"),
    (load("public_service", 'Mc 1; schedule "1-12,0-6,0-23,1"; threshold_source "n0.nothing";'), "ld: threshold source 'n0.nothing' is not valid"),
    (load("industrial", 'schedule "1-12,0-6,0-23,1";'), "ld: NAICS industry code must be specified"),
    (load("industrial", 'industry_code NOPE; schedule "1-12,0-6,0-23,1";'), "ld: unable to locate industry code 'NOPE' in NAICS data file 'naics_data_file.csv'"),
    (load("agricultural", 'Mc 1; schedule "1-12,0-6,0-23,1"; measured_demand_timestep -1;'), "ld: measured_demand_timestep must be non-negative"),
])
def test_errors(helpers, glm, message):
    r = helpers.run(glm, lines=False)
    assert r.returncode != 0 and any(message in x for x in helpers.errors(r)), helpers.errors(r)

def test_schedule_warnings(helpers):
    r = helpers.run(load("agricultural", 'Mc 1; schedule "1-1,0-0,0-0,1.5"; schedule "1-1,0-0,1-1,0.5,1.5";'), lines=False)
    assert r.returncode == 0, r.stderr
    warns = helpers.warnings(r)
    assert any("ld: invalid load schedule aggregated total 1.5 for month 0, weekday 0, hour 0" in x for x in warns)
    assert any("ld: invalid load schedule power factor 1.5 for month 0, weekday 0, hour 1" in x for x in warns)
    assert any("ld: missing or null load schedule" in x for x in warns)
