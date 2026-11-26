"""Class `volt_var_control`: registration, initialization, regulator tap
control (individual and banked), capacitor switching (unsigned and
signed power factor), and the mode changes"""
# pylint: disable=missing-function-docstring,line-too-long

import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.volt_var_control import VoltVarControl, size_sort

VNOM = 2401.7771
CAPS = """
object capacitor {{ name c1; phases ABCN; parent n2; phases_connected ABCN; capacitor_A 300000; capacitor_B 300000; capacitor_C 300000; pt_phase A; control {control}; switchA OPEN; switchB OPEN; switchC OPEN; }}
object capacitor {{ name c2; phases ABCN; parent n2; phases_connected ABCN; capacitor_A 600000; capacitor_B 600000; capacitor_C 600000; pt_phase A; control {control}; switchA OPEN; switchB OPEN; switchC OPEN; }}
"""
WIDE = "minimum_voltages 2000; maximum_voltages 2800; desired_voltages 2300; max_vdrop 1000; low_load_deadband 500; high_load_deadband 500;"
"""Settings that keep the regulator still"""

def feeder(vvc:str, level:str="INDIVIDUAL", pt:str="ABC", caps:bool=True, control:str="OUTPUT_VOLTAGE", cap_control:str="MANUAL") -> str: # pylint: disable=too-many-arguments,too-many-positional-arguments
    return f"""
object regulator_configuration {{ name rc; connect_type WYE_WYE; band_center 2401; band_width 40; time_delay 30; dwell_time 15;
    raise_taps 16; lower_taps 16; regulation 0.10; Control {control}; control_level {level}; PT_phase {pt}; CT_phase {pt}; }}
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object regulator {{ name r01; phases ABCN; from n0; to n1; configuration rc; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object test_line {{ name l12; phases ABCN; from n1; to n2; length 5000; }}
object node {{ name n2; phases ABCN; nominal_voltage {VNOM}; power_A 500000+400000j; power_B 500000+400000j; power_C 500000+400000j; }}
{CAPS.format(control=cap_control) if caps else ""}
object volt_var_control {{ name vvc; regulator_list r01; {'capacitor_list "c1,c2";' if caps else ""} voltage_measurements n2; {vvc} }}
"""

def taps(m:Model) -> list[int]:
    return [int(m.get_property("r01", f"tap_{x}")) for x in "ABC"]

def test_registration():
    Model().read_glm("module powerflow;\n")
    vvc = Class.find("volt_var_control", module="powerflow")
    assert vvc.parent is None and vvc.find_property("phases") is None and vvc.trl == 0
    assert vvc.find_property("control_method").default == "ACTIVE" and vvc.find_property("desired_pf").default == "0.98"
    assert vvc.find_property("capacitor_delay").default == "5 s" and vvc.find_property("voltage_measurements").ptype == "char1024"

def test_size_sort():
    assert size_sort([1, 3, 2, 3]) == [3, 1, 2, 0]
    assert size_sort([]) == [] and size_sort([5]) == [0]

def test_defaults(helpers):
    """Default limits from the regulator's to node, drop and deadbands from
    the tap step, the link and phases from the first regulator; regulators
    and capacitors set to MANUAL"""
    r = helpers.run(feeder(""))
    assert r.returncode == 0, r.stderr
    m = r.model
    warnings = helpers.warnings(r)
    assert any("A link to monitor power-factor was not specified, using first regulator." in x for x in warnings)
    assert any("Power factor monitored phases not set - defaulting to substation_link phases" in x for x in warnings)
    state = powerflow._common.object_state(m, "vvc") # pylint: disable=protected-access
    step = 2401*0.10/16
    assert state["minimum"] == [pytest.approx(0.95*VNOM)] and state["desired"] == [pytest.approx(VNOM)]
    assert state["step_up"] == [pytest.approx(step)] and state["vdrop"] == [pytest.approx(1.5*step)] and state["vbw_low"] == [pytest.approx(2*step)]
    assert state["caps"] == ["c2", "c1"] and state["sizes"] == [1800000, 900000] and state["reg_delay"] == [30]
    assert state["link"] == "r01" and m.get_property("vvc", "pf_phase") in ("A|B|C", "ABC")
    assert m.get_property("rc", "Control") == "MANUAL" and m.get_property("c1", "control") == "MANUAL"

def test_raise_individual(helpers):
    """A low end voltage raises each phase one step per regulator delay"""
    glm = feeder("minimum_voltages 2300; maximum_voltages 2550; desired_voltages 2400;", caps=False)
    assert taps(helpers.run(glm).model) == [1, 1, 1]
    assert taps(helpers.run(glm, stop="2020-01-01 00:00:30").model) == [2, 2, 2]
    m = helpers.run(glm, stop="2020-01-01 00:10:00").model
    later = helpers.run(glm, stop="2020-01-01 00:20:00").model
    assert taps(later) == taps(m) # settled in the deadband
    step = 2401*0.10/16
    assert all(2400 - 2*step <= abs(v) <= 2400 + 2*step for v in helpers.voltages(m, "n2"))

def test_banked(helpers):
    """A banked regulator moves all three taps by its PT phase"""
    glm = feeder("minimum_voltages 2300; maximum_voltages 2550; desired_voltages 2400;", level="BANK", pt="A", caps=False)
    m = helpers.run(glm, stop="2020-01-01 00:01:00").model
    assert taps(m) == [3, 3, 3]

def test_lower(helpers):
    """A high voltage lowers the taps (twice at the start: the mode change
    makes every regulator due again at the next pass, as in gridlabd)"""
    glm = feeder("minimum_voltages 2000; maximum_voltages 2380; desired_voltages 2300;", caps=False).replace("power_A 500000+400000j; power_B 500000+400000j; power_C 500000+400000j;", "")
    assert taps(helpers.run(glm).model) == [-2, -2, -2]
    assert taps(helpers.run(glm, stop="2020-01-01 00:00:30").model) == [-3, -3, -3]

