"""The gridlabd `pypower` module autotests, ported to `arras`

Each GLM file in `data/` is a gridlabd autotest from
`module/pypower/autotest/` with the changes listed in `data/README.md`.
Files whose name ends in `_opt` may fail (gridlabd ignores their exit
code, which includes the result of their `#on_exit` commands); the others
must succeed without errors. The tests then make the checks that
gridlabd's `#on_exit` commands make: `check_case.py` (the
solution's `pp_bus_1` `Vm` equals the case's within 1e-4 of it, which
`test_case14_err` must fail), and comparisons of recorded files with the
files gridlabd wrote. Each runs in its own empty folder.
"""

import os
import glob
import importlib
import sys

import pytest

from arras import exitcodes
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
TESTS = sorted(os.path.basename(x) for x in glob.glob(os.path.join(DATA, "test_*.glm")))

CASES = {
    "test_case9.glm": "case9", "test_case9dc.glm": "case9dc", "test_case4gs.glm": "case4gs",
    "test_case14.glm": "case14", "test_case14gs.glm": "case14", "test_case14_err.glm": "case14e",
    "test_case30.glm": "case30", "test_case39.glm": "case39", "test_case57.glm": "case57",
    "test_case118.glm": "case118", "test_case14_controller.glm": "case14",
    "test_case14_geodata.glm": "case14", "test_case14_load.glm": "case14",
    "test_case14_load_drop.glm": "case14", "test_case14_powerline.glm": "case14",
    "test_case14_sensitivity.glm": "case14", "test_case14_storage.glm": "case14",
    "test_case14_ts.glm": "case14", "test_case14_weather.glm": "case14",
    "test_case14_opf_dispatch_opt.glm": "case14", "test_case14_powerplant_opt.glm": "case14",
}
"""Autotests whose `#on_exit` runs `check_case.py` on `pp_bus_1/Vm`, and
their case (`test_case14_opf.glm` defines `NO_ONEXIT`)"""

OUTPUTS = {
    "test_case14_weather.glm": ["test_case14_weather_pp_bus_1_record.csv"],
    "test_case14_sensitivity.glm": ["test_case14_sensitivity_pp_bus_1_record.csv"],
    "test_case14_geodata.glm": ["test_case14_geodata_load_2_record.csv"],
    "test_derating.glm": ["test_derating_powerplant_capacity.csv"],
    "test_case14_storage.glm": ["test_case14_storage_record.csv"],
    "test_case14_ts.glm": ["test_case14_ts.csv"],
    "test_case14_powerplant_opt.glm": ["test_case14_powerplant_pp_gen_2_record.csv",
        "test_case14_powerplant_pp_powerplant_2_record.csv"],
}
"""Recordings that gridlabd wrote, compared line for line (see
`compare()`)"""

def autotest(helpers, file:str) -> Runner:
    """Run an autotest in the working folder, with the data copied there
    (the recordings gridlabd wrote are renamed `*.gridlabd`)"""
    helpers.copy_data(os.getcwd())
    for name in OUTPUTS.get(file, []) + (["test_case14_powerplant_pp_bus_2_record.csv"] if file == "test_case14_powerplant_opt.glm" else []):
        os.rename(name, f"{name}.gridlabd")
    return Runner(file)

def check_case(runner:Runner, case:str) -> bool:
    """`check_case.py CASE.json CASE_ref.json pp_bus_1/Vm`: the solution's
    `pp_bus_1` `Vm` equals the case's within 1e-4 of it"""
    sys.path.insert(0, os.getcwd())
    try:
        data = getattr(importlib.import_module(case), case)()
    finally:
        sys.path.pop(0)
        sys.modules.pop(case, None)
    initial = float(data["bus"][0][7])
    solved = float(runner.model.get_property("pp_bus_1", "Vm").split()[0])
    return abs(1 - solved/initial) <= 1e-4

def compare(helpers, name:str) -> None:
    """A recording equals gridlabd's: `arras`'s recorders write a first row
    at the start time, which gridlabd's do not (tape decision 10.4), and
    the time zone `GMT0` is `UTC`"""
    expected = [x.replace(" GMT,", " UTC,") for x in helpers.lines(f"{name}.gridlabd")]
    actual = helpers.lines(name)
    if len(actual) == len(expected) + 1:
        actual = actual[:1] + actual[2:]
    assert actual == expected

def test_files():
    """Every gridlabd autotest of the pypower module is ported"""
    assert len(TESTS) == 25
    assert set(CASES) | {"test_case14_opf.glm", "test_autosize.glm", "test_derating.glm",
        "test_shunt_capacitor.glm"} == set(TESTS)

@pytest.mark.parametrize("file", TESTS)
def test_autotest(helpers, file):
    """Each autotest succeeds (an `_opt` test may fail), and its
    `check_case.py` check passes (fails for `_err`)"""
    runner = autotest(helpers, file)
    if not file.endswith("_opt.glm"):
        assert runner.returncode == exitcodes.SUCCESS, runner.stderr
        assert helpers.errors(runner) == []
    if file in CASES and not file.endswith("_opt.glm"):
        assert check_case(runner, CASES[file]) is not file.endswith("_err.glm")
    for name in OUTPUTS.get(file, []):
        compare(helpers, name)

