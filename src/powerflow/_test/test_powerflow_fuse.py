"""Class `fuse`: registration, initialization, admittance, blowing,
replacement, and isolation of the node it feeds"""
# pylint: disable=missing-function-docstring,line-too-long

import numpy as np
import pytest

import powerflow
from arras import exitcodes
from arras.oclass import Class
from arras.model import Model

SOURCE = "object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }\n"

def fuse_feeder(fuse:str="", loads:str="power_A 200000; power_B 50000; power_C 50000;") -> str:
    """A fuse feeding a load node from the swing node"""
    return SOURCE + f"""
object fuse {{ name f1; phases ABCN; from n0; to n1; {fuse} }}
object node {{ name n1; phases ABCN; nominal_voltage 2401.7771; {loads} }}
"""

def test_registration():
    Model().read_glm("module powerflow;\n")
    fuse = Class.find("fuse", module="powerflow")
    assert fuse.parent.name == "link" and fuse.trl == 8
    assert list(fuse.find_property("phase_A_status").keywords) == ["GOOD", "BLOWN"]
    assert fuse.find_property("phase_A_status").default == "GOOD"
    assert fuse.find_property("current_limit").default == "9999 A"
    assert fuse.find_property("mean_replacement_time").default == "3600 s"
    assert fuse.find_property("fuse_resistance").default == "-1 Ohm"
    assert list(fuse.find_property("repair_dist_type").keywords) == ["EXPONENTIAL", "NONE"]

