"""Class `building`: registration, thermal model, autosizing, outputs and ZIP
form, building types, loadshapes, occupancy, storage, inverter, sources,
meter, and errors"""
# pylint: disable=missing-function-docstring,line-too-long,too-many-arguments,too-many-positional-arguments

import cmath
import math

import pytest

import powerflow
from powerflow.building import inverter_output, inverter_settings, loadshape, occupancy_schedule, season_of
from powerflow.scheduled_load import find_data_file
from powerflow._common import PowerflowError
from arras.oclass import Class
from arras.model import Model

VNOM = 277.0
SF = 10.764
PARAMS = {"UA": 1000, "CA": 6e6, "UI": 15000, "CM": 2e7, "UM": 2000, "TH": -5, "TC": 35, "QE": 10, "QG": 1, "QO": 100, "QV": 50,
    "SA": 10, "TS": 22, "TO": 30, "QS": 400, "EU": 2, "NG": 1, "NH": 5, "floor_area": 500,
    "PZM": 0.1, "PPM": 0.2, "QPM": 0.05, "PZE": 0.5, "PIE": 0.2, "PPE": 0.3, "QZE": 0.05, "QIE": 0.02, "QPE": 0.03, "PPH": 0.06, "QPH": 0.01}

def building(extra:str="", phases:str="ABCN", **params) -> str:
    values = dict(PARAMS, **params)
    body = " ".join(f"{k} {v};" for k, v in values.items() if v is not None)
    return (f"object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}\n"
        f"object building {{ name b; parent n0; phases {phases}; nominal_voltage {VNOM}; {body} {extra} }}\n")

def get(m, prop:str) -> float:
    return powerflow.get_double(m, "b", prop)

def autosize(p:dict) -> float:
    g = p["QE"] + p["QG"] + p["QO"] + p["QV"] + 1300*p["SA"]
    tmh = (p["UI"]*p["TS"] + p["UM"]*p["TH"])/(p["UI"] + p["UM"])
    tmc = (p["UI"]*p["TS"] + p["UM"]*p["TC"] + g)/(p["UI"] + p["UM"])
    return max(2.0*(p["UA"]*(p["TS"] - p["TH"]) + p["UI"]*(p["TS"] - tmh)), 2.0*(p["UA"]*(p["TC"] - p["TS"]) + p["UI"]*(tmc - p["TS"])))

def steady(p:dict, qh:float, occupancy:float=0.0) -> tuple[float,float,float,list[float]]:
    """TA, TM, M, and u of the steady state"""
    ef, ee, eg, gg = p.get("electrification_fraction", 0), p.get("electrification_efficiency", 2), p.get("electric_gain_fraction", 1), p.get("gas_gain_fraction", 0.5)
    u = [p["TO"], (p["EU"] + ef*p["NG"]/ee)*eg, (1 - ef)*p["NG"]*gg, p["NH"]*occupancy, p["QS"], p["TS"]]
    tm = (p["UI"]*p["TS"] + p["UM"]*p["TO"] + p["SA"]*p["QS"])/(p["UI"] + p["UM"])
    gains = p["UA"]*(p["TO"] - p["TS"]) + p["UI"]*(tm - p["TS"]) + p["floor_area"]*SF*(u[1] + u[2]) + (p["QO"] + p["QV"])*u[3]
    return p["TS"], tm, -gains/qh, u

def outputs(p:dict, qh:float, m:float, u:list[float], electric_heat:bool=False, pv:float=0.0) -> list[float]:
    qc = -qh if m < 0 else (qh if electric_heat else 0.0)
    f = p["floor_area"]*SF
    return [p["PZM"]*qc*m + f*p["PZE"]*u[1], f*p["PIE"]*u[1], p["PPM"]*qc*m + f*p["PPE"]*u[1] + p["PPH"]*qh*0.1*u[3] - pv*u[4],
        f*p["QZE"]*u[1], f*p["QIE"]*u[1], p["QPM"]*qc*m + f*p["QPE"]*u[1] + p["QPH"]*qh*0.01*u[3]]

def test_registration():
    m = Model()
    m.read_glm("module powerflow;\n")
    oclass = Class.find("building", module="powerflow")
    assert oclass.trl == 9 and oclass.parent.name == "load"
    assert oclass.find_property("dt").default == "1h" and oclass.find_property("DF").default == "2.0 pu" and oclass.find_property("K").default == "1.0 pu"
    assert list(oclass.find_property("IC").keywords) == ["UL1741", "CARULE21", "IEEE1547", "UNITY"]
    assert m.globals.getvalue("powerflow::building_defaults") == "building_defaults.csv"
    assert m.globals.getvalue("powerflow::inverter_settings") == "inverter_settings.csv"

