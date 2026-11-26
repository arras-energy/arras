Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	pip install -e . pytest
	pytest src/powerflow/_test

The package must be installed (editable or not), because `Model` finds the
module through the `arras.modules` entry point in `pyproject.toml`, and
numpy and scipy must be installed (`requirements.txt`). The tests use no
network and no credentials, and finish in about a second.

`conftest.py` runs each test in an empty temporary folder with empty
`arras.oclass.Class.registry` and `arras.module.Module.registry`, ignores
the `data` folder when collecting tests, and provides helpers (the
`helpers` fixture):

- `StandInLine`, registered as class `test_line` (a `link` with a
  `length[ft]` property) by `register_test_line()`: a line of IEEE 13-node
  feeder configuration 601 (series impedance and shunt admittance per
  mile, Kersting, *Distribution System Modeling and Analysis*, examples
  4.1 and 5.1). The line classes of gridlabd are not ported yet; this
  class stands in for them and shows how a link class supplies its
  impedance (`series_impedance()`, `shunt_admittance()`,
  `admittance_key()`);
- `model()` and `run()`: GLM text after a clock and `module powerflow`
  (with `test_line` registered unless `lines=False`);
- `reference()`: an independent solution of a network of
  configuration-601 lines (shunt admittance `B601`, or another one) with wye constant-power, constant-current, and
  constant-admittance loads and delta constant-power loads, by fixed-point
  iteration on the nodal equations, which uses neither PYPOWER nor
  `powerflow.solver`;
- `voltages()`, `errors()`, `warnings()`.

test_powerflow_module.py
------------------------

The docstring examples of every module (doctests); `module powerflow;`
registers the module's solvers, its three classes in gridlabd's order with
their parent class, and its globals (defaults, the
`default_maximum_voltage_error` alias, the `solver_method` keywords);
selected published properties (types, units, keywords in gridlabd's order,
access, defaults, the abstract `powerflow_object`); the initialization
errors of nodes and links with gridlabd's messages; `GS` refused; the
initial voltages, maximum voltage error, link nominal voltage, and
split-phase neutral; phases taken from a parent; child nodes folded into
their parent (loads added, voltages copied, grandchildren moved, nominal
voltage replaced); a link to a child node deferred until the node
initializes.

test_powerflow_line.py
----------------------

`line` and `line_configuration`: registration (order, parents,
properties); the unbalanced feeder of `test_powerflow_flows.py` built of
`line` objects of configuration 601 (impedance and capacitance per mile)
with `line_capacitance` against `reference()` with NR and FD_XB, and the
same solution as the stand-in line class; without `line_capacitance`,
the capacitance left out with a warning; the terms used for a line on two
phases; the admittance at another nominal frequency; the admittance key
following the configuration; the initialization errors (nominal voltage
mismatch, zero length, missing or wrong configuration, same from and to
node) with gridlabd's messages; a zero-length line refused with every
solver method.

test_powerflow_solver.py
------------------------

`powerflow.solver` on networks built in Python: unbalanced wye loads
through a coupled line with NR, FD_XB, and FD_BX against an independent
fixed-point solution; constant-current, constant-impedance, and delta
loads; branch currents and losses; PV and reference buses; the DC
solution's angles and flows; parallel branches; a branch on two phases;
argument errors, islands without a reference bus, non-convergence.

test_powerflow_flows.py
-----------------------

Models run with `arras.runner.Runner`: the unbalanced feeder (`FEEDER`,
also `data/unbalanced_feeder.glm`) with NR, FD_XB, FD_BX, and FBS (solved
with NR, with a deprecation warning) against `reference()`; link outputs
(currents, powers, losses, totals, flow directions) and their balance
with the loads; reverse flow; open links (an unsupplied node fails the
run; an open link in a loop carries nothing); parallel lines; a
single-phase lateral; a delta node; the base `link` class as
`default_resistance`; DC; PV and swing nodes; the second solution of a
time step changing nothing; `convergence_error_handling`; a model
without nodes; a later model not affected by the module left loaded.
