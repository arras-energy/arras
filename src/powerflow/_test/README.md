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
  4.1 and 5.1). The tests of the solver and flows use this
  class in place of gridlabd's line classes and shows how a link class supplies its
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

test_powerflow_fuse.py
----------------------

`fuse`: registration (parent, readiness level, defaults, keywords); the
`(1+j)/R` admittance of each phase with the default resistance; a phase
blowing above `current_limit` with gridlabd's warnings, the node it feeds
losing that phase, and the replacement after `mean_replacement_time` (a
soft event) and blowing again; a blown fuse in a loop; a blown fuse
cutting off more than its node failing the run; `status OPEN`;
exponential replacement durations repeatable with `randomseed`; the
initialization warnings and errors (triplex, negative limit, FD_XB and
DC); FBS solved with NR.

test_powerflow_library.py
-------------------------

The library classes: registration (order, no parent, readiness levels,
defaults, the `climate_impact_zone` global); valid objects of every class
(phase ratings split, degradation rate from the table); the
`transformer_configuration` `resistance`/`reactance`/`impedance` sharing
(last one set wins); center-tapped impedances from losses and copied
secondary impedances; the shunt warning only for a shunt impedance that
is not the default; the pole diameter; the `restoration` output file
emptied, FBS refused, unnamed links reported as `Unnamed`, and
`perform_restoration()` failing without `fault_check`; the
initialization errors and warnings of each class with gridlabd's
messages; `triplex_line_configuration` accepted by a `line` as a
`line_configuration`; the `power_metrics` indices, resets, extra data,
`fault_check` requirement, and log file header.

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

test_powerflow_line_subclasses.py
---------------------------------

`overhead_line`, `underground_line`, and `triplex_line`: registration
(parents, properties); the overhead impedance and capacitance of
Kersting's examples 4.1 and 5.1, and an independent Kron reduction of a
two-phase line; the matrix form; an overhead line solved as a `line` with
its impedance in matrix form; capacitance left out with a warning when a
height is missing; the initialization errors with gridlabd's messages; a
conductor change taken into the matrices; the underground impedance and
capacitance of the concentric-neutral cables of examples 4.3 and 5.2 and
the tape-shielded cable of example 4.4; the underground conductor
message; the triplex `b_mat` and `tn` from an independent computation,
the solver refusing triplex lines, and the triplex warnings and errors
(no phase S, bad diameter or insulation, missing conductor, unsupported
method, z-matrix with a method other than NR).

test_powerflow_transformer.py
-----------------------------

`transformer` and `regulator`: registration; transformer secondary
voltages against independent fixed-point solutions of `V2 = C V1 - zt I`
for wye-wye (NR, FD_XB, FD_BX), delta-wye step-down and step-up (the
30-degree lag and lead), and a single-phase transformer with a
degradation factor; the delta-wye admittance blocks; DC angles with the
delta-wye shift; a transformer listed before its configuration; the
center-tapped transformer refused by the solver; initialization errors
and the thermal-model warning. Regulator no-load output `V1/a` for types
A and B; its admittance blocks; the first-run tap jump; the dwell and
time-delay timing of tap steps; banked remote-node control; line drop
compensation (the monitored voltage formula); the reverse-flow lock; two
regulators sharing a configuration; FD_XB and DC solutions;
initialization errors and the zero-resistance warning.

test_powerflow_switch.py
------------------------

`switch`, `recloser`, and `sectionalizer`: registration (parents, readiness
level, defaults); a closed switch's default impedance `default_resistance*(1-j)`
and its voltage drop and power; the impedance parts and the zero-part
warning; an open switch isolating its to node; the banked majority rule
at initialization and during the run; individual phases; the published
`change_switch_state`; the FD_XB, FD_BX, and DC methods with an open
phase; the triplex error; the recloser defaults, warnings, tries reset,
and `change_recloser_state`; the sectionalizer's `change_sectionalizer_state`.

test_powerflow_load.py
----------------------

`load` and `capacitor`: registration; the unbalanced feeder with its
loads in `load` objects (complex and part properties, explicit delta,
constant current, impedance) against `reference()` with NR and FD_BX, and
the measured voltages; a part changed during a run; a delta (phase `D`)
load; the ZIP form and its sum warning; frequency-dependent impedances;
the triplex error. A closed capacitor against a node with the same shunt
admittance; a manual change after the time delay; VOLT control closing
the capacitors and counting the switches; banked VAR control after the
dwell time; a delta capacitor on a wye node; initialization errors.

test_powerflow_triplex.py
-------------------------

`meter`, `triplex_node`, `triplex_meter`, `triplex_load`, and split-phase
solutions: registration (parents, `isa("node")`, the
`market_price_name` global); a center-tapped transformer and triplex line
feeder with unbalanced 120 V and 240 V loads against an independent
physical solution (Kersting's center-tapped transformer with gridlabd's
impedance split, the triplex line with its neutral Kron-reduced); the
triplex meter's currents (line 2 physical, neutral), power, and demand;
energies and interval energy over two hours; a uniform bill; price
errors and tier filling; triplex node accumulators equal to a
triplex_load; the triplex ZIP form and its warning; the missing phase S
warning; meter power consumption; DC, and FD on a center-tapped
transformer. A three-phase meter's currents and powers from the link
that feeds it, a tiered bill, and a swing meter.

test_powerflow_zipload.py
-------------------------

`zipload`, `triplex_zipload`, and `pqload`: registration (parents,
readiness levels, defaults, units); schedule parsing (wildcards, ranges,
wrapping ranges, lists, errors); a zipload's constant terms against the
equivalent load; heating degrees and the schedule value of the hour; the
per-unit voltage check; a missing weather property; load data from a CSV
file and a missing row; a triplex zipload's 240 V load; a pqload's
power, impedance, and current against the equivalent load, and its
weather inputs.

test_powerflow_substation.py
----------------------------

`substation`: registration; the sequence-to-phase conversion and each
reference phase; swing voltages from sequence voltages, with the
distribution power, current, and voltages against the link it feeds;
the normal-node mode and the default warnings; the three-phase
requirement; energy over two hours; a `pypower` load parent (voltage in,
power, current, and impedance posted) and a nominal voltage mismatch;
a node parent.

test_powerflow_motor.py
-----------------------

`motor`: registration; the single-phase model (torque balance, current
solved with the final voltage, drawn on its phase); the three-phase model
(sequence flux steady state, torque balance, phase currents drawn,
power); a stationary start; override off; stall, trip, and reconnect
timing; the phase count check; the three triplex connections.

test_powerflow_vfd.py
---------------------

`vfd`: registration and the efficiency fit; a steady drive with NR and
FD (output source voltage and phases, output power against its loads,
input power over the efficiency, input currents); the frequency ramp at
1 s steps and its soft event; an off drive taking out what it feeds; a
steady start; initialization errors and warnings.

test_powerflow_solver.py
------------------------

`powerflow.solver` on networks built in Python: unbalanced wye loads
through a coupled line with NR, FD_XB, and FD_BX against an independent
fixed-point solution; constant-current, constant-impedance, and delta
loads; fixed currents (the line carries them exactly, the swing buses supply them) and split fixed currents; branch currents and losses; PV and reference buses; the DC
solution's angles and flows; parallel branches; a branch on two phases;
argument errors, islands without a reference bus (also a phase cut off
but coupled to the others by a line), non-convergence.

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
