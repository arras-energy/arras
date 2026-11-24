# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras Energy `assert` module

The `assert` package implements the gridlabd `assert` module in Python. Its
objects check properties of other objects at each time step of an
`arras.runner.Runner` simulation and stop the simulation when a check
fails, which is how gridlabd models test themselves.

Syntax
------

    module assert {
        message_flags "[QUIET|WARNING|DEBUG|VERBOSE]";
    }

Classes
-------

| Class | Python class | Checks |
| ----- | ------------ | ------ |
| `assert` | `assert.g_assert.Assert` | any property (or a part of it) of the parent, of a group of objects, or a global variable, against a value with a relation |
| `double_assert` | `assert.double_assert.DoubleAssert` | a `double` property against a value and tolerance |
| `complex_assert` | `assert.complex_assert.ComplexAssert` | a `complex` property, or its real part, imaginary part, magnitude, or angle |
| `enum_assert` | `assert.enum_assert.EnumAssert` | an `enumeration` property against an integer |
| `int_assert` | `assert.int_assert.IntAssert` | an `int16`, `int32`, or `int64` property against a value and tolerance |

Globals
-------

- `assert::message_flags`: a `set {QUIET, WARNING, DEBUG, VERBOSE}` added
  to the flags of each assert object: `QUIET` turns off the object's error
  messages, `WARNING` its warning messages, and `VERBOSE` turns on its
  verbose messages (when the `verbose` global is also set).

Description
-----------

`assert` is the name of a gridlabd module and a Python keyword, so the
package is imported with `importlib.import_module("assert")`, not with an
`import` statement. Users load it from GLM (`module assert;`) or with
`arras.model.Model.load_module("assert")`. The package is an
`arras.modules` entry point (see `arras.model.MODULE_ENTRY_POINTS`), so
when a model loads the module, `load()` is expected to:

1. load the module in `arras.module.Module.registry`;
2. register the classes `assert`, `double_assert`, `complex_assert`,
   `enum_assert`, and `int_assert` for module `assert` in
   `arras.oclass.Class.registry` (unless they are registered already),
   with the properties, types, keywords, defaults, flags, descriptions,
   pass configuration (`AUTOLOCK|OBSERVER`), and technology readiness
   level (9) that gridlabd publishes; and
3. create the `assert::message_flags` global in the model.

Each class has the class event handlers `on_init "python:assert.init"` and
`on_commit "python:assert.commit"`, so the runner calls `init()` when it
initializes an assert object and `commit()` at each committed time. These
call the behavior of the object's class, documented in each class's
module.

Examples
--------

The gridlabd autotest `test_double_assert_err.glm`, with the `climate`
class declared in GLM because `arras` has no `climate` module:

    >>> import importlib
    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 01:00:00 UTC"; }
    ... module assert;
    ... class climate { double temperature[degF]; }
    ... object climate {
    ...     name "weather";
    ...     temperature 50;
    ...     object double_assert { target "temperature"; value 50; within 1; };
    ... }
    ... ''')
    >>> [oclass.name for oclass in importlib.import_module("assert").classes()]
    ['assert', 'double_assert', 'complex_assert', 'enum_assert', 'int_assert']
    >>> Runner(model=m).returncode
    0
    >>> m.set_property("weather", "temperature", 55)
    >>> r = Runner(model=m)
    >>> r.returncode
    5
    >>> print(r.stderr[0])
    ERROR [2020-01-01 00:00:00 UTC]: Assert failed on weather: temperature 55 not within 1.000000 of given value 50
    >>> Class.reset()

Caveats
-------

- The objects get their behavior from class event handlers, so the
  assert classes work only in `arras.runner.Runner` simulations; calling
  `init()` or `commit()` outside a run raises `AssertError`.
- The deltamode update functions of `double_assert`, `complex_assert`,
  and `enum_assert` are not modeled, because `arras` does not run
  deltamode.
- See each class's module for its caveats and differences from gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16, with the assert fixes)
----------------------------------------------------------------------------------

The package matches gridlabd's `module/assert` with the fixes listed in
DESIGN.md decision 8.4, which are made in both code bases. See each
class's module for the differences that remain.

References
----------

- `arras-energy/gridlabd`: `module/assert/` (`init.cpp`, `assert.cpp`,
  `double_assert.cpp`, `complex_assert.cpp`, `enum_assert.cpp`,
  `int_assert.cpp`, and the autotests in `module/assert/autotest/`),
  `source/gridlabd.h` (`INIT_MMF()`, `gld_object`, `INIT_CATCHALL()`)
- [Assert module](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Assert.md)
  (`docs/Module/Assert.md`)
"""

from typing import Any

from arras.module import Module
from arras.oclass import Class

from ._common import AssertError, MODULE, MESSAGE_FLAGS, runner
from .g_assert import Assert
from .double_assert import DoubleAssert
from .complex_assert import ComplexAssert
from .enum_assert import EnumAssert
from .int_assert import IntAssert

CLASSES = (Assert, DoubleAssert, ComplexAssert, EnumAssert, IntAssert)
"""Behavior of each class of the module, in gridlabd's registration order"""

_BEHAVIOR = {cls.NAME: cls for cls in CLASSES}

def load(model:Any) -> None:
    """Load the module into a model (the `arras.modules` entry point that
    `arras.model.Model.load_module()` calls)

    Arguments
    ---------
    - `model`: `arras.model.Model` that loads the module

    Exceptions
    ----------
    - `arras.oclass.ClassError`: a class of the module cannot be registered
    """
    module = Module.load(MODULE)
    for cls in CLASSES:
        if Class.find(cls.NAME, module=MODULE) is None:
            cls.register(module)
    name = f"{MODULE}::message_flags"
    if not model.globals.isdefined(name):
        model.globals.create(name, None, ptype="set", keywords=MESSAGE_FLAGS,
            description="module message control flags")

def classes() -> list[Class]:
    """Classes registered for the module, in registration order"""
    return [oclass for oclass in Class.registry if oclass.module == MODULE]

def _behavior(model:Any, name:str) -> Any:
    oclass = model.objects[name].oclass
    if oclass.module == MODULE and oclass.name in _BEHAVIOR:
        return _BEHAVIOR[oclass.name]
    raise AssertError(f"object '{name}' is not an object of an assert class")

def init(name:str, t:int) -> bool: # pylint: disable=unused-argument
    """`on_init` event handler of the assert classes

    Exceptions
    ----------
    - `AssertError`: no simulation is running, or the object is not of an
      assert class
    """
    model = runner().model
    return _behavior(model, name).init(model, name)

def commit(name:str, t:int) -> int:
    """`on_commit` event handler of the assert classes

    Exceptions
    ----------
    - `AssertError`: see `init()`
    """
    model = runner().model
    return _behavior(model, name).commit(model, name, t)
