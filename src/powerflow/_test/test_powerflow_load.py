"""Classes `load` and `capacitor`: registration, initialization, load
terms, solutions checked against independent computations, and capacitor
control"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath
import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.load import Load
from powerflow.capacitor import Capacitor

VNOM = 2401.7771

FEEDER = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
object load {{ name n1; phases ABCN; nominal_voltage {VNOM};
    constant_power_A 200000+100000j; constant_power_B_real 120000; constant_power_B_reac 60000; constant_power_C 50000+30000j; }}
object test_line {{ name l12; phases ABCN; from n1; to n2; length 2500; }}
object load {{ name n2; phases ABCN; nominal_voltage {VNOM};
    constant_power_AB 100000+40000j; constant_current_C 15+5j; constant_impedance_B {1/(0.002+0.0005j):.12g}; }}
""".replace("(", "").replace(")", "")
"""The unbalanced feeder of test_powerflow_flows.py with its loads in
`load` objects"""

LOADS = {
    "n0": {},
    "n1": {"S": (200e3+100e3j, 120e3+60e3j, 50e3+30e3j)},
    "n2": {"D": (100e3+40e3j, 0, 0), "I": (0, 0, 15+5j), "Y": (0, 0.002+0.0005j, 0)},
}
LINES = [("n0", "n1", 2000), ("n1", "n2", 2500)]

def test_registration():
    Model().read_glm("module powerflow;\n")
    load = Class.find("load", module="powerflow")
    assert load.parent.name == "node" and load.trl == 9
    assert load.find_property("constant_power_A").unit == "VA" and load.find_property("constant_power_A_reac").unit == "VAr"
    assert load.find_property("constant_impedance_CA_real").unit == "Ohm" and load.find_property("load_class").default == "U"
    assert load.find_property("impedance_fraction_C").unit == "pu"
    cap = Class.find("capacitor", module="powerflow")
    assert cap.parent.name == "node" and cap.find_property("control").default == "MANUAL"
    assert cap.find_property("control_level").default == "INDIVIDUAL" and cap.find_property("switchB").default == "OPEN"
    assert cap.find_property("cap_A_switch_count").default == "-1"

@pytest.mark.parametrize("method", ["NR", "FD_BX"])
def test_load_feeder(helpers, method):
    """Loads in `load` objects give the independent solution of the same
    loads in nodes"""
    r = helpers.run(FEEDER, module=f"solver_method {method};")
    assert r.returncode == 0, r.stderr
    expected = helpers.reference(LOADS, LINES, "n0")
    for name in ("n1", "n2"):
        assert np.max(np.abs(helpers.voltages(r.model, name) - expected[name])) < 1e-3, name
    m = r.model
    assert powerflow.get_complex(m, "n1", "constant_power_B") == 120000+60000j
    assert powerflow.get_complex(m, "n2", "measured_voltage_A") == helpers.voltages(m, "n2")[0]
    assert powerflow.get_complex(m, "n2", "measured_voltage_AB") == pytest.approx(helpers.voltages(m, "n2")[0] - helpers.voltages(m, "n2")[1])

def test_parts_change(helpers):
    """A change to a part changes the complex load and the solution"""
    m = helpers.run(FEEDER).model
    m.set_property("n1", "constant_power_A_reac", "0")
    Load.before_solve(m, "n1", 1)
    assert powerflow.get_complex(m, "n1", "constant_power_A") == 200000
    assert Load.load_terms(m, "n1")[("power", "A")] == 200000