def test_steady_state_and_autosize(helpers):
    r = helpers.run(building(QH=0), start="2020-07-06 10:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    qh = autosize(PARAMS)
    assert get(m, "QH") == pytest.approx(qh)
    ta, tm, mode, u = steady(PARAMS, qh)
    assert (get(m, "TA"), get(m, "TM"), get(m, "M")) == pytest.approx((ta, tm, mode))
    y = outputs(PARAMS, qh, mode, u)
    # each part keeps its own power factor; each phase takes a third
    for kind, k in (("impedance", 0), ("current", 1), ("power", 2)):
        s = complex(y[k], y[k + 3])
        assert get(m, f"{kind}_pf_A") == pytest.approx(s.real/abs(s))
    assert powerflow.get_complex(m, "b", "constant_power_A") == pytest.approx(complex(y[2], y[5])/3)
    assert get(m, "measured_real_power") == pytest.approx(sum(y[:3])) and get(m, "measured_reactive_power") == pytest.approx(sum(y[3:]))

def test_undersized_and_saturation(helpers):
    r = helpers.run(building(QH=5000), start="2020-07-06 10:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    warns = helpers.warnings(r)
    assert any("b: system is undersized for TC = 35.0 degC" in x for x in warns)
    assert any("b: cooling control saturation (M=" in x and "QH=5.0 kW)" in x for x in warns)
    m = r.model
    assert get(m, "M") == -1
    _, _, _, u = steady(PARAMS, 5000)
    y = outputs(PARAMS, 5000, -1.0, u)
    assert get(m, "measured_real_power") == pytest.approx(sum(y[:3])) # limited M in the outputs

def test_single_phase_heating(helpers):
    p = dict(PARAMS, TO=-10, QS=0)
    r = helpers.run(building("electric_heat TRUE;", phases="AN", QH=200000, TO=-10, QS=0), start="2020-01-06 03:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    _, _, mode, u = steady(p, 200000)
    assert mode > 0 and get(m, "M") == pytest.approx(mode)
    y = outputs(p, 200000, mode, u, electric_heat=True)
    assert powerflow.get_complex(m, "b", "constant_power_A") == pytest.approx(complex(y[2], y[5]))
    assert get(m, "base_power_B") == 0

def test_building_type(helpers):
    """RETAIL defaults per floor area, loadshapes by season (July is
    summer), weekday occupancy"""
    r = helpers.run(building("building_type RETAIL; occupancy 4;", NH=4, UA=None, CA=None, UI=None, CM=None, UM=None, QE=None, QG=None, QO=None,
        QV=None, SA=None, TS=None, EU=None, NG=None, **{k: None for k in ("PZM", "PPM", "QPM", "PZE", "PIE", "PPE", "QZE", "QIE", "QPE", "PPH", "QPH")}),
        start="2020-07-06 10:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    with open(find_data_file("building_defaults.csv"), encoding="utf-8") as file:
        rows = [x.split(",") for x in file.read().splitlines()]
    defaults = dict(zip(rows[0][1:], (float(x) for x in next(row for row in rows if row[0] == "RETAIL")[1:])))
    assert get(m, "UA") == pytest.approx(defaults["UA"]*500) and get(m, "CM") == pytest.approx(defaults["CM"]*500)
    assert get(m, "TS") == defaults["TS"] and get(m, "PPE") == defaults["PPE"]
    shape = loadshape(find_data_file("building_loadshapes.csv"), "RETAIL", "ELECTRIC")
    assert get(m, "EU") == shape[10 + 0*24 + 2*48] # Monday 10:00, summer
    schedule = occupancy_schedule(find_data_file("building_occupancy.csv"), "RETAIL")
    start, stop, occupied, unoccupied = schedule[0]
    p = {k: get(m, k) for k in PARAMS}
    _, _, mode, _ = steady(p, get(m, "QH"), occupied if start <= 10 < stop else unoccupied)
    assert get(m, "M") == pytest.approx(mode)

def test_seasons_and_data():
    assert [season_of(x) for x in range(1, 13)] == [0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 0]
    assert loadshape(find_data_file("building_loadshapes.csv"), "NOPE", "GAS") is None
    assert occupancy_schedule(find_data_file("building_occupancy.csv"), "NOPE") is None
    settings = inverter_settings(find_data_file("inverter_settings.csv"))
    assert settings["UNITY"] == (0, 0, 0, 0, 0, 0) and settings["UL1741"] == (0.95, 1.05, -0.1, 0.1, 0.05, 0.05)

def test_inverter_output():
    ieee = (0.95, 1.05, -0.1, 0.1, 0.05, 0.05)
    assert inverter_output(ieee, 5000, 1.0, 10000) == 0
    low = inverter_output(ieee, 5000, 0.9, 10000)
    r = min(0.05*0.05, 0.1)*5000
    assert low == pytest.approx(5000 - cmath.rect(5000, math.asin(r/5000)))
    high = inverter_output(ieee, 5000, 1.1, 4000)
    r = max(-0.05*0.05, -0.1)*4000
    assert high == pytest.approx(5000 - cmath.rect(4000, -math.asin(r/4000)))
    assert inverter_output((0, 0, 0, 0, 0, 0), 5000, 1.0, 10000) == 0 # UNITY within the export limit
    assert inverter_output(ieee, 5000, 0.9, 0) == 0 # PX 0: no correction (gridlabd: NaN)

def test_solar_storage_export(helpers):
    """Solar exceeding the power part charges the battery up to PG; the
    inverter curtails the generation beyond PX"""
    pv, qs = 100, 1000
    r = helpers.run(building(QH=200000, PV=pv, QS=qs, BS=3.6e9, PG=20000, PX=50000), start="2020-07-06 10:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    _, _, mode, u = steady(dict(PARAMS, QS=qs), 200000)
    y = outputs(dict(PARAMS, QS=qs), 200000, mode, u, pv=pv)
    assert y[2] < -20000
    assert get(m, "ES") == pytest.approx(20000*3600) # PG limits the charge
    assert get(m, "measured_resource_power") == pytest.approx(pv*qs - 20000)
    curtailed = (pv*qs - 20000) - 50000 # UNITY: generation beyond PX
    net = max(sum(y[:3]) + 20000 + curtailed, -50000)
    assert get(m, "measured_real_power") == pytest.approx(net) and get(m, "power_fraction_A") == 1

def test_storage_supply(helpers):
    r = helpers.run(building(QH=200000, BS=3.6e9, ES=3.6e6, PG=5000), start="2020-07-06 10:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert get(m, "ES") == pytest.approx(0) # 1 kWh supplied over the hour (less than PG)
    assert get(m, "measured_resource_power") == pytest.approx(1000)
    plain = helpers.run(building(QH=200000), start="2020-07-06 10:00:00", lines=False).model
    assert get(m, "measured_real_power") == pytest.approx(get(plain, "measured_real_power") - 1000) # discharging lowers the load

def test_sources_and_dt(helpers):
    glm = "module climate;\nobject climate { name w; temperature 86; solar_global 10; record.low 14; }\n" + building(
        'temperature_source "w.temperature"; solar_source "w.solar_global"; heating_design "w.record.low"; dt 2h; measured_energy_delta_timestep 2h; measured_demand_timestep 2h;', QH=0)
    r = helpers.run(glm, start="2020-07-06 10:00:00", stop="2020-07-06 14:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert get(m, "TO") == pytest.approx(30, abs=0.01) and get(m, "QS") == pytest.approx(10*SF, rel=1e-3) and get(m, "TH") == pytest.approx(-10, abs=0.01)
    assert get(m, "measured_real_energy") == pytest.approx(get(m, "measured_real_power")*4)
    assert get(m, "measured_real_energy_delta") == pytest.approx(get(m, "measured_real_power")*2)
    assert not any("multiple of dt" in x for x in helpers.warnings(r))

@pytest.mark.parametrize("extra,params,message", [
    ("", {"K": 0}, "b: K must be positive"),
    ("", {"DF": -1}, "b: DF must be positive"),
    ("", {"QH": -1}, "b: QH must be non-negative"),
    ("electrification_fraction 2;", {}, "b: electrification fraction must be between 0 and 1"),
    ("gas_gain_fraction 0;", {}, "b: gas_gain_fraction must be positive"),
    ("", {"PV": -1}, "b: PV must be non-negative"),
    ('temperature_source "nothing.temperature";', {}, "b: temperature source 'nothing.temperature' is not valid"),
    ("building_type NOPE;", {}, "b: building type 'NOPE' not found in"),
    ("building_type RETAIL;", {"floor_area": 0}, "b: floor area must be positive"),
])
def test_errors(helpers, extra, params, message):
    r = helpers.run(building(extra, **params), lines=False)
    assert r.returncode != 0 and any(message in x for x in helpers.errors(r)), helpers.errors(r)

def test_warnings(helpers):
    r = helpers.run(building("measured_energy_delta_timestep 1800; measured_demand_timestep 5400;", PPE=0.2), lines=False)
    assert r.returncode == 0, r.stderr
    warns = helpers.warnings(r)
    assert any("b: measured_energy_delta_timestep must a multiple of dt" in x for x in warns)
    assert any("b: measured_demand_timestep must a multiple of dt" in x for x in warns)
    assert any("b: real power output fractions must add to 1.0" in x for x in warns)

def test_inverter_file_errors(helpers):
    with open("inv.csv", "w", encoding="utf-8") as file:
        file.write("standard,Vmin,Vmax,Qmin,Qmax,Slow,Shigh\nUNITY,1,0,0,0,0,0\n")
    with pytest.raises(PowerflowError, match="voltage deadband is inverted"):
        inverter_settings("inv.csv")
    r = helpers.run(building(), module='inverter_settings "missing.csv";', lines=False)
    assert r.returncode != 0 and any("unable to stat file 'missing.csv'" in x for x in helpers.errors(r))
