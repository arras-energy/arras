"""Classes `meter`, `triplex_node`, `triplex_meter`, and `triplex_load`, and
split-phase solutions (center-tapped transformer and triplex line) checked
against an independent solution"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model

VP = 7200.0
"""Primary voltage (V, line to neutral)"""

LOADS = {"1": 2000+500j, "2": 1500+300j, "12": 3000+1000j}

def feeder(meter:str="", load:str="", loads:dict|None=None) -> str:
    loads = LOADS if loads is None else loads
    terms = " ".join(f"constant_power_{k} {v.real:.0f}{v.imag:+.0f}j;" for k, v in loads.items())
    return f"""
object transformer_configuration {{ name tc; connect_type SINGLE_PHASE_CENTER_TAPPED; install_type POLETOP; primary_voltage {VP}; secondary_voltage 120;
    power_rating 50; powerA_rating 50; impedance 0.006+0.0136j; }}
object node {{ name n1; phases ABCN; nominal_voltage {VP}; bustype SWING; }}
object transformer {{ name t12; phases AS; from n1; to m2; configuration tc; }}
object triplex_meter {{ name m2; phases AS; nominal_voltage 120; {meter} }}
object triplex_line_conductor {{ name tlc; resistance 0.97; geometric_mean_radius 0.0111; }}
object triplex_line_configuration {{ name tlcfg; conductor_1 tlc; conductor_2 tlc; conductor_N tlc; insulation_thickness 0.08; diameter 0.368; }}
object triplex_line {{ name tl; phases AS; from m2; to l3; length 100; configuration tlcfg; }}
object triplex_load {{ name l3; phases AS; nominal_voltage 120; {terms} {load} }}
"""

def carson(gmr_or_d:float, r:float=0.0) -> complex:
    return complex(r + 0.00158836*60, 0.00202237*60*(math.log(1/gmr_or_d) + math.log(100/60)/2 + 7.6786))

def reference(loads:dict) -> dict:
    """Independent solution in physical coordinates (line 2 measured from
    the neutral to the line): Kersting's center-tapped transformer with
    gridlabd's impedance split, and the triplex line with its neutral
    Kron-reduced, by fixed-point iteration"""
    # pylint: disable=too-many-locals
    rating = 50e3
    high, low = VP*VP/rating, 120*120/rating
    z = 0.006+0.0136j
    z0, z1 = complex(0.5*z.real, 0.8*z.imag)*high, complex(z.real, 0.4*z.imag)*low
    z2, zc = z1, high*1e9*1j*1e9/complex(1e9, 1e9)
    nt = VP/120
    zp11, zp12, zp13 = carson(0.0111, 0.97), carson((0.368 + 0.16)/12), carson((0.368 + 0.08)/12)
    zp = np.array([[zp11 - zp13**2/zp11, zp12 - zp13**2/zp11], [zp12 - zp13**2/zp11, zp11 - zp13**2/zp11]])*100/5280
    u = np.array([120+0j, -120+0j])
    for _ in range(500):
        i_1 = (loads.get("1", 0)/u[0]).conjugate()
        i_2 = (loads.get("2", 0)/u[1]).conjugate()
        i_12 = (loads.get("12", 0)/(u[0] - u[1])).conjugate()
        line = np.array([i_1 + i_12, i_2 - i_12])
        j1, j2 = -line
        ip = (VP/zc - (j1 - j2)/nt)/(1 + z0/zc)
        e = (VP - z0*ip)/nt
        v = np.array([e + z1*j1, -e + z2*j2])
        u = v - zp @ line
    return {"m2": v, "l3": u, "line": line, "primary": ip}

def gridlabd(v:np.ndarray) -> np.ndarray:
    """Physical line voltages in gridlabd's convention"""
    return np.array([v[0], -v[1]])

def triplex_voltages(m:Model, name:str) -> np.ndarray:
    return np.array([powerflow.get_complex(m, name, f"voltage_{x}") for x in "12"])

def test_registration():
    Model().read_glm("module powerflow;\n")
    node = Class.find("triplex_node", module="powerflow")
    assert node.parent.name == "powerflow_object" and node.find_property("voltage_12").unit == "V"
    assert node.find_property("voltage_A") is None and node.find_property("power_12").unit == "VA"
    for name in ("triplex_meter", "triplex_load"):
        assert Class.find(name, module="powerflow").parent.name == "triplex_node"
    assert Class.find("meter", module="powerflow").parent.name == "node"
    assert Class.find("meter", module="powerflow").find_property("bill_day").default == "15"
    m = Model()
    m.read_glm("module powerflow;\n")
    assert m.globals.get("powerflow::market_price_name") == "current_market.clearing_price"

def test_isa_node(helpers):
    m = helpers.model("object triplex_node { name t; phases AS; nominal_voltage 120; bustype SWING; }", lines=False)
    from powerflow._common import isa # pylint: disable=import-outside-toplevel
    assert isa(m, "t", "node") and isa(m, "t", "triplex_node") and not isa(m, "t", "link")

