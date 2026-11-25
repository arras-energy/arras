"""The `pypower` package: docstrings, registration, globals, the solver
call, and helpers"""

import os
import json
import doctest
import importlib

import pytest

import pypower
from pypower import _common, solver as solver_module
from pypower.geodata import geocode_decode
from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner

MODULES = ["pypower", "pypower.solver", "pypower.bus", "pypower.branch", "pypower.dcline",
    "pypower.gen", "pypower.gencost", "pypower.geodata", "pypower.load", "pypower.powerplant",
    "pypower.powerline", "pypower.relay", "pypower.scada", "pypower.shunt", "pypower.transformer",
    "pypower.weather"]

CLASSES = ["bus", "branch", "dcline", "gen", "gencost", "geodata", "load", "powerplant",
    "powerline", "relay", "scada", "shunt", "transformer", "weather"]

LINE = [0.01, 0.1, 0.02, 0, 0, 0, 0, 0, 1, -360, 360]

def three_bus(**options) -> dict:
    """Solver case data of the three-bus network"""
    case = {"version": 2, "baseMVA": 100.0,
        "bus": [[1, 3, 0, 0, 0, 0, 1, 1.0, 0, 230, 1, 1.1, 0.9],
            [2, 1, 50, 20, 0, 0, 1, 1.0, 0, 230, 1, 1.1, 0.9],
            [3, 1, 40, 10, 0, 0, 1, 1.0, 0, 230, 1, 1.1, 0.9]],
        "branch": [[1, 2] + LINE, [2, 3] + LINE, [1, 3] + LINE],
        "gen": [[1, 0, 0, 100, -100, 1.0, 100, 1, 200, 0] + [0]*11]}
    case.update(options)
    return case

@pytest.mark.parametrize("name", MODULES)
def test_doctests(name):
    """The docstring examples give the output shown"""
    result = doctest.testmod(importlib.import_module(name), optionflags=doctest.ELLIPSIS)
    assert result.failed == 0

def test_load():
    """GLM `module pypower;` registers the module with its solvers, its
    classes in gridlabd's order, and its globals"""
    m = Model()
    m.read_glm("module pypower;\n")
    assert [x.name for x in pypower.classes()] == CLASSES
    module = Module.find("pypower")
    assert {"init", "precommit", "sync", "commit", "term"} <= set(module.solvers)
    assert m.globals.get("pypower::version") == "2"
    assert m.globals.get("pypower::solver_method") == "NR"
    assert m.globals.get("pypower::baseMVA") == "+100 MVA"
    assert m.globals.get("pypower::enable_opf") == "FALSE"
    assert m.globals.get("pypower::save_format") == "CSV"
    assert m.globals.get("pypower::solver_status") == "INIT"
    assert m.globals.get("pypower::default_reactive_power_fraction") == "+0.2 pu"
    assert m.globals.get("pypower::autosize_angle") == "+0 rad"
    assert m.globals.get("pypower::opf_condition_tolerance") == "+1000"
    second = Model()
    second.read_glm("module pypower { save_format PY; maximum_timestep 60; }\n")
    assert [x.name for x in pypower.classes()] == CLASSES
    assert second.globals.get("pypower::save_format") == "PY"

def test_globals_order():
    """Globals are created in gridlabd's order: message flags, the class
    globals, then the module globals"""
    m = Model()
    m.read_glm("module pypower;\n")
    names = [name for name, *_ in pypower.GLOBALS]
    assert names[:4] == ["message_flags", "autosize_angle", "default_dcline_loss0", "default_dcline_loss1"]
    assert names[-1] == "opf_cost_tolerance"
    for name in names:
        assert m.globals.isdefined(f"pypower::{name}")

def test_classes():
    """Class properties, units, defaults, keywords, flags, pass
    configurations, readiness levels, and event handlers"""
    Model().read_glm("module pypower;\n")
    bus = Class.find("bus", module="pypower")
    assert [p.name for p in bus.properties()][:5] == ["bus_i", "S", "type", "Pd", "Qd"]
    assert bus["Pd"].unit == "MW" and bus["Pd"].has_flag("OUTPUT")
    assert bus["baseKV"].has_flag("REQUIRED")
    assert list(bus["type"].keywords) == ["PQREF", "NONE", "REF", "PV", "PQ", "UNKNOWN"]
    assert bus["Vm"].default == "1 pu.V"
    assert bus.trl == 9
    assert bus.has_pass("PRETOPDOWN") and not bus.has_pass("BOTTOMUP")
    assert bus.events["presync"] == "python:pypower.presync"
    assert Class.find("shunt", module="pypower").trl == 7
    load = Class.find("load", module="pypower")
    assert set(load.events) == {"init", "presync", "sync", "postsync"}
    plant = Class.find("powerplant", module="pypower")
    assert list(plant["fuel"].keywords)[0] == "NG"
    assert plant["fuel"].keywords["COAL"] == 0x4000
    assert Class.find("scada", module="pypower")["point"].ptype == "method"
    branch = Class.find("branch", module="pypower")
    assert branch["angmin"].default == "-360 deg"
    assert list(branch["status"].keywords) == ["IN", "OUT"]

