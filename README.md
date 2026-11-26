[![Validation](https://github.com/arras-energy/arras/actions/workflows/validate.yaml/badge.svg)](https://github.com/arras-energy/arras/actions/workflows/validate.yaml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Farras-energy.github.io%2Farras%2Fcoverage%2Fbadge.json)](https://arras-energy.github.io/arras/coverage/)
[![Documentation](https://github.com/arras-energy/arras/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/arras-energy/arras/actions/workflows/deploy-pages.yml)

# Welcome

[Arras Energy](https://www.arras.energy/) is a release of [HiPAS GridLAB-D](https://github.com/slacgismo/hipas-gridlabd) supported by the Linux Foundation under LF Energy. [GridLAB-D](https://www.gridlabd.org/) was developed at Pacific Northwest National Laboratory with funding from the US Department of Energy.

## Documentation

See https://arras-energy.github.io/arras for the command line interface and supporting modules.

See https://docs.gridlabd.us/ for documentation of the HiPAS GridLAB-D simulator.

## Python API

`arras.Globals` holds the GridLAB-D global variables with the defaults that `gridlabd` uses. Users get, set, and create globals, and evaluate the `${...}` pseudo-globals and expansions that GLM files use:

```python
>>> from arras import Globals
>>> g = Globals()
>>> g.get("starttime")
'2000-01-01 00:00:00 UTC'
>>> g.expand("${RANGE,1,5,2}")
'1,3,5'
```

See the [`arras.globals` documentation](https://arras-energy.github.io/arras/arras/globals.html) for the full list.

`arras.Class` holds GridLAB-D object class definitions. Users register classes, declare properties as a GLM `class { ... }` block does, look up properties through the inheritance chain, and print a class as `gridlabd --modhelp` does:

```python
>>> from arras import Class
>>> node = Class("node", module="powerflow")
>>> node.publish("voltage_A[V]", "complex")
<Property node.voltage_A:complex[V]>
>>> test = Class.declare("test")
>>> test.set_parent(node)
>>> test.add_property("x", "double", unit="MW")
<Property test.x:double[MW]>
>>> test.find_property("voltage_A").oclass.name
'node'
```

See the [`arras.oclass` documentation](https://arras-energy.github.io/arras/arras/oclass.html) for the rules each method follows.

`arras.Units` is the GridLAB-D unit manager. It reads the same `unitfile.txt` that `gridlabd` uses, derives compound units such as `m/s` on request, and converts values between units with the same dimensions:

```python
>>> from arras import Units
>>> units = Units()
>>> round(units.convert(212,"degF","degC"),3)
99.999
>>> round(units.convert(1,"kWh","Btu"),3)
3412.969
```

See the [`arras.units` documentation](https://arras-energy.github.io/arras/arras/units.html) for the unit file syntax and the gridlabd parsing behaviors it reproduces.

`arras.Model` holds a gridlabd model: globals, modules, the classes that modules provide and the runtime classes that GLM `class` blocks declare, schedules, filters, and objects keyed on name. Users read and write GLM and gridlabd's JSON format, search objects with regular expressions, add and delete objects, and get and set properties, which are checked against the object's class:

```python
>>> from arras import Model
>>> m = Model()
>>> m.read_glm("""
... class meter { double power[kW]; enumeration {OFF=0, ON=1} status; }
... object meter { name m1; power 1.5 MW; }
... """)
>>> m.get_property("m1", "power")
'1500.0 kW'
>>> m.add_object("meter", "m2", status="ON", parent="m1")
'm2'
>>> m.find("^m")
['m1', 'm2']
>>> m.write_json("model.json")  # doctest: +SKIP
```

Module classes come from JSON that gridlabd writes (`gridlabd -o FILE.json` or `gridlabd --modhelp=json MODULE`), read with `Model.load_classes()` or `Model.read_json()`. See the [`arras.model` documentation](https://arras-energy.github.io/arras/arras/model.html) for the value checks, the GLM directives supported, and the differences from gridlabd.

`arras.Module` holds a GridLAB-D module: its version, the classes it registers, and the solvers that keep the simulation clock synchronized. Users attach Python callables to the hooks that gridlabd modules export (`on_sync`, `clock_update`, the deltamode functions, ...) and run the dispatchers, which call every loaded module in load order and combine the results as the gridlabd core does:

```python
>>> from arras import Module
>>> tape = Module("tape", sync=lambda t: t + 3600)
>>> recorder = tape.register_class("recorder", passconfig="BOTTOMUP")
>>> powerflow = Module("powerflow", sync=lambda t: -(t + 60))
>>> Module.syncall(946684800)
-946684860
```

A negative time is a soft event; the earliest time by absolute value is kept. Class heartbeat solvers (`set_heartbeat()`) and the core's internal items (random variables, schedules, loadshapes, transforms, and enduses, added with `Module.add_internal()`) are combined the same way by `Module.internalsyncall()`, which gridlabd runs before each set of object passes. See the [`arras.module` documentation](https://arras-energy.github.io/arras/arras/module.html) for each solver's arguments and the dispatchers' rules.

`arras.Runner` solves the quasi-steady time series of a model in Python, as the gridlabd core main loop does, without running `gridlabd`. The `arras` command uses it: `arras -D NAME=VALUE model.glm -o result.json`. Objects get their behavior from GLM event handlers such as `on_sync "python:module.function";`, a Python function called as `function(name, t)` that returns the time of the object's next event. Modules get theirs from the solvers attached to `arras.Module` and from the `on_init(t)` ... `on_term(t)` functions of a Python module `NAME.py` that the model loads with `module NAME;`; internal items and class heartbeats are synchronized at each time, as gridlabd does. Users run a simulation in the foreground, or in a background thread with a progress callback that takes any of the optional arguments `timestamp`, `percent`, `stdout`, and `stderr`:

```python
>>> from arras import Runner
>>> done = []
>>> r = Runner("model.glm", background=True, progress=lambda percent: done.append(percent))  # doctest: +SKIP
>>> r.running  # doctest: +SKIP
True
>>> r.wait()  # doctest: +SKIP
0
>>> done[-1]  # doctest: +SKIP
100.0
```

See the [`arras.runner` documentation](https://arras-energy.github.io/arras/arras/runner.html) for the command line options, the synchronization passes, the handler rules, and the differences from gridlabd.

## gridlabd modules in Python

Some gridlabd modules are ported to Python packages that are installed with `arras`. A model loads one as gridlabd does, with `module NAME;`, and its objects work in `arras.Runner` simulations. The first is the `assert` module, whose objects check properties at each time step and stop the simulation when a check fails:

```python
>>> from arras import Model, Runner
>>> m = Model()
>>> m.read_glm("""
... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
... module assert;
... class meter { complex voltage_A[V]; }
... object meter {
...     name "m1";
...     voltage_A 120+1j;
...     object assert { target "voltage_A"; part "mag"; relation "inside"; lower 119; upper 121; };
...     object complex_assert { target "voltage_A"; value 120; operation REAL; within 0.1; };
... }
... """)
>>> Runner(model=m).returncode
0
```

`assert` is a Python keyword, so the package is imported with `importlib.import_module("assert")`. See the [`assert` documentation](https://arras-energy.github.io/arras/assert.html) for its classes `assert`, `double_assert`, `complex_assert`, `enum_assert`, and `int_assert`, and the differences from gridlabd.

The `climate` module gives the weather of a site at each time step, read from a TMY2, TMY3, or CSV weather file, with the solar position, the solar flux on surfaces facing nine directions, the heat index, and an optional cloud model:

```python
>>> from arras import Model, Runner
>>> m = Model()
>>> m.read_glm("""
... clock { starttime "2020-07-01 12:00:00 UTC"; stoptime "2020-07-01 12:00:00 UTC"; }
... module climate;
... object climate { name "site"; tmyfile ""; temperature 90; humidity 0.5; }
... """)
>>> Runner(model=m).returncode
0
>>> m.get_property("site", "temperature")
'90'
```

With `tmyfile ""` the model sets the weather; a file name is searched as given, then in the folders of the `climate::library_path` global. See the [`climate` documentation](https://arras-energy.github.io/arras/climate.html) for its classes `climate`, `weather`, and `csv_reader`, the class functions, and the differences from gridlabd.

The `tape` module plays values from files into a model and records properties to files. The file `-` writes to the run's output:

```python
>>> from arras import Model, Runner
>>> m = Model()
>>> m.read_glm("""
... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 02:00:00 UTC"; }
... module tape { csv_header_type NAME; }
... class load { double power[kW]; }
... object load { power 1.5; object recorder { property "power[W]"; file "-"; interval 3600; }; }
... """)
>>> Runner(model=m).stdout
['timestamp,power[W]', '2020-01-01 00:00:00 UTC,+1500 W', '2020-01-01 01:00:00 UTC,+1500 W']
```

The file operations of gridlabd's separate `tape_file` module are part of the `tape` package; the `memory` and `plot` tape modes are not implemented. See the [`tape` documentation](https://arras-energy.github.io/arras/tape.html) for its classes `player`, `shaper`, `recorder`, `multi_recorder`, `collector`, `histogram`, `group_recorder`, `violation_recorder`, `metrics_collector`, `metrics_collector_writer`, and `multiplayer`, and the differences from gridlabd. 

The `pypower` module describes a transmission network as PYPOWER case tables (buses, branches, generators, generator costs, DC lines) and solves its power flow, or optimal power flow, whenever its inputs change. Loads, powerplants, powerlines, transformers, shunts, and relays reduce detailed models to those tables, and Python functions in a controllers module can control them:

```python
>>> from arras import Model, Runner
>>> m = Model()
>>> m.read_glm("""
... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
... module pypower;
... object bus { name b1; type REF; baseKV 230 kV; object gen { name g1; Pmax 200 MW; Qmax 100 MVAr; Qmin -100 MVAr; }; }
... object bus { name b2; type PQ; baseKV 230 kV; Pd 50 MW; Qd 20 MVAr; }
... object branch { from b1; to b2; r 0.01; x 0.1; b 0.02; rateA 100 MVA; }
... """)
>>> Runner(model=m).returncode
0
>>> round(float(m.get_property("b2", "Vm")), 4), round(float(m.get_property("g1", "Pg")), 2)
(0.9741, 50.3)
```

PYPOWER 5.1.16, the version gridlabd pins, is vendored in the package, so `arras` needs numpy and scipy. See the [`pypower` documentation](https://arras-energy.github.io/arras/pypower.html) for its classes `bus`, `branch`, `dcline`, `gen`, `gencost`, `geodata`, `load`, `powerplant`, `powerline`, `relay`, `scada`, `shunt`, `transformer`, and `weather`, the controllers module, and the differences from gridlabd.

The `powerflow` module solves the unbalanced three-phase power flow of a distribution network of nodes and links. Its first version implements the base classes `powerflow_object`, `node`, and `link`, then `fuse`, `line`, the `overhead_line`, `underground_line`, and `triplex_line` subclasses (matrices from conductors and spacing by Carson's equations; triplex lines are not solved yet), `transformer` and `regulator` (with automatic tap control), and the library classes (line, transformer, and regulator configurations, spacings, conductors, pole configurations, and the settings of `restoration` and `power_metrics`) (impedance and capacitance matrices per mile); the other gridlabd powerflow classes (switches, loads, meters, ...) are to follow. gridlabd's Newton-Raphson solver is replaced by the vendored PYPOWER, given the network in phase coordinates (one bus per node phase, the full 3x3 link admittances), so unbalanced flows are solved without a sequence reduction. `solver_method` is `NR` (the default), `FD_XB`, `FD_BX`, or `DC`; `FBS` is deprecated and solved with NR:

```python
>>> from arras import Model, Runner
>>> m = Model()
>>> m.read_glm("""
... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
... module powerflow { solver_method NR; }
... object node { name n1; phases ABCN; nominal_voltage 2401.8; bustype SWING; }
... object link { name l1; from n1; to n2; phases ABCN; }
... object node { name n2; phases ABCN; nominal_voltage 2401.8; power_A 100000+50000j; power_B 50000; }
... """)
>>> Runner(model=m).returncode
0
>>> m.get_property("l1", "flow_direction")
'CN|BF|AF'
```

Node loads (`power_X`, `current_X`, `shunt_X`, wye or delta) are positive when they draw power. A link of the base class is a small resistance (`powerflow::default_resistance`) on each phase; a `line` takes its impedance from its configuration and length, and its shunt capacitance too when `powerflow::line_capacitance` is true. A `fuse` blows a phase whose current exceeds its `current_limit` and is replaced after its `mean_replacement_time`. See the [`powerflow` documentation](https://arras-energy.github.io/arras/powerflow.html) for the classes, the solver, and the differences from gridlabd.

A distribution can provide other modules the same way, as an `arras.modules` entry point (see [`arras.model`](https://arras-energy.github.io/arras/arras/model.html)).

## Testing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest pytest-cov
pytest --cov
```

See `src/arras/_test/README.md`, `src/assert/_test/README.md`, `src/climate/_test/README.md`, `src/tape/_test/README.md`, `src/pypower/_test/README.md`, and `src/powerflow/_test/README.md` for what the tests check. The coverage report for `main` is published at https://arras-energy.github.io/arras/coverage/.

## Source Code Repositories

See https://github.com/arras-energy for the project's repositories.
