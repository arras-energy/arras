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

## Testing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest pytest-cov
pytest --cov
```

See `src/arras/_test/README.md` for what the tests check. The coverage report for `main` is published at https://arras-energy.github.io/arras/coverage/.

## Source Code Repositories

See https://github.com/arras-energy for the project's repositories.