def test_case14_opf(helpers):
    """The OPF of case 14 gives gridlabd's voltages (the autotest's asserts
    hold to 0.001 pu and 0.01 deg) and writes the case files"""
    runner = autotest(helpers, "test_case14_opf.glm")
    assert runner.returncode == exitcodes.SUCCESS
    assert runner.model.globals.get("pypower::solver_status") == "SUCCESS"
    for suffix in ("casedata_bus", "casedata_gencost", "results_bus", "results_branch", "results_gen"):
        assert os.path.exists(f"test_case14_opf_{suffix}.csv")
    assert os.path.exists("test_case14_opf_results_solver.json")

def test_case14_powerplant(helpers):
    """A dispatchable powerplant with a ramp rate and a player-driven load:
    the bus demand follows the player as gridlabd's recording does (the
    bus voltages are not compared: gridlabd's recording keeps the first
    solution's all day)"""
    runner = autotest(helpers, "test_case14_powerplant_opt.glm")
    assert runner.returncode == exitcodes.SUCCESS
    expected = helpers.lines("test_case14_powerplant_pp_bus_2_record.csv.gridlabd")
    actual = helpers.lines("test_case14_powerplant_pp_bus_2_record.csv")
    assert len(actual) == len(expected)
    for want, got in zip(expected[1:], actual[1:]):
        assert want.split(",")[0] == got.split(",")[0]
        assert want.split(",")[2:4] == got.split(",")[2:4]

def test_case14_opf_dispatch(helpers):
    """With powerplants on every generator, the OPF updates the setpoints
    `Ps` and `Qs` and leaves `Pg` and `Qg` as the powerplants make them
    (the autotest's purpose). Its voltage asserts may fail, which gridlabd
    allows (`_opt`): with gridlabd's loose OPF tolerances the voltages
    depend on the numerical libraries (bus 1 reaches 1.273 pu with one
    build of numpy and scipy, the asserted 1.195 pu with another)"""
    runner = autotest(helpers, "test_case14_opf_dispatch_opt.glm")
    assert runner.returncode in (exitcodes.SUCCESS, exitcodes.RUNERR)
    assert all("assert failed" in x or "commit failed" in x for x in helpers.errors(runner))
    assert [runner.model.get_property(f"pp_gen_{n}", "Pg") for n in range(1, 6)] == ["0.0"]*5

def test_case14_controller(helpers):
    """Load, powerplant, and relay controllers switch every half hour, the
    module's `on_sync` asks for the top of each hour, and the SCADA object
    records its points to the historian"""
    runner = autotest(helpers, "test_case14_controller.glm")
    assert runner.steps == 49
    module = sys.modules["controllers"]
    name = [x for x, obj in runner.model.objects.items() if obj.oclass.name == "scada"][0]
    historian = module.historian[name]
    assert len(historian) == 49
    first = historian[min(historian)]
    assert set(first) == {"pp_bus_3.Va", "pp_bus_4.Va"}
    assert first["pp_bus_3.Va"].endswith(" deg")
    assert module.scada[name] == historian[max(historian)]

def test_case14_load(helpers):
    """Two loads on bus 2 add up to the case's demand"""
    runner = autotest(helpers, "test_case14_load.glm")
    assert float(runner.model.get_property("pp_bus_2", "Pd")) == pytest.approx(21.7)
    assert runner.model.get_property("load:0", "S") == "21.0+12.0i"
    assert runner.model.get_property("load:0", "V").endswith("d")

def test_case14_powerline(helpers):
    """Powerlines set branches 1 to 3: one line, two in series, two in
    parallel (impedances in ohms)"""
    runner = autotest(helpers, "test_case14_powerline.glm")
    m = runner.model
    assert float(m.get_property("pp_branch_1", "r")) == pytest.approx(0.01938)
    assert float(m.get_property("pp_branch_2", "r")) == pytest.approx(0.05403)
    assert float(m.get_property("pp_branch_3", "x")) == pytest.approx(0.19797)
    assert float(m.get_property("pp_branch_3", "rateA")) == 0

def test_autosize(helpers):
    """A line, a device, and a transformer get autosized impedances, and
    the generator output holds the autotest's values"""
    runner = autotest(helpers, "test_autosize.glm")
    m = runner.model
    assert float(m.get_property("device_2_3", "x")) == pytest.approx(10*float(m.get_property("device_2_3", "r")))
    assert float(m.get_property("line_1_2", "b")) > 0
    assert float(m.get_property("transformer_2_4", "b")) == 0
    assert float(m.get_property("gen_1", "Pg")) == pytest.approx(20.0451, abs=0.001)

def test_shunt_capacitor(helpers):
    """A discrete capacitor bank steps once and locks for its dwell time; a
    continuous condenser settles at its limit"""
    runner = autotest(helpers, "test_shunt_capacitor.glm")
    m = runner.model
    assert float(m.get_property("caps_3", "admittance")) >= 1.0
    assert 0 < float(m.get_property("caps_4", "admittance")) <= 15.0
