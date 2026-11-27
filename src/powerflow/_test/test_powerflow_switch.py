"""Classes `switch`, `recloser`, and `sectionalizer`: registration,
initialization, switch logic, and solutions"""
# pylint: disable=missing-function-docstring,line-too-long

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.switch import Switch
from powerflow.recloser import Recloser
from powerflow.sectionalizer import Sectionalizer

def feeder(cls:str="switch", extra:str="", tail:str="") -> str:
    return f"""
object node {{ name n1; phases ABCN; nominal_voltage 2401.777; bustype SWING; }}
object {cls} {{ name s12; phases ABCN; from n1; to n2; {extra} }}
object node {{ name n2; phases ABCN; nominal_voltage 2401.777; power_A 100000+50000j; power_B 100000+50000j; power_C 100000+50000j; }}
{tail}"""

def states(m:Model) -> list[str]:
    return [m.get_property("s12", f"phase_{x}_state") for x in "ABC"]

def test_registration():
    Model().read_glm("module powerflow;\n")
    switch = Class.find("switch", module="powerflow")
    assert switch.parent.name == "link" and switch.trl == 8
    assert switch.find_property("operating_mode").default == "BANKED"
    assert switch.find_property("phase_B_state").default == "CLOSED"
    for name in ("recloser", "sectionalizer"):
        oclass = Class.find(name, module="powerflow")
        assert oclass.parent.name == "switch" and oclass.find_property("switch_impedance") is not None
    assert Class.find("recloser", module="powerflow").find_property("number_of_tries").flags

