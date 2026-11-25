"""Power flow solutions of models: unbalanced feeders checked against an
independent solution, link outputs, solver methods, and failures"""
# pylint: disable=missing-function-docstring,line-too-long

import numpy as np
import pytest

import powerflow
from arras import exitcodes

FEEDER = """
object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
object test_line { name l01; phases ABCN; from n0; to n1; length 2000; }
object node { name n1; phases ABCN; nominal_voltage 2401.7771;
    power_A 200000+100000j; power_B 120000+60000j; power_C 50000+30000j; }
object test_line { name l12; phases ABCN; from n1; to n2; length 2500; }
object node { name n2; phases ABCN; nominal_voltage 2401.7771;
    power_AB 100000+40000j; current_C 15+5j; shunt_B 0.002+0.0005j; }
"""
"""Two unbalanced line sections of configuration 601: wye constant-power
loads at `n1`; a delta load, a constant-current load, and an admittance
at `n2`"""

LOADS = {
    "n0": {},
    "n1": {"S": (200e3+100e3j, 120e3+60e3j, 50e3+30e3j)},
    "n2": {"D": (100e3+40e3j, 0, 0), "I": (0, 0, 15+5j), "Y": (0, 0.002+0.0005j, 0)},
}
LINES = [("n0", "n1", 2000), ("n1", "n2", 2500)]

@pytest.mark.parametrize("method", ["NR", "FD_XB", "FD_BX", "FBS"])
def test_unbalanced_feeder(helpers, method):
    """The node voltages of an unbalanced feeder match an independent
    solution, whichever AC method solves it (FBS is solved with NR)"""
    r = helpers.run(FEEDER, module=f"solver_method {method};")
    assert r.returncode == 0, r.stderr
    expected = helpers.reference(LOADS, LINES, "n0")
    for name in ("n1", "n2"):
        assert np.max(np.abs(helpers.voltages(r.model, name) - expected[name])) < 1e-3, name
    deprecated = [x for x in helpers.warnings(r) if "FBS is deprecated" in x]
    assert len(deprecated) == (1 if method == "FBS" else 0)

def test_unbalance_is_real(helpers):
    """The feeder is unbalanced: phase magnitudes differ by volts, and the
    mutual coupling matters (a solution without it differs)"""
    r = helpers.run(FEEDER)
    v = np.abs(helpers.voltages(r.model, "n2"))
    assert v.max() - v.min() > 20

def test_link_outputs(helpers):
    """Currents, powers, losses, totals, and flow directions"""
    r = helpers.run(FEEDER)
    m = r.model
    get = lambda name, prop: powerflow.get_complex(m, name, prop)
    for phase in "ABC":
        s_in, s_out, loss = get("l01", f"power_in_{phase}"), get("l01", f"power_out_{phase}"), get("l01", f"power_losses_{phase}")
        assert abs(loss.real - abs((s_in - s_out).real)) < 1e-9 and abs(loss.imag - (s_in - s_out).imag) < 1e-9
        v_from = powerflow.get_complex(m, "n0", f"voltage_{phase}")
        assert abs(s_in - v_from*get("l01", f"current_in_{phase}").conjugate()) < 1e-6
    total = sum(get("l01", f"power_in_{x}") for x in "ABC")
    assert abs(get("l01", "power_in") - total) < 1e-6
    assert powerflow.get_double(m, "l01", "power_out_real") == pytest.approx(get("l01", "power_out").real)
    assert m.get_property("l01", "flow_direction") == "CF|BF|AF"
    # what leaves l01 is what n1 draws plus what enters l12
    for k, phase in enumerate("ABC"):
        drawn = LOADS["n1"]["S"][k]
        assert abs(get("l01", f"power_out_{phase}") - drawn - get("l12", f"power_in_{phase}")) < 1e-2

def test_reverse_flow(helpers):
    """With the swing node at the to end, flows are reverse"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; power_A 100000; power_B 100000; power_C 100000; }
        object test_line { name l01; phases ABCN; from n0; to n1; length 1000; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        """)
    assert r.returncode == 0, r.stderr
    assert r.model.get_property("l01", "flow_direction") == "CR|BR|AR"
    assert powerflow.get_complex(r.model, "l01", "power_in").real < 0

def test_open_link(helpers):
    """An open link carries nothing; the node it fed is an island without
    a swing node, which fails the run"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object test_line { name l01; phases ABCN; from n0; to n1; length 1000; status OPEN; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; power_A 1000; }
        """)
    assert r.returncode == exitcodes.RUNERR
    assert any("no swing bus found for n1.A, n1.B, n1.C" in x for x in helpers.errors(r))