def test_handlers_outside_run():
    """Event handlers need a running simulation"""
    with pytest.raises(pypower.PypowerError):
        pypower.init("x", 0)
    with pytest.raises(pypower.PypowerError):
        _common.runner()

def test_not_pypower_object(helpers):
    """A handler called for an object of another class fails the run"""
    m = helpers.model("""
        class thing { double x; on_init "python:pypower.init"; }
        object thing { name t1; }
        """)
    runner = Runner(model=m)
    assert runner.returncode != 0

#
# Solver
#
def test_solver_methods():
    """The four power flow methods and the DC power flow solve the case"""
    for method in (1, 2, 3, 4):
        result = solver_module.solver(three_bus(solver_method=method, save_case=False))
        assert round(result["bus"][1][7], 4) == 0.9792
    result = solver_module.solver(three_bus(use_dc_powerflow=True))
    assert result["bus"][1][7] == 1.0

def test_solver_out_of_service():
    """Generators out of service are not passed to PYPOWER and keep their
    rows"""
    case = three_bus()
    case["gen"].append([2, 5, 0, 10, -10, 1.0, 100, 0, 10, 0] + [0]*11)
    result = solver_module.solver(case)
    assert result["gen"][1][1] == 5

def test_solver_save(tmp_path):
    """Case data and results are written in the three formats"""
    for fmt in ("csv", "json", "py"):
        solver_module.solver(three_bus(save_case=True, save_format=fmt, modelname=str(tmp_path / f"m_{fmt}")))
    assert (tmp_path / "m_csv_casedata_bus.csv").read_text().startswith("bus_i,type,Pd")
    assert (tmp_path / "m_csv_results_branch.csv").exists()
    data = json.loads((tmp_path / "m_json_results.json").read_text())
    assert len(data["bus"]) == 3
    assert "array(" in (tmp_path / "m_py_results.py").read_text()
    solver_json = json.loads((tmp_path / "m_csv_results_solver.json").read_text())
    assert solver_json["bus"].endswith("m_csv_results_bus.csv") and solver_json["success"] == 1

def test_solver_failure(tmp_path, capsys):
    """A solution that does not converge writes the failure files and
    returns `False` when `stop_on_failure`; a case without a REF or PV bus
    is an exception"""
    name = str(tmp_path / "f")
    case = three_bus(maximum_iterations_nr=1, solution_tolerance=1e-30, modelname=name, stop_on_failure=True)
    assert solver_module.solver(case) is False
    assert (tmp_path / "f_failed.txt").read_text().startswith("*** SOLVER FAILURE DIAGNOSTICS ***")
    case = three_bus(maximum_iterations_nr=1, solution_tolerance=1e-30, modelname=name, stop_on_failure=False)
    assert isinstance(solver_module.solver(case), dict)
    case = three_bus(modelname=name)
    case["bus"][0][1] = 1
    assert solver_module.solver(case) is False
    assert "EXCEPTION [solver.py@" in capsys.readouterr().err
    assert (tmp_path / "f_exception_bus.csv").exists()

def test_solver_opf(tmp_path, capsys):
    """Cost data makes the solver run the OPF; empty cost data is an
    exception; debug and verbose write the case tables and PYPOWER's
    report"""
    case = three_bus(gencost=[[2, 0, 0, "0.01,10,0"]], debug=True, verbose=True, modelname=str(tmp_path / "o"))
    case["bus"] = [row + [0]*4 for row in case["bus"]]
    case["gen"] = [row + [0]*4 for row in case["gen"]]
    for row in case["branch"]:
        row[5] = 250 # PYPOWER 5.1.16's PIPS raises when no branch has a rating (with numpy 1.26 too)
    result = solver_module.solver(case)
    assert round(result["gen"][0][1], 1) == pytest.approx(90.5, abs=0.5)
    captured = capsys.readouterr()
    assert "*** BUS DATA ***" in captured.err and "*** GENCOST DATA ***" in captured.err
    assert "PYPOWER" in captured.out or "Converged" in captured.out
    assert solver_module.solver(three_bus(gencost=[], modelname=str(tmp_path / "o"))) is False

