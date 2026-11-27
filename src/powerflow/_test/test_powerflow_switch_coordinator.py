"""Class `switch_coordinator`: registration, connecting and arming
switches, toggling and direct switching in the solution, and the return
to IDLE"""
# pylint: disable=missing-function-docstring,line-too-long

import numpy as np
import pytest

from arras.oclass import Class
from arras.model import Model
from powerflow.switch_coordinator import SwitchCoordinator

VNOM = 2401.7771
T0 = 1577836800

def feeder(coordinator:str, s2:str="OPEN") -> str:
    return f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object switch {{ name s1; phases ABCN; from n0; to n1; status CLOSED; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object switch {{ name s2; phases ABCN; from n0; to n2; status {s2}; }}
object node {{ name n2; phases ABCN; nominal_voltage {VNOM}; }}
object switch {{ name s3; phases ABCN; from n0; to n3; status CLOSED; }}
object node {{ name n3; phases ABCN; nominal_voltage {VNOM}; }}
object switch_coordinator {{ name sc; connect "s1|s2|s3"; {coordinator} }}
"""

def status(m:Model) -> list[str]:
    return [m.get_property(x, "status") for x in ("s1", "s2", "s3")]

def test_registration():
    Model().read_glm("module powerflow;\n")
    sc = Class.find("switch_coordinator", module="powerflow")
    assert sc.trl == 9 and sc.parent is None
    assert sc.find_property("status").default == "IDLE" and sc.find_property("arm").ptype == "method"
    assert "NONE" in sc.find_property("armed").keywords

def test_arm(helpers):
    """Arming the last switch connected works (gridlabd misses it); arming
    makes the coordinator ARMED"""
    r = helpers.run(feeder("arm s3; arm s1;"), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("sc", "armed") == "s1|s3" and m.get_property("sc", "status") == "ARMED"
    assert m.get_property("sc", "arm") == "" and status(m) == ["CLOSED", "OPEN", "CLOSED"]

def test_toggle(helpers):
    """TOGGLE flips the armed switches in the solution, then the coordinator
    is IDLE with nothing armed"""
    r = helpers.run(feeder("arm s1; arm s2; status TOGGLE;"), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert status(m) == ["OPEN", "CLOSED", "CLOSED"]
    assert np.abs(helpers.voltages(m, "n1")).max() == 0 and np.abs(helpers.voltages(m, "n2")).min() > 0
    assert m.get_property("sc", "status") == "IDLE" and m.get_property("sc", "armed") == "NONE"

def test_direct(helpers):
    """DIRECT closes the armed switches and opens the others"""
    m = helpers.run(feeder("arm s2; status DIRECT;"), lines=False).model
    assert status(m) == ["OPEN", "CLOSED", "OPEN"]
    assert np.abs(helpers.voltages(m, "n2")).min() > 0 and np.abs(helpers.voltages(m, "n3")).max() == 0

def test_runtime_methods(helpers):
    """Method values written during a run are applied at the next time"""
    m = helpers.run(feeder(""), lines=False).model
    assert m.get_property("sc", "status") == "IDLE"
    m.set_property("sc", "arm", "s3")
    m.set_property("sc", "status", "TOGGLE")
    SwitchCoordinator.precommit(m, "sc", T0 + 60)
    assert m.get_property("sc", "armed") == "s3" and m.get_property("sc", "arm") == ""
    SwitchCoordinator.sync(m, "sc", T0 + 60)
    assert status(m) == ["CLOSED", "OPEN", "OPEN"]
    SwitchCoordinator.commit(m, "sc", T0 + 60)
    assert m.get_property("sc", "status") == "IDLE"
    m.set_property("sc", "disarm", "s1")
    SwitchCoordinator.precommit(m, "sc", T0 + 120)
    assert m.get_property("sc", "status") == "ARMED" and m.get_property("sc", "armed") == "NONE"

@pytest.mark.parametrize("coordinator, message, kind", [
    ('connect "n1";', "object 'n1' is not a switch", "ERROR"),
    ('connect "nothing";', "object 'nothing' is not found", "WARNING"),
    ("arm n1;", "unable to arm 'n1', no such device connected", "ERROR"),
])
def test_errors(helpers, coordinator, message, kind):
    r = helpers.run(feeder(coordinator), lines=False)
    lines = helpers.errors(r) if kind == "ERROR" else helpers.warnings(r)
    assert any(message in x for x in lines), r.stderr