def test_admittance(helpers):
    """Below its limit, each phase is the admittance (1+j)/R, with R
    `default_resistance` when `fuse_resistance` is negative"""
    r = helpers.run(fuse_feeder(), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_double(m, "f1", "fuse_resistance") == pytest.approx(1e-4)
    assert powerflow.get_double(m, "f1", "mean_repair_time") == 3600
    y = complex(1, 1)/1e-4
    for x in "ABC":
        drop = powerflow.get_complex(m, "n0", f"voltage_{x}") - powerflow.get_complex(m, "n1", f"voltage_{x}")
        assert abs(drop*y - powerflow.get_complex(m, "f1", f"current_in_{x}")) < 1e-6
        assert m.get_property("f1", f"phase_{x}_status") == "GOOD"
    assert not helpers.warnings(r)

def test_blow_and_replace(helpers):
    """Phase A blows above the limit; the node it fed alone loses phase A;
    the fuse is replaced after `mean_replacement_time` (a soft event) and
    blows again"""
    r = helpers.run(fuse_feeder("current_limit 50; mean_replacement_time 3600;"), stop="2020-01-01 02:30:00", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    blew = [x for x in helpers.warnings(r) if "just blew" in x]
    assert len(blew) == 3
    assert blew[0].startswith("WARNING [2020-01-01 00:00:00 UTC]: f1: Phase A of fuse:f1 just blew!- current is 83.27")
    assert "[2020-01-01 01:00:00 UTC]" in blew[1] and "[2020-01-01 02:00:00 UTC]" in blew[2]
    assert sum("No fault_check object present - Newton-Raphson solver may fail!" in x for x in helpers.warnings(r)) == 3
    assert m.get_property("f1", "phase_A_status") == "BLOWN"
    assert m.get_property("f1", "phase_B_status") == "GOOD"
    assert powerflow.get_complex(m, "n1", "voltage_A") == 0
    assert abs(powerflow.get_complex(m, "n1", "voltage_B")) > 2400
    assert powerflow.get_complex(m, "f1", "current_in_A") == 0
    assert m.get_property("f1", "flow_direction") == "CF|BF|AN"

def test_blow_in_mesh(helpers):
    """When the node the fuse feeds has another link, it keeps phase A
    through that link"""
    r = helpers.run(SOURCE + """
        object fuse { name f1; phases ABCN; from n0; to n1; current_limit 20; }
        object test_line { name l1; phases ABCN; from n0; to n1; length 5000; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; power_A 200000; power_B 20000; power_C 20000; }
        """)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert m.get_property("f1", "phase_A_status") == "BLOWN"
    assert abs(powerflow.get_complex(m, "n1", "voltage_A")) > 2000
    assert abs(powerflow.get_complex(m, "l1", "power_out_A") - 200000) < 1

def test_blow_upstream_fails(helpers):
    """A blown fuse that cuts off more than its own node fails the run, as
    gridlabd's NR does without fault_check"""
    r = helpers.run(SOURCE + """
        object fuse { name f1; phases ABCN; from n0; to n1; current_limit 50; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; }
        object test_line { name l1; phases ABCN; from n1; to n2; length 1000; }
        object node { name n2; phases ABCN; nominal_voltage 2401.7771; power_A 200000; }
        """)
    assert r.returncode == exitcodes.RUNERR
    assert any("no swing bus found for n1.A, n2.A" in x for x in helpers.errors(r))

def test_open(helpers):
    """`status OPEN` blows every phase; the node it fed is out of the
    network"""
    r = helpers.run(fuse_feeder("status OPEN;"), lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert [m.get_property("f1", f"phase_{x}_status") for x in "ABC"] == ["BLOWN"]*3
    assert np.all(helpers.voltages(m, "n1") == 0)
    assert m.get_property("f1", "flow_direction") == "CN|BN|AN"

def test_exponential_repair(helpers):
    """Exponential replacement durations follow `randomseed` and are
    written to `mean_repair_time`"""
    glm = "#set randomseed=5\n" + fuse_feeder("current_limit 50; mean_replacement_time 600; repair_dist_type EXPONENTIAL;")
    first = helpers.run(glm, lines=False)
    second = helpers.run(glm, lines=False)
    value = powerflow.get_double(first.model, "f1", "mean_repair_time")
    assert value != 600 and value > 0
    assert powerflow.get_double(second.model, "f1", "mean_repair_time") == value
    from powerflow._common import object_state # pylint: disable=import-outside-toplevel
    fix = object_state(first.model, "f1")["fix_time"][0]
    assert fix == 1577836800 + int(value) # 2020-01-01 00:00:00 UTC plus the truncated duration

@pytest.mark.parametrize("fuse,message", [
    ("current_limit 0;", "fuse:f1 has a zero current limit - set to 9999.9 Amps"),
    ("mean_replacement_time 0;", "Fuse:f1 has a negative or 0 mean replacement time - defaulting to 1 hour"),
    ("fuse_resistance 0;", "Fuse:f1 fuse_resistance has been set to zero. This will result singular matrix. Setting to the global default."),
])
def test_init_warnings(helpers, fuse, message):
    r = helpers.run(fuse_feeder(fuse, "power_A 1000;"), lines=False)
    assert r.returncode == 0, r.stderr
    assert any(message in x for x in helpers.warnings(r))
    m = r.model
    assert powerflow.get_double(m, "f1", "current_limit") > 0
    assert powerflow.get_double(m, "f1", "mean_replacement_time") > 0
    assert powerflow.get_double(m, "f1", "fuse_resistance") == pytest.approx(1e-4)
    assert powerflow.get_double(m, "f1", "mean_repair_time") == powerflow.get_double(m, "f1", "mean_replacement_time")

@pytest.mark.parametrize("glm,module,message", [
    (SOURCE + "object fuse { name f1; phases AS; from n0; to n1; } object node { name n1; phases AS; nominal_voltage 120; }", "", "init_fuse(obj=1;f1): fuses cannot be placed on triplex circuits"),
    (fuse_feeder("current_limit -1;"), "", "fuse:f1 has a negative current limit value!"),
])
def test_init_errors(helpers, glm, module, message):
    r = helpers.run(glm, module=module, lines=False)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

@pytest.mark.parametrize("method", ["NR", "FBS", "FD_XB", "FD_BX", "DC"])
def test_replaced_under_every_solver(helpers, method):
    """With every solver method, a fuse blows and is replaced at its
    replacement time (a soft event), then blows again"""
    r = helpers.run(fuse_feeder("current_limit 50; mean_replacement_time 1800;"), module=f"solver_method {method};", stop="2020-01-01 01:10:00", lines=False)
    assert r.returncode == 0, r.stderr
    blew = [x.split("]")[0] for x in r.stderr if "just blew" in x]
    assert blew == ["WARNING [2020-01-01 00:00:00 UTC", "WARNING [2020-01-01 00:30:00 UTC", "WARNING [2020-01-01 01:00:00 UTC"]
    assert r.model.get_property("f1", "phase_A_status") == "BLOWN"

@pytest.mark.parametrize("method", ["FD_XB", "FD_BX"])
def test_fd_same_as_nr(helpers, method):
    """The fast-decoupled methods solve the fuse's NR admittance (1+j)/R:
    same voltages as NR"""
    nr = helpers.run(fuse_feeder(), lines=False)
    fd = helpers.run(fuse_feeder(), module=f"solver_method {method};", lines=False)
    assert fd.returncode == 0, fd.stderr
    assert np.max(np.abs(helpers.voltages(fd.model, "n1") - helpers.voltages(nr.model, "n1"))) < 1e-6
    y = complex(1, 1)/1e-4
    drop = powerflow.get_complex(fd.model, "n0", "voltage_A") - powerflow.get_complex(fd.model, "n1", "voltage_A")
    assert abs(drop*y - powerflow.get_complex(fd.model, "f1", "current_in_A")) < 1e-6

def test_dc_magnitude(helpers):
    """DC uses the magnitude of the fuse impedance, R/sqrt(2), so the flow
    goes from the source to the load"""
    r = helpers.run(fuse_feeder(), module="solver_method DC;", lines=False)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_complex(m, "f1", "power_in_A").real == pytest.approx(200000)
    assert m.get_property("f1", "flow_direction") == "CF|BF|AF"
    angle = np.angle(powerflow.get_complex(m, "n0", "voltage_A")) - np.angle(powerflow.get_complex(m, "n1", "voltage_A"))
    assert angle == pytest.approx(200000*(1e-4/np.sqrt(2))/helpers.VNOM**2)
