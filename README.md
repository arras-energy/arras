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

`assert` is a Python keyword, so the package is imported with `importlib.import_module("assert")`. See the [`assert` documentation](https://arras-energy.github.io/arras/assert.html) for its classes `assert`, `double_assert`, `complex_assert`, `enum_assert`, and `int_assert`, and the differences from gridlabd. A distribution can provide other modules the same way, as an `arras.modules` entry point (see [`arras.model`](https://arras-energy.github.io/arras/arras/model.html)).

## Testing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest pytest-cov
pytest --cov
```

See `src/arras/_test/README.md` and `src/assert/_test/README.md` for what the tests check. The coverage report for `main` is published at https://arras-energy.github.io/arras/coverage/.

## Source Code Repositories

See https://github.com/arras-energy for the project's repositories.