def test_delta_phases(helpers):
    """With phase D, `constant_power_A` is the AB load"""
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABC; from n0; to n1; length 2000; }}
object load {{ name n1; phases ABCD; nominal_voltage {VNOM}; constant_power_A 100000+40000j; }}
"""
    r = helpers.run(glm)
    assert r.returncode == 0, r.stderr
    expected = helpers.reference({"n0": {}, "n1": {"D": (100e3+40e3j, 0, 0)}}, [("n0", "n1", 2000)], "n0")
    assert np.max(np.abs(helpers.voltages(r.model, "n1") - expected["n1"])) < 1e-3

@pytest.mark.parametrize("phases, shift, scale", [("ABCN", 0.0, 1.0), ("ABCD", math.pi/6, math.sqrt(3))])
def test_zip(helpers, phases, shift, scale):
    """ZIP form: power, current, and impedance fractions of the base power
    at their power factors, at the nominal voltage across the load
    (line-to-line when delta-connected), so that each draws its share of
    the base power at nominal voltage"""
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object load {{ name n1; phases {phases}; parent n0; base_power_B 100000; power_fraction_B 0.5; current_fraction_B 0.3; impedance_fraction_B 0.2;
    power_pf_B 0.9; current_pf_B -0.8; impedance_pf_B 1.0; }}
"""
    m = helpers.run(glm, lines=False).model
    p = 50000*0.9
    assert powerflow.get_complex(m, "n1", "constant_power_B") == pytest.approx(complex(p, p*math.sqrt(1/0.81 - 1)))
    s = complex(30000*0.8, -30000*0.8*math.sqrt(1/0.64 - 1))
    i = s.conjugate()/(VNOM*scale)
    assert powerflow.get_complex(m, "n1", "constant_current_B") == pytest.approx(cmath.rect(abs(i), cmath.phase(i) - 2*math.pi/3 + shift))
    assert powerflow.get_complex(m, "n1", "constant_impedance_B") == pytest.approx((VNOM*scale)**2/20000)
    vload = cmath.rect(VNOM*scale, -2*math.pi/3 + shift)
    assert vload*powerflow.get_complex(m, "n1", "constant_current_B").conjugate() == pytest.approx(s)
    assert abs(vload)**2/powerflow.get_complex(m, "n1", "constant_impedance_B").conjugate() == pytest.approx(20000)

def test_zip_sum_warning(helpers):
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object load {{ name n1; phases ABCN; parent n0; base_power_A 1000; power_fraction_A 0.5; current_fraction_A 0.1; power_pf_A 1; }}
"""
    r = helpers.run(glm, lines=False)
    assert any("ZIP components on phase A did not sum to 1" in x for x in helpers.warnings(r)), r.stderr
    assert powerflow.get_double(r.model, "n1", "power_fraction_A") == pytest.approx(0.9)

def test_frequency_dependence(helpers):
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object load {{ name n1; phases ABCN; parent n0; constant_impedance_A 10+5j; constant_impedance_B 10-5j; }}
"""
    m = helpers.run(glm, module="enable_frequency_dependence true; current_frequency 61;", lines=False).model
    terms = Load.load_terms(m, "n1")
    assert terms[("shunt", "A")] == pytest.approx(1/complex(10, 5*61/60))
    assert terms[("shunt", "B")] == pytest.approx(1/complex(10, -5*60/61))

def test_load_triplex(helpers):
    r = helpers.run(f"object load {{ name n1; phases AS; nominal_voltage 120; bustype SWING; }}", lines=False)
    assert r.returncode != 0
    assert any("Load objects do not support triplex connections at this time!" in x for x in helpers.errors(r)), r.stderr

#
# Capacitor
#
def capacitor(extra:str="", load:str="power_A 1500000+1200000j; power_B 1500000+1200000j; power_C 1500000+1200000j;") -> str:
    return f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 5000; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; {load} }}