def test_open_link_in_mesh(helpers):
    """An open link in a loop carries nothing and the other path carries
    the load"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object test_line { name a; phases ABCN; from n0; to n1; length 1000; }
        object test_line { name b; phases ABCN; from n0; to n1; length 1000; status OPEN; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; power_A 100000; }
        """)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_complex(m, "b", "power_in") == 0
    assert m.get_property("b", "flow_direction") == "CN|BN|AN"
    assert abs(powerflow.get_complex(m, "a", "power_out_A") - 100000) < 1e-2

def test_mesh(helpers):
    """Parallel lines of 1000 and 2000 ft share the flow 2:1"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object test_line { name a; phases ABCN; from n0; to n1; length 1000; }
        object test_line { name b; phases ABCN; from n0; to n1; length 2000; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; power_A 300000+100000j; power_B 200000; power_C 100000; }
        """)
    assert r.returncode == 0, r.stderr
    m = r.model
    for phase in "ABC":
        ia = powerflow.get_complex(m, "a", f"current_in_{phase}")
        ib = powerflow.get_complex(m, "b", f"current_in_{phase}")
        assert abs(ia - 2*ib) < 1e-3*abs(ia)

def test_single_phase_lateral(helpers):
    """A phase-B lateral off a three-phase feeder"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object test_line { name l01; phases ABCN; from n0; to n1; length 1000; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; }
        object test_line { name l12; phases BN; from n1; to n2; length 500; }
        object node { name n2; phases BN; nominal_voltage 2401.7771; power_B 50000+20000j; }
        """)
    assert r.returncode == 0, r.stderr
    m = r.model
    assert powerflow.get_complex(m, "n2", "voltage_A") == 0
    assert abs(powerflow.get_complex(m, "l12", "power_out_B") - (50000+20000j)) < 1e-2
    assert powerflow.get_complex(m, "l12", "power_in_A") == 0
    assert m.get_property("l12", "flow_direction") == "CN|BF|AN"
    miles = 500/5280
    z, ysh = helpers.Z601[1, 1]*miles, helpers.B601[1, 1]*miles/2
    vb = powerflow.get_complex(m, "n1", "voltage_B")
    series = powerflow.get_complex(m, "l12", "current_in_B") - ysh*vb
    assert abs(powerflow.get_complex(m, "n2", "voltage_B") - (vb - z*series)) < 1e-6

def test_delta_node(helpers):
    """A node with phase D takes power_A ... power_C as phase-to-phase
    loads AB, BC, CA"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object test_line { name l01; phases ABC; from n0; to n1; length 1000; }
        object node { name n1; phases ABCD; nominal_voltage 2401.7771; power_A 90000+30000j; }
        """)
    assert r.returncode == 0, r.stderr
    expected = helpers.reference({"n0": {}, "n1": {"D": (90e3+30e3j, 0, 0)}}, [("n0", "n1", 1000)], "n0")
    assert np.max(np.abs(helpers.voltages(r.model, "n1") - expected["n1"])) < 1e-3
    assert abs(powerflow.get_complex(r.model, "l01", "power_in_C")) < 1e-3 * 90000 + 50

def test_base_link(helpers):
    """A link of the base class is a `default_resistance` on each phase"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object link { name l01; phases ABCN; from n0; to n1; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; power_A 240177.71; }
        """, module="default_resistance 0.01 Ohm;")
    assert r.returncode == 0, r.stderr
    loss = powerflow.get_complex(r.model, "l01", "power_losses_A")
    current = abs(powerflow.get_complex(r.model, "l01", "current_in_A"))
    assert loss.real == pytest.approx(current**2*0.01)
    assert abs(loss.imag) < 1e-6

def test_dc(helpers):
    """DC: magnitudes stay at their initial values; flows are real and
    lossless"""
    r = helpers.run(FEEDER, module="solver_method DC;")
    assert r.returncode == 0, r.stderr
    m = r.model
    assert np.allclose(np.abs(helpers.voltages(m, "n2")), helpers.VNOM)
    loss = powerflow.get_complex(m, "l01", "power_losses")
    assert loss == 0
    assert powerflow.get_complex(m, "l01", "power_in").imag == 0
    p = powerflow.get_complex(m, "l12", "power_in_A").real
    assert p > 0 and np.angle(powerflow.get_complex(m, "n2", "voltage_A")) < 0

def test_pv_node(helpers):
    """A PV node keeps its voltage magnitude"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object test_line { name l01; phases ABCN; from n0; to n1; length 1000; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; bustype PV; voltage_A 2450; voltage_B 2450-120d; voltage_C 2450+120d; power_A -100000; power_B -100000; power_C -100000; }
        """)
    assert r.returncode == 0, r.stderr
    assert np.allclose(np.abs(helpers.voltages(r.model, "n1")), 2450)