def test_solver_diagnostics(tmp_path):
    """The diagnostics list limit violations"""
    data = {"gen": [[1, 300, 0, 10, -10, 1, 100, 1, 200, 0]],
        "branch": [[1, 2, 0, 0, 0, 10, 0, 0, 0, 0, 1, 0, 0, 50, 0, -50, 0]],
        "bus": [[1, 3, 0, 0, 0, 0, 1, 1.2, 0, 230, 1, 1.1, 0.9]]}
    solver_module.write_case({}, str(tmp_path / "d.txt"))
    assert "No generation data" in (tmp_path / "d.txt").read_text()
    with open(tmp_path / "e.txt", "w", encoding="utf-8") as fh:
        solver_module._diagnostics(data, fh) # pylint: disable=protected-access
    text = (tmp_path / "e.txt").read_text()
    assert "Generation output violations" in text and "Branch flow violations" in text and "Bus voltage violations" in text

def test_jsonify():
    """Nested containers are replaced by their key, as in gridlabd"""
    assert pypower.solver.jsonify({"a": 1, "b": {"c": 2}}) == {"a": 1, "b": "b"}
    with pytest.raises(NameError):
        pypower.solver.jsonify([1])

#
# Helpers
#
@pytest.mark.parametrize("text, unit, value", [
    ("1+2j", None, complex(1, 2)), ("(1+2j)", None, complex(1, 2)), ("5", None, complex(5, 0)),
    ("2+90d", None, complex(0, 2)), ("1+0r", None, complex(1, 0)), ("1+1j kVA", "MVA", complex(0.001, 0.001)),
    ("", None, 0j), ("x", None, 0j),
])
def test_text_to_complex(text, unit, value):
    """Complex text in the notations gridlabd reads"""
    assert _common.text_to_complex(text, unit) == pytest.approx(value)

def test_values():
    """Doubles, notations, C arithmetic"""
    assert _common.text_to_double("1500 kW", "MW") == pytest.approx(1.5)
    assert _common.text_to_double("x") == 0.0
    assert _common.fmt_complex(complex(0, 2), "d") == "2.0+90.0d"
    assert _common.fmt_complex(complex(1, -1), "i") == "1.0-1.0i"
    assert _common.fmt(float("nan")) == "nan" and _common.fmt(float("-inf")) == "-inf"
    assert _common.fdiv(1, 0) == float("inf") and _common.fdiv(-1, 0) == float("-inf")
    assert _common.fdiv(0, 0) != _common.fdiv(0, 0)
    assert _common.csqrt(-1) != _common.csqrt(-1)

def test_from_string(helpers):
    """Controller values are set as gridlabd's `from_string()` reads them"""
    m = helpers.model("object load { name l1; }")
    assert _common.from_string(m, "l1", "P", "(10+2j)") and m.get_property("l1", "P") == "10+2j"
    assert _common.from_string(m, "l1", "P", "5j") and m.get_property("l1", "P") == "5"
    assert not _common.from_string(m, "l1", "status", "MAYBE")

def test_geocode():
    """Geohash cell centers"""
    lat, lon = geocode_decode("ezs42")
    assert lat == pytest.approx(42.605, abs=0.03) and lon == pytest.approx(-5.603, abs=0.03)
    assert geocode_decode("ezs4a") is None

def test_flags(helpers):
    """Object flags and the module message flags control object messages"""
    m = helpers.model("object bus { name b1; flags QUIET; } object bus { name b2; }")
    m.globals.set("pypower::message_flags", "VERBOSE")
    assert _common.object_flags(m, "b1") & _common.OF_QUIET
    assert _common.object_flags(m, "b2") & _common.OF_VERBOSE

def test_saved_case_name(helpers):
    """A run that reads a model file names saved case files after it"""
    helpers.write("three.glm", f"""
        clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 00:00:00"; }}
        module pypower {{ save_case TRUE; save_format JSON; }}
        {helpers.THREE_BUS}
        """)
    runner = Runner("three.glm")
    assert runner.returncode == 0, runner.stderr
    assert os.path.exists("three_casedata.json") and os.path.exists("three_results.json")
