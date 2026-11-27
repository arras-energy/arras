"""Classes `line` and `line_configuration`: registration, initialization,
and unbalanced feeders of `line` objects checked against an independent
solution"""
# pylint: disable=missing-function-docstring,line-too-long

import math

import numpy as np
import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model
from powerflow.line import Line

C601 = {ij: float(b)/(2*math.pi*60)*1e3 for ij, b in zip(("11", "12", "13", "21", "22", "23", "31", "32", "33"),
    (6.2998, -1.9958, -1.2595, -1.9958, 5.9597, -0.7417, -1.2595, -0.7417, 5.6386))}
"""Capacitance (nF/mile) of configuration 601 at 60 Hz, from its shunt
susceptance (uS/mile, Kersting example 5.1)"""

def config_601(name:str="lc601") -> str:
    z = {"11": "0.3465+1.0179j", "12": "0.1560+0.5017j", "13": "0.1580+0.4236j",
         "21": "0.1560+0.5017j", "22": "0.3375+1.0478j", "23": "0.1535+0.3849j",
         "31": "0.1580+0.4236j", "32": "0.1535+0.3849j", "33": "0.3414+1.0348j"}
    terms = " ".join(f"z{ij} {v};" for ij, v in z.items()) + " " + " ".join(f"c{ij} {v!r};" for ij, v in C601.items())
    return f"object line_configuration {{ name {name}; {terms} }}"

FEEDER = config_601() + """
object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
object line { name l01; phases ABCN; from n0; to n1; length 2000; configuration lc601; }
object node { name n1; phases ABCN; nominal_voltage 2401.7771;
    power_A 200000+100000j; power_B 120000+60000j; power_C 50000+30000j; }
object line { name l12; phases ABCN; from n1; to n2; length 2500; configuration lc601; }
object node { name n2; phases ABCN; nominal_voltage 2401.7771;
    power_AB 100000+40000j; current_C 15+5j; shunt_B 0.002+0.0005j; }
"""
"""The unbalanced feeder of test_powerflow_flows.py, with `line` objects
of configuration 601"""

LOADS = {
    "n0": {},
    "n1": {"S": (200e3+100e3j, 120e3+60e3j, 50e3+30e3j)},
    "n2": {"D": (100e3+40e3j, 0, 0), "I": (0, 0, 15+5j), "Y": (0, 0.002+0.0005j, 0)},
}
LINES = [("n0", "n1", 2000), ("n1", "n2", 2500)]

def test_registration():
    """`line` inherits from `link`; `line_configuration` and
    `powerflow_library` are registered in gridlabd's order"""
    Model().read_glm("module powerflow;\n")
    assert [x.name for x in powerflow.classes()] == ["powerflow_object", "powerflow_library", "node", "link", "capacitor", "fuse", "meter", "line", "line_spacing",
        "overhead_line", "underground_line", "overhead_line_conductor", "underground_line_conductor", "line_configuration",
        "transformer_configuration", "transformer", "load", "regulator_configuration", "regulator", "triplex_node", "triplex_meter", "triplex_line", "triplex_line_configuration", "triplex_line_conductor", "switch_coordinator", "switch", "substation", "pqload", "voltdump", "series_reactor", "restoration", "frequency_gen", "volt_var_control", "motor", "billdump", "power_metrics", "currdump", "recloser",
        "sectionalizer", "emissions", "load_tracker", "triplex_load", "triplex_zipload", "impedance_dump", "vfd", "pole", "pole_configuration", "pole_mount", "zipload"]
    line = Class.find("line", module="powerflow")
    assert line.parent.name == "link"
    assert line.find_property("length").unit == "ft" and line.find_property("length").flags & 0x0008
    assert line.find_property("configuration").ptype == "object"
    assert line.find_property("power_in") is not None
    config = Class.find("line_configuration", module="powerflow")
    assert getattr(config, "parent", None) is None
    assert config.find_property("z23").unit == "Ohm/mile" and config.find_property("z23").default == "0+0j"
    assert config.find_property("c31").unit == "nF/mile"
    assert config.find_property("rating.winter.emergency").default == "2000 A"
    assert [p.name for p in config.properties()][:6] == ["conductor_A", "conductor_B", "conductor_C", "conductor_N", "spacing", "z11"]
    assert Class.find("powerflow_library", module="powerflow") is not None

@pytest.mark.parametrize("method", ["NR", "FD_XB"])
def test_feeder(helpers, method):
    """With `line_capacitance`, the node voltages match the independent
    solution with the lines' shunt capacitance"""
    r = helpers.run(FEEDER, module=f"solver_method {method}; line_capacitance true;", lines=False)
    assert r.returncode == 0, r.stderr
    expected = helpers.reference(LOADS, LINES, "n0")
    for name in ("n1", "n2"):
        assert np.max(np.abs(helpers.voltages(r.model, name) - expected[name])) < 1e-3, name
    assert sum(1 for x in helpers.warnings(r) if "highly recommended" in x) == 2