def test_split_phase_feeder(helpers):
    """Unbalanced 120 V and 240 V loads through a center-tapped transformer
    and a triplex line match the independent solution"""
    r = helpers.run(feeder(), lines=False)
    assert r.returncode == 0, r.stderr
    expected = reference(LOADS)
    for name in ("m2", "l3"):
        assert np.max(np.abs(triplex_voltages(r.model, name) - gridlabd(expected[name]))) < 1e-4, name
    m = r.model
    assert powerflow.get_complex(m, "l3", "voltage_12") == pytest.approx(expected["l3"][0] - expected["l3"][1])
    assert powerflow.get_complex(m, "l3", "voltage_N") == 0
    assert powerflow.get_complex(m, "t12", "current_in_A") == pytest.approx(expected["primary"])

def test_triplex_meter(helpers):
    """The meter's currents are the line currents (line 2 physical), the
    neutral current their negative sum, and its power the power into the
    line"""
    r = helpers.run(feeder(), lines=False)
    m = r.model
    expected = reference(LOADS)
    i1, i2 = expected["line"]
    assert powerflow.get_complex(m, "m2", "measured_current_1") == pytest.approx(i1, rel=1e-5)
    assert powerflow.get_complex(m, "m2", "measured_current_2") == pytest.approx(i2, rel=1e-5)
    assert powerflow.get_complex(m, "m2", "measured_current_N") == pytest.approx(-(i1 + i2), rel=1e-4)
    v1, v2 = expected["m2"]
    power = v1*i1.conjugate() + v2*i2.conjugate()
    assert powerflow.get_complex(m, "m2", "measured_power") == pytest.approx(power, rel=1e-5)
    assert powerflow.get_complex(m, "m2", "measured_voltage_12") == pytest.approx(v1 - v2, rel=1e-6)
    assert powerflow.get_double(m, "m2", "measured_demand") == pytest.approx(power.real, rel=1e-5)

def test_energy(helpers):
    """Energy over two hours of constant load, and the interval energy"""
    r = helpers.run(feeder("measured_energy_delta_timestep 3600;"), stop="2020-01-01 02:00:00", lines=False)
    assert r.returncode == 0, r.stderr
    p = powerflow.get_double(r.model, "m2", "measured_real_power")
    assert powerflow.get_double(r.model, "m2", "measured_real_energy") == pytest.approx(2*p)
    assert powerflow.get_double(r.model, "m2", "measured_real_energy_delta") == pytest.approx(p)
    assert powerflow.get_double(r.model, "m2", "measured_avg_voltage_mag_1_in_interval") == pytest.approx(abs(powerflow.get_complex(r.model, "m2", "voltage_1")))

def test_uniform_bill(helpers):
    r = helpers.run(feeder("bill_mode UNIFORM; price 0.1; monthly_fee 10; measured_energy_delta_timestep 3600;"), stop="2020-01-01 03:00:00", lines=False)
    m = r.model
    energy = powerflow.get_double(m, "m2", "measured_real_energy")/1000
    assert powerflow.get_double(m, "m2", "monthly_energy") == pytest.approx(energy)
    assert powerflow.get_double(m, "m2", "monthly_bill") == pytest.approx(10 + 0.1*energy)

@pytest.mark.parametrize("meter,message", [
    ("bill_mode TIERED; first_tier_price 0.1; first_tier_energy 500; second_tier_price 0.2; second_tier_energy 100;", "triplex_meter energy tiers quantity trend improperly"),
    ("bill_mode HOURLY;", "triplex_meter cannot use real time energy prices without a power market that publishes the next price"),
    ("power_market n1;", "triplex_meter::power_market object 'n1' does not publish 'current_market.clearing_price'"),
])
def test_price_errors(helpers, meter, message):
    r = helpers.run(feeder(meter), lines=False)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

def test_tier_fill(helpers):
    m = helpers.run(feeder("bill_mode TIERED; first_tier_price 0.1; first_tier_energy 500;"), lines=False).model
    assert powerflow.get_double(m, "m2", "third_tier_price") == 0.1 and powerflow.get_double(m, "m2", "third_tier_energy") == 500

def test_node_accumulators(helpers):
    """`power_1` ... of a triplex node give the solution of the same loads in
    a triplex_load"""
    glm = feeder(loads={}).replace("object triplex_load { name l3; phases AS; nominal_voltage 120;", "object triplex_node { name l3; phases AS; nominal_voltage 120; power_1 2000+500j; power_2 1500+300j; power_12 3000+1000j;")
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    assert np.max(np.abs(triplex_voltages(r.model, "l3") - gridlabd(reference(LOADS)["l3"]))) < 1e-4

