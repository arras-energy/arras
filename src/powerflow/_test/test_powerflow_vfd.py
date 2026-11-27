"""Class `vfd`: registration, initialization, the output voltage source,
the input power, the frequency ramp, and an off drive"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.vfd import efficiency

VNOM = 2401.7771

def feeder(vfd:str, meter:str="") -> str:
    head = f"object meter {{ measured_energy_delta_timestep {meter}; " if meter else "object node { "
    return f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
{head}name n1; phases ABCN; nominal_voltage {VNOM}; }}
object vfd {{ name v1; phases ABCN; from n1; to n2; {vfd} }}
object load {{ name n2; phases ABCN; nominal_voltage {VNOM}; constant_impedance_A 50; constant_impedance_B 50; constant_impedance_C 50; }}
object test_line {{ name l23; phases ABCN; from n2; to n3; length 1000; }}
object load {{ name n3; phases ABCN; nominal_voltage {VNOM}; constant_power_A 20000; constant_power_B 20000; constant_power_C 20000; }}
"""

def test_registration():
    Model().read_glm("module powerflow;\n")
    vfd = Class.find("vfd", module="powerflow")
    assert vfd.parent.name == "link" and vfd.trl == 7
    assert vfd.find_property("rated_horse_power").unit == "hp" and vfd.find_property("stable_time").default == "1.45 s"
    assert vfd.find_property("vfd_state").default == "OFF"

def test_efficiency():
    assert efficiency(50.138) == pytest.approx(96.014)
    assert efficiency(100.0) == pytest.approx(sum(c*((100 - 50.138)/37.009)**k for k, c in enumerate((96.014, 3.8759, -4.4504, -3.2079, 8.7113, 0.97848, -8.2828, 3.497))))

@pytest.mark.parametrize("method", ["NR", "FD_XB"])
def test_steady(helpers, method):
    """The output is a balanced source at rated voltage times f/f_nominal
    (line to neutral); the input draws the output power over the
    efficiency, balanced"""
    r = helpers.run(feeder("desired_motor_speed 1500;"), module=f"solver_method {method};")
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("v1", "vfd_state") == "STEADY_STATE"
    assert powerflow.get_double(m, "v1", "desired_output_frequency") == 50 and powerflow.get_double(m, "v1", "current_output_frequency") == 50
    assert powerflow.get_double(m, "v1", "rated_output_voltage") == pytest.approx(VNOM*math.sqrt(3))
    v2 = helpers.voltages(m, "n2")
    assert np.abs(v2) == pytest.approx([VNOM*50/60]*3)
    assert np.angle(v2[1]/v2[0]) == pytest.approx(-2*math.pi/3) and np.angle(v2[2]/v2[0]) == pytest.approx(2*math.pi/3)
    out = powerflow.get_complex(m, "v1", "power_out")
    load = sum(abs(v)**2/50 for v in v2) + sum(powerflow.get_complex(m, "l23", f"power_in_{x}") for x in "ABC")
    assert out == pytest.approx(load, rel=1e-6)
    eff = powerflow.get_double(m, "v1", "efficiency")
    assert eff == pytest.approx(efficiency(100*50/60))
    for x in "ABC":
        pin = powerflow.get_complex(m, "v1", f"power_in_{x}")
        assert pin == pytest.approx(out*100/eff/3)
        assert powerflow.get_complex(m, "v1", f"current_in_{x}") == pytest.approx((pin/powerflow.get_complex(m, "n1", f"voltage_{x}")).conjugate())
    assert powerflow.get_complex(m, "l01", "power_out") == pytest.approx(powerflow.get_complex(m, "v1", "power_in"), rel=1e-6)

def test_ramp(helpers):
    """A drive that starts fills its window with the desired frequency one
    second at a time, from 3 Hz"""
    glm = feeder("desired_motor_speed 1500; stable_time 10;", meter="1")
    m = helpers.run(glm).model
    assert m.get_property("v1", "vfd_state") == "CHANGING"
    assert powerflow.get_double(m, "v1", "current_output_frequency") == pytest.approx((50 + 9*3)/10)
    m = helpers.run(glm, stop="2020-01-01 00:00:05").model
    assert powerflow.get_double(m, "v1", "current_output_frequency") == pytest.approx((6*50 + 4*3)/10)
    assert np.abs(helpers.voltages(m, "n2")) == pytest.approx([VNOM*31.2/60]*3)
    m = helpers.run(glm, stop="2020-01-01 00:00:20").model
    assert m.get_property("v1", "vfd_state") == "STEADY_STATE" and powerflow.get_double(m, "v1", "current_output_frequency") == 50

def test_ramp_events(helpers):
    """Without other events, the drive's next event is when its window
    fills"""
    m = helpers.run(feeder("desired_motor_speed 1500; stable_time 10;"), stop="2020-01-01 00:01:00").model
    assert m.get_property("v1", "vfd_state") == "STEADY_STATE" and powerflow.get_double(m, "v1", "current_output_frequency") == 50

def test_off(helpers):
    """An off drive takes out the nodes it feeds and draws nothing"""
    r = helpers.run(feeder("desired_motor_speed 0;"))
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("v1", "vfd_state") == "OFF"
    assert np.abs(helpers.voltages(m, "n2")).max() == 0 and np.abs(helpers.voltages(m, "n3")).max() == 0
    assert powerflow.get_complex(m, "v1", "power_in") == 0 and powerflow.get_double(m, "v1", "efficiency") == 0
    assert abs(powerflow.get_complex(m, "l01", "power_out")) < 1e-3

def test_start_steady(helpers):
    m = helpers.run(feeder("desired_motor_speed 1700; vfd_state STEADY_STATE;")).model
    assert powerflow.get_double(m, "v1", "current_output_frequency") == pytest.approx(1700*4/120)

@pytest.mark.parametrize("extra, message", [
    ("stable_time 0;", "the stableTime must be positive"),
    ("motor_poles 0;", "motor_poles must be positive and non-zero!"),
    ("rated_horse_power -1;", "rated_horse_power must be positive and non-zero!"),
])
def test_init_errors(helpers, extra, message):
    r = helpers.run(feeder(extra))
    assert any(message in x for x in helpers.errors(r)), r.stderr

def test_three_phase(helpers):
    r = helpers.run(feeder("").replace("name v1; phases ABCN;", "name v1; phases ABN;"))
    assert any("Must be three-phase!" in x for x in helpers.errors(r)), r.stderr

def test_warnings(helpers):
    r = helpers.run(feeder("desired_motor_speed 1200; rated_output_voltage 4000;"))
    warnings = helpers.warnings(r)
    assert any("rated_output_voltage does not match the TO node nominal voltage" in x for x in warnings)
    assert any("nominal_output_frequency is not set or is negative - defaulting to system nominal" in x for x in warnings)
    assert any("VFD currently at 66.666667% of rated speed" in x for x in warnings)