def test_capacitors_unsigned(helpers):
    """Below the desired power factor, the largest open capacitor whose
    d_max share is below the reactive power closes; a closed one whose
    d_min share is above it opens after the capacitor delay"""
    glm = feeder(WIDE)
    m = helpers.run(glm).model
    assert taps(m) == [0, 0, 0]
    assert [m.get_property(c, "switchA") for c in ("c1", "c2")] == ["OPEN", "CLOSED"]
    assert [m.get_property("c2", f"switch{x}") for x in "ABC"] == ["CLOSED"]*3
    m = helpers.run(glm, stop="2020-01-01 00:00:05").model
    assert [m.get_property(c, "switchA") for c in ("c1", "c2")] == ["OPEN", "OPEN"]

def test_capacitors_satisfied(helpers):
    m = helpers.run(feeder(WIDE + " desired_pf 0.5;"), stop="2020-01-01 00:00:10").model
    assert [m.get_property(c, "switchA") for c in ("c1", "c2")] == ["OPEN", "OPEN"]

def test_capacitors_signed(helpers):
    """Signed: a lagging power factor adds the first capacitor whose d_max
    share is below the reactive power to correct"""
    m = helpers.run(feeder(WIDE + " pf_signed TRUE; desired_pf 0.95;")).model
    assert [m.get_property(c, "switchA") for c in ("c1", "c2")] == ["OPEN", "CLOSED"]

def test_standby(helpers):
    """STANDBY changes nothing; switching ACTIVE to STANDBY restores the
    control modes"""
    m = helpers.run(feeder(WIDE + " control_method STANDBY;", cap_control="VOLT; voltage_set_low 2000; voltage_set_high 2600; time_delay 1")).model
    assert m.get_property("rc", "Control") == "OUTPUT_VOLTAGE" and m.get_property("c1", "control") == "VOLT"
    m = helpers.run(feeder(WIDE, cap_control="VOLT; voltage_set_low 2000; voltage_set_high 2600; time_delay 1")).model
    assert m.get_property("rc", "Control") == "MANUAL" and m.get_property("c1", "control") == "MANUAL"
    m.set_property("vvc", "control_method", "STANDBY")
    VoltVarControl.presync(m, "vvc", 1577836900)
    assert m.get_property("rc", "Control") == "OUTPUT_VOLTAGE" and m.get_property("c1", "control") == "VOLT"

def test_all_manual(helpers):
    """With every regulator MANUAL the controller starts ACTIVE and the
    link defaults to the first regulator (gridlabd indexes past the list)"""
    r = helpers.run(feeder(WIDE, control="MANUAL"))
    assert r.returncode == 0, r.stderr
    assert powerflow._common.object_state(r.model, "vvc")["link"] == "r01" # pylint: disable=protected-access

@pytest.mark.parametrize("vvc, message", [
    ("d_min 0.7;", "d_min must be less than d_max"),
    ("d_max 1.5;", "d_max and d_min must be a number between 0 and 1"),
    ("desired_pf -0.9;", "Desired power factor is negative.  Should pf_signed be set?"),
    ("pf_signed TRUE; desired_pf -1;", "Desired signed power factor is outside the valid range"),
    ("capacitor_delay -1;", "capacitor_delay must be a positive number!"),
    ("minimum_voltages 2500; maximum_voltages 2400; desired_voltages 2450;", "Minimum voltage limit on regulator 1 must be less than the maximum"),
    ("minimum_voltages 2300; maximum_voltages 2500; desired_voltages 2600;", "Desired voltage on regulator 1 is outside the minimum and maximum set points."),
    ("max_vdrop 0; low_load_deadband 10; high_load_deadband 5;", "Maximum expected voltage drop specified for regulator 1 should be a positive non-zero number."),
])
def test_init_errors(helpers, vvc, message):
    r = helpers.run(feeder(vvc))
    assert any(message in x and "vvc volt_var_control (id=" in x for x in helpers.errors(r)), r.stderr

def test_list_errors(helpers):
    r = helpers.run(feeder("").replace('capacitor_list "c1,c2";', 'capacitor_list "c1,c9";'))
    assert any("item c9 in capacitor_list not found" in x for x in helpers.errors(r)), r.stderr
    r = helpers.run(feeder("").replace("regulator_list r01;", "regulator_list nothing;"))
    assert any("regulator_list is empty" in x for x in helpers.errors(r)), r.stderr
    r = helpers.run(feeder("").replace("voltage_measurements n2;", 'voltage_measurements "n2,3";'))
    assert any("Measurement list references a nonexistant regulator 3" in x for x in helpers.errors(r)), r.stderr

def test_warnings(helpers):
    r = helpers.run(feeder("minimum_voltages 2300; maximum_voltages 2500; regulator_delay 0.5; low_load_deadband 5; high_load_deadband 10; max_vdrop 20;"))
    warnings = helpers.warnings(r)
    assert any("Desired, minimum, and maximum voltages don't match" in x for x in warnings)
    assert any("regulator_delay should be greater than or equal to 1" in x for x in warnings)
    assert any("Low loading deadband for regulator 1 is expected to be larger than the high loading deadband" in x for x in warnings)

def test_measurement_pairs(helpers):
    """Pairs of node and regulator number"""
    m = helpers.run(feeder("").replace("voltage_measurements n2;", 'voltage_measurements "n2,1,n1,1";')).model
    assert powerflow._common.object_state(m, "vvc")["measurements"] == [["n2", "n1"]] # pylint: disable=protected-access