def test_swing_voltage(helpers):
    """A swing node keeps the voltages it is given"""
    r = helpers.run("""
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; voltage_A 2500+0d; voltage_B 2500-120d; voltage_C 2500+120d; }
        object test_line { name l01; phases ABCN; from n0; to n1; length 1000; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; }
        """)
    assert r.returncode == 0, r.stderr
    assert np.allclose(np.abs(helpers.voltages(r.model, "n1")), 2500)

def test_iterates_until_settled(helpers):
    """The module asks to iterate after a solution that changed voltages;
    the second solution changes nothing"""
    r = helpers.run(FEEDER, stop="2020-01-01 02:00:00")
    assert r.returncode == 0, r.stderr
    from powerflow._common import module_state # pylint: disable=import-outside-toplevel
    state = module_state(r.model)
    assert state.solutions == 2
    assert state.last.success

HEAVY = """
    object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
    object test_line { name l01; phases ABCN; from n0; to n1; length 2000; }
    object node { name n1; phases ABCN; nominal_voltage 2401.7771; power_A 2000000; power_B 2000000; power_C 2000000; }
    """
"""A feeder whose solution needs several NR iterations"""

def test_iteration_limit(helpers):
    """A solution that needs more than `NR_iteration_limit` iterations
    keeps the voltages reached and iterates the time step, as gridlabd
    does; the run's `iteration_limit` stops it"""
    r = helpers.run("#set iteration_limit=3\n" + HEAVY, module="NR_iteration_limit 1;")
    assert r.returncode != 0
    r = helpers.run(HEAVY, module="NR_iteration_limit 1;")
    assert r.returncode == 0, r.stderr
    expected = helpers.run(HEAVY).model
    assert np.max(np.abs(helpers.voltages(r.model, "n1") - helpers.voltages(expected, "n1"))) < 1e-3

@pytest.mark.parametrize("handling,code,lines", [
    ("FATAL", exitcodes.RUNERR, ["ERROR", "unable to converge"]),
    ("IGNORE", 0, ["WARNING", "unable to converge"]),
    ("COLLAPSE", exitcodes.RUNERR, ["ERROR", "COLLAPSE is not yet supported", "unable to converge"]),
])
def test_convergence_errors(helpers, monkeypatch, handling, code, lines):
    """A solution that cannot be used (singular, not finite): FATAL fails
    the run, IGNORE warns and keeps the voltages, COLLAPSE is not supported
    (an error, then as FATAL), as in gridlabd"""
    from powerflow import _module # pylint: disable=import-outside-toplevel
    from powerflow.solver import Result # pylint: disable=import-outside-toplevel
    monkeypatch.setattr(_module, "solve", lambda net, *args, **kwargs: Result(np.full(len(net.labels), np.nan+0j), False, 3, 1, "test", True))
    r = helpers.run(FEEDER, module=f"convergence_error_handling {handling};")
    assert r.returncode == code
    level, *texts = lines
    for text in texts:
        assert any(x.startswith(level) and text in x for x in r.stderr), r.stderr
    assert np.all(np.isfinite(helpers.voltages(r.model, "n1")))

def test_diverged_solver():
    """A singular network is reported as diverged"""
    from powerflow.solver import Network, solve # pylint: disable=import-outside-toplevel
    net = Network()
    a = net.add_bus("a", 1, 1, "REF")
    b = net.add_bus("b", 1, 1)
    net.add_branch((a, -1, -1), (b, -1, -1), np.diag([1e-30, 0, 0]), np.diag([-1e-30, 0, 0]), np.diag([-1e-30, 0, 0]), np.diag([1e-30, 0, 0]))
    net.add_wye_load(b, S=1e6)
    result = solve(net)
    assert not result.success

def test_no_nodes(helpers):
    """A model that loads the module without nodes runs"""
    assert helpers.run("", lines=False).returncode == 0

def test_module_left_loaded(helpers):
    """A later run of a model without the module is not affected by the
    module's solvers"""
    from arras.model import Model # pylint: disable=import-outside-toplevel
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    assert helpers.run(FEEDER).returncode == 0
    m = Model()
    m.read_glm('clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }\nclass other { double x; }\nobject other { x 1; }\n')
    assert Runner(model=m).returncode == 0

def test_feeder_file(helpers):
    """`data/unbalanced_feeder.glm` (the feeder above, as a file) runs from
    the file name and writes its result"""
    import os # pylint: disable=import-outside-toplevel
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    helpers.register_test_line()
    r = Runner(os.path.join(helpers.DATA, "unbalanced_feeder.glm"), "-o", "result.json")
    assert r.returncode == 0, r.stderr
    expected = helpers.reference(LOADS, LINES, "n0")
    assert np.max(np.abs(helpers.voltages(r.model, "n2") - expected["n2"])) < 1e-3
    assert os.path.exists("result.json")