def test_triplex_load_zip(helpers):
    m = helpers.run(feeder(loads={}, load="base_power_12 3000; power_fraction_12 0.5; impedance_fraction_12 0.5; power_pf_12 1; impedance_pf_12 1;"), lines=False).model
    assert powerflow.get_complex(m, "l3", "constant_power_12") == pytest.approx(1500)
    assert powerflow.get_complex(m, "l3", "constant_impedance_12") == pytest.approx(4*120**2/1500)
    assert powerflow.get_complex(m, "l3", "measured_voltage_12") == powerflow.get_complex(m, "l3", "voltage_12")

def test_zip_current_warning(helpers):
    r = helpers.run(feeder(loads={}, load="constant_current_1 5; base_power_1 1000; current_fraction_1 1;"), lines=False)
    assert any("ZIP fractions will override constant_current_X values" in x for x in helpers.warnings(r)), r.stderr

def test_missing_phase_s(helpers):
    r = helpers.run("object triplex_node { name t; phases A; nominal_voltage 120; bustype SWING; }", lines=False)
    assert any("Phases specified did not include phase S. Adding phase S." in x for x in helpers.warnings(r)), r.stderr
    assert r.model.get_property("t", "phases") == "AS"

def test_meter_power_consumption(helpers):
    with_meter = helpers.run(feeder("meter_power_consumption 100;", loads={}), lines=False).model
    p = powerflow.get_complex(with_meter, "t12", "power_in_A").real
    assert p == pytest.approx(100, rel=0.01)

def test_dc(helpers):
    r = helpers.run(feeder(), module="solver_method DC;", lines=False)
    assert r.returncode == 0, r.stderr
    assert abs(powerflow.get_complex(r.model, "m2", "measured_power").real - sum(LOADS.values()).real) < 1e-6

@pytest.mark.parametrize("method", ["FD_XB", "FD_BX"])
def test_fast_decoupled_transformer(helpers, method):
    """The fast-decoupled methods solve a center-tapped transformer with
    unbalanced loads at its secondary (they do not converge with triplex
    lines and unbalanced loads)"""
    glm = feeder(meter="power_1 2000+500j; power_12 3000+1000j;", loads={}).split("object triplex_line_conductor")[0]
    nr = helpers.run(glm, lines=False)
    fd = helpers.run(glm, module=f"solver_method {method};", lines=False)
    assert fd.returncode == 0, fd.stderr
    assert np.max(np.abs(triplex_voltages(fd.model, "m2") - triplex_voltages(nr.model, "m2"))) < 1e-6

#
# Meter
#
METER = """
object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
object test_line { name l01; phases ABCN; from n0; to m1; length 2000; }
object meter { name m1; phases ABCN; nominal_voltage 2401.7771; %s }
object test_line { name l12; phases ABCN; from m1; to n2; length 2500; }
object load { name n2; phases ABCN; nominal_voltage 2401.7771; constant_power_A 200000+100000j; constant_power_B 120000+60000j; constant_power_C 50000+30000j; }
"""

def test_meter_measurements(helpers):
    r = helpers.run(METER % "")
    assert r.returncode == 0, r.stderr
    m = r.model
    for x in "ABC":
        i = powerflow.get_complex(m, "l01", f"current_out_{x}")
        v = powerflow.get_complex(m, "m1", f"voltage_{x}")
        assert powerflow.get_complex(m, "m1", f"measured_current_{x}") == pytest.approx(i)
        assert powerflow.get_complex(m, "m1", f"measured_power_{x}") == pytest.approx(v*i.conjugate())
    total = sum(powerflow.get_complex(m, "m1", f"measured_power_{x}") for x in "ABC")
    assert powerflow.get_double(m, "m1", "measured_real_power") == pytest.approx(total.real)
    assert powerflow.get_complex(m, "m1", "measured_voltage_AB") == pytest.approx(powerflow.get_complex(m, "m1", "voltage_A") - powerflow.get_complex(m, "m1", "voltage_B"))

def test_meter_tiered_bill(helpers):
    r = helpers.run(METER % "bill_mode TIERED; price 0.1; first_tier_price 0.2; first_tier_energy 100; measured_energy_delta_timestep 3600;", stop="2020-01-01 02:00:00")
    m = r.model
    energy = powerflow.get_double(m, "m1", "measured_real_energy")/1000
    assert energy > 100
    assert powerflow.get_double(m, "m1", "monthly_bill") == pytest.approx(0.1*100 + 0.2*(energy - 100))

def test_swing_meter(helpers):
    """A swing meter measures the currents into the links it feeds"""
    glm = (METER % "").replace("object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }\nobject test_line { name l01; phases ABCN; from n0; to m1; length 2000; }\n", "").replace("nominal_voltage 2401.7771;  }", "nominal_voltage 2401.7771; bustype SWING; }")
    r = helpers.run(glm)
    assert r.returncode == 0, r.stderr
    assert powerflow.get_complex(r.model, "m1", "measured_current_A") == pytest.approx(powerflow.get_complex(r.model, "l12", "current_in_A"))