def test_same_as_stand_in(helpers):
    """A `line` gives the solution of the stand-in line class of the other
    tests"""
    r = helpers.run(FEEDER, module="line_capacitance true;")
    stand_in = helpers.run(FEEDER.replace("object line {", "object test_line {").replace(" configuration lc601;", ""))
    for name in ("n1", "n2"):
        assert np.max(np.abs(helpers.voltages(r.model, name) - helpers.voltages(stand_in.model, name))) < 1e-6

def test_no_line_capacitance(helpers):
    """Without `line_capacitance` (the default), the capacitance is left out,
    with a warning"""
    r = helpers.run(FEEDER, lines=False)
    assert r.returncode == 0, r.stderr
    expected = helpers.reference(LOADS, LINES, "n0", shunt=np.zeros((3, 3)))
    assert np.max(np.abs(helpers.voltages(r.model, "n2") - expected["n2"])) < 1e-3
    assert any("Shunt capacitance of line:l01 specified without setting powerflow::line_capacitance = TRUE. Shunt capacitance will be ignored." in x for x in helpers.warnings(r))

def test_partial_phases(helpers):
    """A line on phases A and C uses only the A and C terms of its
    configuration"""
    m = helpers.model(config_601() + """
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
        object line { name l01; phases ACN; from n0; to n1; length 1000; configuration lc601; }
        object node { name n1; phases ACN; nominal_voltage 2401.7771; }
        """, module="line_capacitance true;", lines=False)
    zabc, yabc = Line.line_matrices(m, "l01")
    assert zabc[0, 2] == pytest.approx((0.1580+0.4236j)*1000/5280)
    assert zabc[0, 1] == 0 and zabc[1, 1] == 0 and zabc[2, 1] == 0
    assert yabc[1, 1] == 0 and yabc[2, 2] == pytest.approx(1j*2*math.pi*60*1e-9*C601["33"]*1000/5280)

def test_frequency(helpers):
    """The shunt admittance follows `powerflow::nominal_frequency`"""
    m = helpers.model(config_601() + """
        object node { name n0; phases ABCN; nominal_voltage 2401.7771; }
        object line { name l01; phases ABCN; from n0; to n1; length 5280; configuration lc601; }
        object node { name n1; phases ABCN; nominal_voltage 2401.7771; }
        """, module="line_capacitance true; nominal_frequency 50;", lines=False)
    _, yabc = Line.line_matrices(m, "l01")
    assert yabc[0, 0] == pytest.approx(1j*2*math.pi*50*1e-9*C601["11"])
    key = Line.admittance_key(m, "l01")
    m.set_property("lc601", "z11", "1+1j")
    assert Line.admittance_key(m, "l01") != key

@pytest.mark.parametrize("glm,message", [
    ("object node { name n0; phases ABC; nominal_voltage 2400; } object node { name n1; phases ABC; nominal_voltage 2410; } object line { name l01; phases ABC; from n0; to n1; length 100; configuration lc601; }",
     "init_line(obj=3;l01): from and to node nominal voltage mismatch of greater than 0.1%%"),
    ("object node { name n0; phases ABC; nominal_voltage 2400; } object node { name n1; phases ABC; nominal_voltage 2400; } object line { name l01; phases ABC; from n0; to n1; configuration lc601; }",
     "Newton-Raphson method does not support zero length lines at this time"),
    ("object node { name n0; phases ABC; nominal_voltage 2400; } object node { name n1; phases ABC; nominal_voltage 2400; } object line { name l01; phases ABC; from n0; to n1; length 100; }",
     "line:3 - l01 - configuration object either doesn't exist, or is not a valid configuration object!"),
    ("object node { name n0; phases ABC; nominal_voltage 2400; } object node { name n1; phases ABC; nominal_voltage 2400; } object line { phases ABC; from n0; to n1; length 100; configuration n0; }",
     "init_line(obj=3;unnamed): line:3 - Unnamed - configuration object either doesn't exist"),
    ("object node { name n0; phases ABC; nominal_voltage 2400; } object line { name l01; phases ABC; from n0; to n0; length 100; configuration lc601; }",
     "FROM and TO objects are the same object!"),
])
def test_init_errors(helpers, glm, message):
    r = helpers.run(config_601() + glm, lines=False)
    assert r.returncode != 0
    assert any(message in x for x in helpers.errors(r)), r.stderr

@pytest.mark.parametrize("method,name", [("NR", "Newton-Raphson"), ("FBS", "Newton-Raphson"), ("FD_XB", "FD_XB"), ("FD_BX", "FD_BX"), ("DC", "DC")])
def test_zero_length_any_solver(helpers, method, name):
    """A zero-length line fails with every solver method, not only NR as in
    gridlabd"""
    r = helpers.run(config_601() + """
        object node { name n0; phases ABC; nominal_voltage 2400; bustype SWING; }
        object node { name n1; phases ABC; nominal_voltage 2400; }
        object line { name l01; phases ABC; from n0; to n1; length 0; configuration lc601; }
        """, module=f"solver_method {method};", lines=False)
    assert r.returncode != 0
    assert any(f"init_line(obj=3;l01): {name} method does not support zero length lines at this time" in x for x in helpers.errors(r)), r.stderr
