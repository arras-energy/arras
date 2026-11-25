Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	pip install -e . pytest
	pytest src/pypower/_test

The package must be installed (editable or not), because `Model` finds the
module through the `arras.modules` entry point in `pyproject.toml`, and
numpy and scipy must be installed (`requirements.txt`). The tests use no
network and no credentials, and finish in about 75 seconds (about 2.5
minutes with coverage), most of it in the month-long hourly runs of the
ported autotests (`test_case14_load`, `_load_drop`, `_powerline`,
`_geodata`, `_weather`, `_sensitivity`, 745 time steps each).
`conftest.py` runs each test in an empty temporary folder with empty
`arras.oclass.Class.registry` and `arras.module.Module.registry`, ignores
the `data` folder when collecting tests, and provides helpers (the
`helpers` fixture): `model()` and `run()` (GLM text after a clock and
`module pypower;`), `THREE_BUS` (a three-bus network whose solution is
known), `copy_data()` (the test data into the working folder), `write()`,
`lines()`, `errors()`, and `warnings()`.

test_pypower_autotest.py
------------------------

Runs each ported gridlabd autotest (`data/test_*.glm`) in its own folder.
Files named `_opt` may fail, as gridlabd ignores their exit code; the
others must succeed with no error lines. Then makes the checks of the
autotests' `#on_exit` commands:

- `check_case.py CASE.json CASE_ref.json pp_bus_1/Vm` (from `case.glm`):
  the solution's `pp_bus_1` `Vm` equals the case's within 1e-4 of it;
  `test_case14_err` (whose case has a wrong `Vm`) must fail it.
- the recordings that gridlabd wrote, line for line:
  `test_case14_weather_pp_bus_1_record.csv`,
  `test_case14_sensitivity_pp_bus_1_record.csv`,
  `test_case14_geodata_load_2_record.csv`,
  `test_derating_powerplant_capacity.csv`,
  `test_case14_storage_record.csv`, `test_case14_ts.csv`, and the
  generator and powerplant recordings of `test_case14_powerplant_opt`.
  `arras`'s recorders write a first row at the start time that gridlabd's
  do not (tape decision 10.4); that row is left out, and `GMT` reads
  `UTC`.

It also checks: the OPF of case 14 (the autotest's asserts hold gridlabd's
voltages to 0.001 pu) and its case files; the bus demand of the
powerplant autotest (gridlabd's recording keeps the voltages of the first
solution all day, so voltages are not compared); the OPF dispatch
autotest (its first assert fails, which gridlabd allows); the controllers
of `test_case14_controller` (49 steps, the SCADA historian); the loads,
powerlines, autosizing, and shunts of their autotests.

test_pypower_module.py
----------------------

The docstring examples of every module; registration of the module with
its solvers, its 14 classes in gridlabd's order, and its globals in
gridlabd's order; published properties, units, defaults, keywords (in
gridlabd's order), flags, pass configurations, readiness levels, and
event handlers; handlers outside a run and on objects of other classes;
the solver call: the five power flow methods, generators out of service,
the three save formats and `jsonify()`, failures (diagnostics files,
`stop_on_failure`, exceptions), the OPF and its debug tables; and the
helpers (complex notations, C division and square root, `from_string()`,
geohashes, message flags, saved case names).

test_pypower_classes.py
-----------------------

The three-bus network's solution, losses, and currents; models without
branches; `maximum_timestep`; solver failures; the OPF with tight
tolerances (the defaults are gridlabd's loose ones); verbose messages;
and each class: bus base loads, weather files, and sensitivities; weather
objects; branch errors and autosizing; generator and cost model errors;
DC line losses, control points, and status; load status and voltages;
powerplants on buses (storage) and generators (derating, ramps, costs,
emissions); powerline, transformer, relay, and shunt behavior and
errors; geodata targets and file errors; saved case files.

test_pypower_controllers.py
---------------------------

The controllers module: `on_init`, `on_precommit`, `on_sync`,
`on_commit`, and `on_term` calls and results, functions that are not
callable or fail, halting with `stop_on_failure`, a module that cannot be
imported; load, powerplant, and relay controllers (arguments, results,
errors, values not accepted); and SCADA points, historian, and writes.