@pytest.mark.parametrize("cls", ["switch", "recloser", "sectionalizer"])
def test_closed(helpers, cls):
    """A closed switch is `default_resistance*(1-j)` on each phase"""
    r = helpers.run(feeder(cls), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    z = powerflow.get_complex(m, "s12", "switch_impedance")
    assert z == pytest.approx(complex(1e-4, -1e-4))
    assert powerflow.get_double(m, "s12", "switch_resistance") == pytest.approx(1e-4)
    i = powerflow.get_complex(m, "s12", "current_in_A")
    v1, v2 = helpers.voltages(m, "n1")[0], helpers.voltages(m, "n2")[0]
    assert v1 - v2 == pytest.approx(z*i, abs=1e-9)
    assert abs(v2*np.conj(i) - (100000+50000j)) < 1

def test_impedance_parts(helpers):
    """The last of the impedance and its parts set wins; a zero part
    becomes `default_resistance` with a warning"""
    r = helpers.run(feeder(extra="switch_impedance 0.01+0.02j; switch_reactance 0;"), lines=False)
    assert r.returncode == 0, r.stderr
    assert powerflow.get_complex(r.model, "s12", "switch_impedance") == pytest.approx(complex(0.01, 1e-4))
    assert any("switch_reactance has been set to zero" in x for x in helpers.warnings(r))

def test_open(helpers):
    """An open switch disconnects the to node, whose voltages are 0"""
    r = helpers.run(feeder(extra="status OPEN;"), lines=False)
    assert r.returncode == 0, r.stderr
    assert np.all(helpers.voltages(r.model, "n2") == 0)
    assert states(r.model) == ["OPEN"]*3

@pytest.mark.parametrize("given,status,result", [
    ("phase_A_state OPEN;", "CLOSED", ["CLOSED"]*3),
    ("phase_A_state OPEN; phase_B_state OPEN;", "OPEN", ["OPEN"]*3),
    ("status OPEN;", "OPEN", ["OPEN"]*3),
])
def test_banked_init(helpers, given, status, result):
    """Banked: the minority of phases follows the majority, a minority of
    closed phases opens the switch"""
    m = helpers.run(feeder(extra=given), lines=False).model
    assert m.get_property("s12", "status") == status and states(m) == result

def test_banked_change(helpers):
    """Banked: opening two phases opens the switch; changing `status`
    afterwards closes every phase"""
    m = helpers.run(feeder(), lines=False).model
    m.set_property("s12", "phase_A_state", "OPEN")
    m.set_property("s12", "phase_B_state", "OPEN")
    Switch.before_solve(m, "s12", 0)
    assert m.get_property("s12", "status") == "OPEN" and states(m) == ["OPEN"]*3
    m.set_property("s12", "status", "CLOSED")
    Switch.before_solve(m, "s12", 1)
    assert states(m) == ["CLOSED"]*3
    m.set_property("s12", "phase_C_state", "OPEN")
    Switch.before_solve(m, "s12", 2)
    assert states(m) == ["CLOSED"]*3, "a single open phase follows the majority"

def test_individual(helpers):
    """Individual: an open phase disconnects only that phase"""
    r = helpers.run(feeder(extra="operating_mode INDIVIDUAL; phase_B_state OPEN;"), lines=False)
    assert r.returncode == 0, r.stderr
    v = helpers.voltages(r.model, "n2")
    assert v[1] == 0 and abs(v[0]) > 2000 and abs(v[2]) > 2000
    assert powerflow.get_complex(r.model, "s12", "current_in_B") == 0

def test_change_switch_state(helpers):
    m = helpers.run(feeder(extra="operating_mode INDIVIDUAL;"), lines=False).model
    assert Switch.change_switch_state(m, "s12", 0x04 | 0x01, False) == 1
    assert states(m) == ["OPEN", "CLOSED", "OPEN"]
    m2 = helpers.run(feeder(), lines=False).model
    Switch.change_switch_state(m2, "s12", 0x04, False)
    assert m2.get_property("s12", "status") == "OPEN" and states(m2) == ["OPEN"]*3

@pytest.mark.parametrize("method", ["FD_XB", "FD_BX", "DC"])
def test_other_methods(helpers, method):
    r = helpers.run(feeder(extra="operating_mode INDIVIDUAL; phase_C_state OPEN;"), module=f"solver_method {method};", lines=False)
    assert r.returncode == 0, r.stderr
    assert helpers.voltages(r.model, "n2")[2] == 0

def test_switch_mid_run(helpers):
    """A player-like change during the run: opening the switch at the next
    time step isolates the to node"""
    m = helpers.run(feeder(), stop="2020-01-01 00:00:00", lines=False).model
    m.set_property("s12", "status", "OPEN")
    Switch.before_solve(m, "s12", 0)
    assert states(m) == ["OPEN"]*3 and Switch.connected_phases(m, "s12") == 0

def test_triplex_refused(helpers):
    glm = """
object node { name n1; phases AS; nominal_voltage 120; bustype SWING; }
object switch { name s12; phases AS; from n1; to n2; }
object node { name n2; phases AS; nominal_voltage 120; }
"""
    r = helpers.run(glm, lines=False)
    assert r.returncode != 0
    assert any("switch:1 - s12 - triplex/S-phase connections unsupported at this time" in x for x in helpers.errors(r)), r.stderr

def test_recloser_init(helpers):
    m = helpers.run(feeder("recloser"), lines=False).model
    assert powerflow.get_double(m, "s12", "max_number_of_tries") == 3 and powerflow.get_double(m, "s12", "retry_time") == 1
    r = helpers.run(feeder("recloser", "max_number_of_tries -2; retry_time -5;"), lines=False)
    assert r.returncode == 0
    assert any("number of recloser tries is less than 0" in x for x in helpers.warnings(r))
    assert any("retry time is < 0" in x for x in helpers.warnings(r))
    assert powerflow.get_double(r.model, "s12", "max_number_of_tries") == 3

def test_recloser_state(helpers):
    m = helpers.run(feeder("recloser", "max_number_of_tries 4;"), lines=False).model
    m.set_property("s12", "number_of_tries", "2")
    Recloser.before_solve(m, "s12", 10)
    assert powerflow.get_double(m, "s12", "number_of_tries") == 0
    assert Recloser.change_recloser_state(m, "s12", 0x07, False) == 4 and m.get_property("s12", "status") == "OPEN"
    assert Recloser.change_recloser_state(m, "s12", 0x07, True) == 1 and m.get_property("s12", "status") == "CLOSED"

def test_sectionalizer_state(helpers):
    m = helpers.run(feeder("sectionalizer", "status OPEN;"), lines=False).model
    assert Sectionalizer.change_sectionalizer_state(m, "s12", 0x07, True) == 1 and m.get_property("s12", "status") == "CLOSED"
    with pytest.raises(powerflow.PowerflowError, match="without fault_check"):
        Sectionalizer.change_sectionalizer_state(m, "s12", 0x07, False)