object capacitor {{ name c1; phases ABCN; parent n1; capacitor_A 300000; capacitor_B 300000; capacitor_C 300000; {extra} }}
"""

def switches(m:Model) -> list[str]:
    return [m.get_property("c1", f"switch{x}") for x in "ABC"]

def test_manual_closed(helpers):
    """A closed capacitor is the shunt admittance `j Q / Vnom^2`: the same
    solution as a node with that shunt"""
    r = helpers.run(capacitor("switchA CLOSED; switchB CLOSED; switchC CLOSED;"))
    assert r.returncode == 0, r.stderr
    m = r.model
    y = 300000j/VNOM**2
    assert Capacitor.load_terms(m, "c1")[("shunt", "B")] == pytest.approx(y)
    shunt = f"shunt_A {y.real}+{y.imag}j; shunt_B {y.real}+{y.imag}j; shunt_C {y.real}+{y.imag}j;"
    same = helpers.run(capacitor("capacitor_A 0.001; capacitor_B 0.001; capacitor_C 0.001;").replace("power_A 1500000", shunt + " power_A 1500000")).model
    assert np.max(np.abs(helpers.voltages(m, "n1") - helpers.voltages(same, "n1"))) < 0.01
    assert all(abs(v) > 0 for v in helpers.voltages(m, "n1"))

def test_manual_delay(helpers):
    """A manual switch change takes effect after the time delay"""
    m = helpers.run(capacitor("time_delay 60;")).model
    m.set_property("c1", "switchA", "CLOSED")
    Capacitor.before_solve(m, "c1", 1577836800 + 10)
    assert switches(m)[0] == "OPEN"
    Capacitor.before_solve(m, "c1", 1577836800 + 69)
    assert switches(m)[0] == "OPEN"
    Capacitor.before_solve(m, "c1", 1577836800 + 70)
    assert switches(m)[0] == "CLOSED"

def test_volt_control(helpers):
    """VOLT: a voltage below the low set point closes the capacitors"""
    r = helpers.run(capacitor("control VOLT; pt_phase ABC; voltage_set_low 2350; voltage_set_high 2600;"), stop="2020-01-01 00:01:00")
    assert r.returncode == 0, r.stderr
    assert switches(r.model) == ["CLOSED"]*3
    assert [float(r.model.get_property("c1", f"cap_{x}_switch_count")) for x in "ABC"] == [1, 1, 1]

def test_var_control_bank(helpers):
    """VAR, BANK: the reactive power into the monitored link above the high
    set point closes every capacitor after the dwell time"""
    glm = capacitor("control VAR; control_level BANK; pt_phase A; VAr_set_low 100000; VAr_set_high 800000; remote_sense l01; dwell_time 30;")
    early = helpers.run(glm, stop="2020-01-01 00:00:20")
    late = helpers.run(glm, stop="2020-01-01 00:01:00")
    assert early.returncode == 0 and late.returncode == 0, early.stderr + late.stderr
    assert switches(early.model) == ["OPEN"]*3
    assert switches(late.model) == ["CLOSED"]*3

def test_delta_on_wye(helpers):
    """A delta-connected capacitor on a wye node is a phase-to-phase shunt"""
    m = helpers.run(capacitor("phases_connected ABCD; switchA CLOSED;")).model
    assert Capacitor.load_terms(m, "c1") == {("shunt", "AB"): pytest.approx(300000j/VNOM**2)}

@pytest.mark.parametrize("extra,message", [
    ("control VAR; pt_phase A;", "VAR, VARVOLT, or CURRENT control on capacitor:3 requires a remote link to monitor."),
    ("control VOLT; pt_phase A; voltage_set_low 2500; voltage_set_high 2400;", "The lower voltage limit of capacitor:3 is larger than the high limit setpoint!"),
    ("control VOLT; voltage_set_low 2300; voltage_set_high 2400;", "Capacitor:3 is set to an automatic scheme, but is not monitoring any phases."),
    ("control VARVOLT; pt_phase A; remote_sense_B n1;", "Please set the remote sensing location on capacitor:3 under \"remote_sense\""),
])
def test_capacitor_init_errors(helpers, extra, message):
    r = helpers.run(capacitor(extra))
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

def test_wye_on_delta(helpers):
    glm = f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object capacitor {{ name c1; phases ABCD; parent n0; phases_connected ABCN; capacitor_A 1000; }}
"""
    r = helpers.run(glm, lines=False)
    assert any("Capacitor:1 is Wye-connected on a Delta-connected node." in x for x in helpers.errors(r)), r.stderr

def test_no_capacitance(helpers):
    r = helpers.run(capacitor("capacitor_A 0; capacitor_B 0; capacitor_C 0;"))
    assert any("does not have any capacitance values defined!" in x for x in helpers.errors(r)), r.stderr
