"""Class `motor`: registration, initialization, the single-phase and
three-phase steady-state models in the solution, protection, and triplex
connections"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath
import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model

VNOM = 2401.7771
ALPHA = cmath.rect(1, 2*math.pi/3)

def feeder(motor:str, meter:str="") -> str:
    head = f"object meter {{ measured_energy_delta_timestep {meter}; " if meter else "object node { "
    return f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 20000; }}
{head}name n1; phases ABCN; nominal_voltage {VNOM}; }}
object motor {{ name m1; parent n1; nominal_voltage {VNOM}; {motor} }}
"""

def test_registration():
    Model().read_glm("module powerflow;\n")
    motor = Class.find("motor", module="powerflow")
    assert motor.parent.name == "node" and motor.trl == 1
    assert motor.find_property("base_power").default == "3500 W" and motor.find_property("Xc_run").default == "-2.779 ohm"
    assert motor.find_property("triplex_connection_type").default == "TRIPLEX_12"
    assert motor.find_property("psi_b").access == "HIDDEN"

def test_spim(helpers):
    """The SPIM's torque meets the mechanical torque, and the current it
    draws is solved with the node's final voltage"""
    r = helpers.run(feeder("phases BN; base_power 50000;"))
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("m1", "motor_status") == "RUNNING" and m.get_property("m1", "motor_operation_type") == "SINGLE-PHASE"
    assert powerflow.get_double(m, "m1", "electrical_torque") == pytest.approx(1.0448, abs=1e-6)
    vs = powerflow.get_complex(m, "m1", "Vs")
    assert vs == pytest.approx(powerflow.get_complex(m, "n1", "voltage_B")/VNOM, rel=1e-9)
    current = powerflow.get_complex(m, "m1", "Is")*50000/VNOM
    assert cmath.phase(powerflow.get_complex(m, "m1", "Is")) - cmath.phase(vs) == pytest.approx(cmath.phase(powerflow.get_complex(m, "m1", "Ids") + powerflow.get_complex(m, "m1", "Iqs")))
    assert powerflow.get_complex(m, "l01", "current_out_B") == pytest.approx(current, rel=1e-6)
    assert abs(powerflow.get_complex(m, "l01", "current_out_A")) < 1e-5

def test_tpim(helpers): # pylint: disable=too-many-locals
    """The TPIM's sequence fluxes are its steady state and its torque meets
    the load torque; its phase currents are drawn in the solution"""
    r = helpers.run(feeder("phases ABCN; base_power 300000;"))
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("m1", "motor_status") == "RUNNING" and m.get_property("m1", "motor_operation_type") == "THREE-PHASE"
    def get(prop:str) -> complex:
        return powerflow.get_complex(m, "m1", prop)
    assert powerflow.get_double(m, "m1", "electrical_torque") == pytest.approx(0.95, abs=1e-6)
    vas, vbs, vcs = (get(x) for x in ("Vas", "Vbs", "Vcs"))
    vap = (vas + ALPHA*vbs + ALPHA**2*vcs)/3
    rs, lm, ls, lr, s1 = (powerflow.get_double(m, "m1", x) for x in ("rs", "lm", "Ls", "Lr", "sigma1"))
    assert vap - (1j + rs/s1)*get("phips") + rs/s1*lm/lr*get("phipr") == pytest.approx(0, abs=1e-9)
    assert ls == pytest.approx(3.1) and lr == pytest.approx(3.08)
    base = 300000/VNOM/3
    for x, name in zip("ABC", ("Ias", "Ibs", "Ics")):
        assert powerflow.get_complex(m, "l01", f"current_out_{x}") == pytest.approx(get(name)*base, rel=1e-6)
    assert get("Smt") == pytest.approx((vap*get("Ips").conjugate() + (vas + ALPHA**2*vbs + ALPHA*vcs)/3*get("Ins_cj"))*300000)

def test_tpim_stationary(helpers):
    m = helpers.run(feeder("phases ABCN; TPIM_initial_status STATIONARY;")).model
    assert powerflow.get_double(m, "m1", "omgr0") == 0 and powerflow.get_double(m, "m1", "TL") == 0
    assert m.get_property("m1", "motor_status") == "STALLED"
    assert powerflow.get_double(m, "m1", "delta_mode_voltage_trigger") == 110

def test_override_off(helpers):
    m = helpers.run(feeder("phases AN; motor_override OFF;")).model
    assert m.get_property("m1", "motor_status") == "OFF" and m.get_property("m1", "motor_status_number") == "3"
    assert powerflow.get_complex(m, "m1", "Is") == 0
    assert abs(powerflow.get_complex(m, "l01", "current_out_A")) < 1e-5

def test_trip(helpers):
    """A stalled motor trips after trip_time and reconnects after
    reconnect_time"""
    glm = feeder("phases AN; mechanical_torque 10; trip_time 10; reconnect_time 30;", meter="5")
    m = helpers.run(glm, stop="2020-01-01 00:00:05").model
    assert m.get_property("m1", "motor_status") == "STALLED" and powerflow.get_double(m, "m1", "trip") == 5
    m = helpers.run(glm, stop="2020-01-01 00:00:10").model
    assert m.get_property("m1", "motor_status") == "TRIPPED" and m.get_property("m1", "motor_trip") == "TRUE"
    assert abs(powerflow.get_complex(m, "l01", "current_out_A")) < 1e-5
    m = helpers.run(glm, stop="2020-01-01 00:00:40").model
    assert m.get_property("m1", "motor_trip") == "FALSE" and m.get_property("m1", "motor_status") == "STALLED"

def test_phase_count(helpers):
    r = helpers.run(feeder("phases ABN;"))
    assert any("only single-phase or three-phase motors are support" in x for x in helpers.errors(r)), r.stderr

@pytest.mark.parametrize("ttype, slot", [("TRIPLEX_1N", 0), ("TRIPLEX_2N", 1), ("TRIPLEX_12", 2)])
def test_triplex(helpers, ttype, slot):
    """A triplex motor draws its current on line 1, line 2, or line 1 to
    line 2 (twice the nominal voltage)"""
    glm = f"""
object triplex_node {{ name t0; phases AS; nominal_voltage 120; bustype SWING; }}
object triplex_line_conductor {{ name tc; resistance 0.97; geometric_mean_radius 0.0111; }}
object triplex_line_configuration {{ name tlc; conductor_1 tc; conductor_2 tc; conductor_N tc; insulation_thickness 0.08; diameter 0.368; }}
object triplex_line {{ name tl; phases AS; from t0; to t1; length 100; configuration tlc; }}
object triplex_node {{ name t1; phases AS; nominal_voltage 120; }}
object motor {{ name m1; phases AS; parent t1; nominal_voltage 120; triplex_connection_type {ttype}; }}
"""
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    v = [powerflow.get_complex(m, "t1", f"voltage_{x}") for x in ("1", "2")]
    vs = (v[0], v[1], v[0] + v[1])[slot]/(240 if slot == 2 else 120)
    assert powerflow.get_complex(m, "m1", "Vs") == pytest.approx(vs, rel=1e-9)
    assert m.get_property("m1", "motor_status") == "RUNNING"
    current = powerflow.get_complex(m, "m1", "Is")*3500/(240 if slot == 2 else 120)
    out = [powerflow.get_complex(m, "tl", f"current_out_{x}") for x in "AB"]
    expected = ((current, 0), (0, current), (current, current))[slot]
    assert np.abs(np.array(out) - np.array(expected)).max() < 1e-4 # the solver's mismatch tolerance, 0.01 VA
