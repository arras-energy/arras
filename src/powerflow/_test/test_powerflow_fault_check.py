"""Class `fault_check`: registration, initialization, check modes, removal
and restoration of unsupported phases, output file, grid association, and
errors"""
# pylint: disable=missing-function-docstring,line-too-long

import pytest

import powerflow
from powerflow.fault_check import support
from arras.oclass import Class
from arras.model import Model

VNOM = 2401.7771

def feeder(fault_check:str, switch:str="CLOSED", player:bool=False, l23:str="ABCN") -> str:
    """n0 (swing) - l01 - n1 - sw - n2 - l23 - n3 (load)"""
    play = 'object player { property status; file "sw.csv"; };' if player else ""
    return ("module tape;\n" if player else "") + f"""
object node {{ name n0; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; phases ABCN; from n0; to n1; length 1000; }}
object node {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object switch {{ name sw; phases ABCN; from n1; to n2; status {switch}; {play} }}
object node {{ name n2; phases ABCN; nominal_voltage {VNOM}; }}
object test_line {{ name l23; phases {l23}; from n2; to n3; length 1000; }}
object load {{ name n3; phases ABCN; nominal_voltage {VNOM}; constant_power_A 10000; constant_power_B 10000; constant_power_C 10000; }}
object fault_check {{ name fc; {fault_check} }}
"""

@pytest.fixture(name="player_file")
def fixture_player_file():
    with open("sw.csv", "w", encoding="utf-8") as file:
        file.write("2020-01-01 01:00:00,OPEN\n2020-01-01 02:00:00,CLOSED\n")

def volts(m, name:str) -> list[complex]:
    return [powerflow.get_complex(m, name, f"voltage_{x}") for x in "ABC"]

def read(path:str) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()

def test_registration():
    Model().read_glm("module powerflow;\n")
    oclass = Class.find("fault_check", module="powerflow")
    assert oclass.trl == 6 and oclass.parent is None
    assert list(oclass.find_property("check_mode").keywords) == ["SINGLE_DEBUG", "ALL", "ONCHANGE", "SINGLE"]
    assert oclass.find_property("strictly_radial").default == "TRUE" and oclass.find_property("check_mode").default == "SINGLE"
    names = [x.name for x in powerflow.classes()]
    assert names.index("fault_check") == names.index("volt_var_control") + 1

def test_supported(helpers):
    with open("fc.txt", "w", encoding="utf-8") as file:
        file.write("old\n")
    r = helpers.run(feeder('output_filename "fc.txt";'))
    assert r.returncode == 0, r.stderr
    assert read("fc.txt") == "" # emptied at initialization, nothing unsupported
    tops, supported, islands = support(r.model, False)
    assert tops == ["n0", "n1", "n2", "n3"] and len(supported) == 12 and set(islands.values()) == {0}

def test_unsupported_fails(helpers):
    """Strictly radial without reliability: the run fails at the first check"""
    r = helpers.run(feeder('output_filename "fc.txt";', switch="OPEN"))
    assert r.returncode != 0
    assert any("sync_fault_check(obj=" in x and ";fc): Unsupported phase on node n2" in x for x in helpers.errors(r))
    assert read("fc.txt") == "Unsupported at timestamp 1577836800 - 2020-01-01 00:00:00 =\n\nPhases A, B, and C on node n2\nPhases A, B, and C on node n3\n\n"
    r = helpers.run(feeder("strictly_radial FALSE;", switch="OPEN"))
    assert any("Unsupported phase on a possibly meshed node" in x for x in helpers.errors(r))

def test_reliability_removes(helpers):
    """With reliability_mode the unsupported phases are taken out (gridlabd
    leaves them in, in strictly radial mode)"""
    r = helpers.run(feeder("reliability_mode TRUE;", switch="OPEN"))
    assert r.returncode == 0, r.stderr
    assert any("fc: Unsupported phase on node n2" in x for x in helpers.warnings(r))
    assert volts(r.model, "n3") == [0, 0, 0] and abs(volts(r.model, "n1")[0]) > 2000

def test_without_fault_check_fails(helpers):
    r = helpers.run(feeder("", switch="OPEN").replace("object fault_check { name fc;  }", ""))
    assert r.returncode != 0 and any("no swing bus" in x for x in helpers.errors(r))

def test_unsupported_phases(helpers):
    """A single-phase line feeds the three-phase load: phases B and C"""
    r = helpers.run(feeder('reliability_mode TRUE; output_filename "fc.txt";', l23="AN"))
    assert r.returncode == 0, r.stderr
    assert "Phases B and C on node n3\n" in read("fc.txt")
    v = volts(r.model, "n3")
    assert abs(v[0]) > 2000 and v[1] == 0 and v[2] == 0

@pytest.mark.usefixtures("player_file")
def test_onchange(helpers):
    """The switch opens at 01:00 and closes at 02:00: the island is taken
    out, then restored"""
    glm = feeder('check_mode ONCHANGE; strictly_radial FALSE; reliability_mode TRUE; output_filename "fc.txt";', player=True)
    r = helpers.run(glm, stop="2020-01-01 01:30:00")
    assert r.returncode == 0, r.stderr
    assert volts(r.model, "n3") == [0, 0, 0]
    assert any("fc: Unsupported phase on a possibly meshed node" in x for x in helpers.warnings(r))
    assert read("fc.txt").startswith("Unsupported at timestamp 1577840400 - 2020-01-01 01:00:00 =")
    r = helpers.run(glm, stop="2020-01-01 02:30:00")
    assert r.returncode == 0, r.stderr
    assert all(abs(x) > 2000 for x in volts(r.model, "n3"))

