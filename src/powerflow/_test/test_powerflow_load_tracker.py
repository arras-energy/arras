"""Class `load_tracker`: registration, initialization, the feedback of
each property type and operation, output tracking, deadband, and the
extra pass"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath

import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.load_tracker import LoadTracker

VNOM = 2401.7771
T0 = 1577836800

def feeder(tracker:str) -> str:
    return f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 2000; }}
object load {{ name n1; phases ABCN; nominal_voltage {VNOM}; constant_power_A 300000+400000j; }}
object load_tracker {{ name lt; target l01; target_property power_in_A; {tracker} }}
"""

def test_registration():
    Model().read_glm("module powerflow;\n")
    lt = Class.find("load_tracker", module="powerflow")
    assert lt.trl == 9 and lt.parent is None
    assert lt.find_property("operation").default == "MAGNITUDE" and lt.find_property("deadband").default == "1.0"

@pytest.mark.parametrize("operation", ["REAL", "IMAGINARY", "MAGNITUDE", "ANGLE"])
def test_feedback(helpers, operation):
    """The feedback of a complex property by operation"""
    r = helpers.run(feeder(f"setpoint 0; full_scale 1e12; operation {operation};"))
    assert r.returncode == 0, r.stderr
    m = r.model
    value = powerflow.get_complex(m, "l01", "power_in_A")
    expected = {"REAL": value.real, "IMAGINARY": value.imag, "MAGNITUDE": abs(value), "ANGLE": cmath.phase(value)}[operation]
    assert powerflow.get_double(m, "lt", "feedback") == pytest.approx(expected)
    assert powerflow.get_double(m, "lt", "output") == 0

def test_tracking(helpers):
    """The output moves toward the setpoint until the feedback is in the
    deadband; another pass is asked for while it is not"""
    m = helpers.run(feeder("setpoint 0; full_scale 100;").replace("target l01; target_property power_in_A;", "target n1; target_property nominal_voltage;")).model
    m.set_property("lt", "setpoint", "50")
    m.set_property("n1", "nominal_voltage", "40")
    LoadTracker.presync(m, "lt", T0)
    assert powerflow.get_double(m, "lt", "output") == 0 # the initial setpoint/full_scale, scaled
    m.set_property("lt", "output", "0.4")
    LoadTracker.presync(m, "lt", T0)
    assert powerflow.get_double(m, "lt", "output") == pytest.approx(0.4*(1 + 10/40))
    assert LoadTracker.postsync(m, "lt", T0) == T0
    m.set_property("n1", "nominal_voltage", "49.5")
    assert LoadTracker.postsync(m, "lt", T0) == powerflow._common.TS_NEVER # pylint: disable=protected-access
    LoadTracker.presync(m, "lt", T0 + 1)
    assert powerflow.get_double(m, "lt", "output") == pytest.approx(0.5) # inside the deadband

def test_damping_and_zero_feedback(helpers):
    m = helpers.run(feeder("setpoint 0; full_scale 100; damping 1;").replace("target l01; target_property power_in_A;", "target n1; target_property nominal_voltage;")).model
    m.set_property("lt", "setpoint", "60")
    m.set_property("lt", "output", "0.5")
    m.set_property("n1", "nominal_voltage", "80")
    LoadTracker.presync(m, "lt", T0)
    assert powerflow.get_double(m, "lt", "output") == pytest.approx(0.5*(1 - 20/80/2))
    m.set_property("n1", "nominal_voltage", "0")
    LoadTracker.presync(m, "lt", T0)
    assert powerflow.get_double(m, "lt", "output") == pytest.approx(0.6)

def test_integer(helpers):
    """An integer property (a regulator's tap)"""
    glm = f"""
object regulator_configuration {{ name rc; connect_type WYE_WYE; band_center 2401; band_width 40; raise_taps 16; lower_taps 16; regulation 0.10; Control MANUAL; }}
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object regulator {{ name r01; phases ABCN; from n0; to n1; configuration rc; tap_A 3; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object load_tracker {{ name lt; target r01; target_property tap_A; setpoint 3; full_scale 16; }}
"""
    r = helpers.run(glm, lines=False)
    assert r.returncode == 0, r.stderr
    assert powerflow.get_double(r.model, "lt", "feedback") == 3 and powerflow.get_double(r.model, "lt", "output") == pytest.approx(3/16)

def test_unsupported_type(helpers):
    r = helpers.run(feeder("full_scale 1e12;").replace("target_property power_in_A;", "target_property violation_detected;"))
    assert any("Unsupported property type." in x for x in helpers.errors(r)), r.stderr

@pytest.mark.parametrize("tracker, message", [
    ("full_scale 0;", "The full_scale property must be non-zero"),
    ("full_scale 1e12; deadband 60;", "Deadband must be in the range 1% to 50%"),
    ("full_scale 1e12; damping -1;", "Damping must greater than or equal to 0.0"),
    ("full_scale 1e12; target_property nothing;", 'Unable to find property "nothing" in object l01'),
    ("full_scale 1e12; target_property status;", "Unsupported property type.  Supported types are complex, double and integer"),
])
def test_init_errors(helpers, tracker, message):
    glm = feeder(tracker)
    if "target_property" in tracker:
        glm = glm.replace("target_property power_in_A;", "")
    r = helpers.run(glm)
    assert any(message in x and "init_load_tracker(obj=" in x for x in helpers.errors(r)), r.stderr

def test_no_target(helpers):
    r = helpers.run(feeder("full_scale 1e12;").replace("target l01;", ""))
    assert any("Target object not set" in x for x in helpers.errors(r)), r.stderr