@pytest.mark.usefixtures("player_file")
def test_single_misses_changes(helpers):
    """SINGLE checks only at the start: the switch opening later leaves an
    unsupported island, which fails the solver"""
    r = helpers.run(feeder("reliability_mode TRUE;", player=True), stop="2020-01-01 01:30:00")
    assert r.returncode != 0 and any("no swing bus" in x for x in helpers.errors(r))

@pytest.mark.usefixtures("player_file")
def test_all(helpers):
    r = helpers.run(feeder("check_mode ALL; reliability_mode TRUE;", player=True), stop="2020-01-01 01:30:00")
    assert r.returncode == 0, r.stderr
    assert volts(r.model, "n2") == [0, 0, 0]

def test_full_output_and_grids(helpers):
    """Two grids: with grid_association both are supported, in islands 1
    and 2; meshed checking is forced with a warning"""
    glm = feeder('full_output_file TRUE; grid_association TRUE; output_filename "fc.txt";', switch="OPEN").replace(
        "object node { name n2; phases ABCN;", "object node { name n2; bustype SWING; phases ABCN;")
    r = helpers.run(glm)
    assert r.returncode == 0, r.stderr
    assert any("fc: fault_check:fc was forced into meshed search mode due to multiple grids being desired" in x for x in helpers.warnings(r))
    assert r.model.get_property("fc", "strictly_radial") == "FALSE"
    assert read("fc.txt") == ("Supported at timestamp 1577836800 - 2020-01-01 00:00:00 =\nNumber detected islands = 2\n\n"
        "Phases A, B, and C on node n0 - Island 1\nPhases A, B, and C on node n1 - Island 1\n"
        "Phases A, B, and C on node n2 - Island 2\nPhases A, B, and C on node n3 - Island 2\n\n")

def test_full_output_with_unsupported(helpers):
    r = helpers.run(feeder('full_output_file TRUE; reliability_mode TRUE; output_filename "fc.txt";', l23="AN"))
    assert r.returncode == 0, r.stderr
    text = read("fc.txt")
    assert text.startswith("Unsupported at timestamp 1577836800 - 2020-01-01 00:00:00 =\n\nPhases B and C on node n3\n\nSupported Nodes\n")
    assert text.endswith("Phases A, B, and C on node n2\nPhase A on node n3\n\n")

def test_single_debug(helpers):
    r = helpers.run(feeder('check_mode SINGLE_DEBUG; output_filename "fc.txt";', switch="OPEN"))
    assert r.returncode != 0
    assert any(" fc -- Special debug mode utilized, simulation terminating" in x for x in helpers.errors(r))
    assert read("fc.txt").startswith("Special debug topology check -- phase checks bypassed -- Unsupported nodes list\n\nPhases A, B, and C on node n2\n")

def test_restoration(helpers):
    r = helpers.run(feeder("") + "object restoration { name rs; }\n")
    assert r.returncode != 0
    assert any("fc: fault_check interaction with restoration requires meshed checking mode - enabling this now" in x for x in helpers.warnings(r))
    assert any("Restoration failed to execute properly" in x for x in helpers.errors(r))

@pytest.mark.parametrize("glm,module,message", [
    (feeder(""), "solver_method DC;", "init_fault_check(obj=7;fc): Fault checking object is only valid for the Newton-Raphson solver at this time."),
    (feeder("") + "object fault_check { name fc2; }\n", "", "init_fault_check(obj=8;fc2): Only one fault_check object is supported at this time"),
    (feeder("eventgen_object n1;"), "", "fault_check:fc n1 is not an eventgen object. Please specify the name of an eventgen object."),
    (feeder(""), "NR_island_failure_handled TRUE;", "fault_check:fc - powerflow::NR_island_failure_handled is set, but grid_association is not!"),
])
def test_init_errors(helpers, glm, module, message):
    r = helpers.run(glm, module=module)
    assert r.returncode != 0 and any(message in x for x in helpers.errors(r)), helpers.errors(r)

def test_blown_fuse(helpers):
    """A fuse blows: ONCHANGE takes the nodes past it out (without
    fault_check the run fails with no swing bus)"""
    glm = feeder("check_mode ONCHANGE; reliability_mode TRUE;").replace("object switch { name sw; phases ABCN; from n1; to n2; status CLOSED;  }",
        "object fuse { name sw; phases ABCN; from n1; to n2; current_limit 1 A; mean_replacement_time 3600; }")
    r = helpers.run(glm, stop="2020-01-01 00:30:00")
    assert r.returncode == 0, r.stderr
    assert any("just blew" in x for x in helpers.warnings(r))
    assert volts(r.model, "n3") == [0, 0, 0] and abs(volts(r.model, "n1")[0]) > 2000
    r = helpers.run(glm.replace("object fault_check { name fc; check_mode ONCHANGE; reliability_mode TRUE; }", ""), stop="2020-01-01 00:30:00")
    assert r.returncode != 0 and any("no swing bus" in x for x in helpers.errors(r))
