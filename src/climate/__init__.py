# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras Energy `climate` module

The `climate` package implements the gridlabd `climate` module in Python.
Its objects give the weather of a site at each time step of an
`arras.runner.Runner` simulation, read from TMY2, TMY3, or CSV weather
files, with the solar position, the solar flux on surfaces facing nine
directions, the heat index, and an optional fractal cloud model.

Syntax
------

    module climate {
        message_flags "[QUIET|WARNING|DEBUG|VERBOSE]";
        library_path "<folder>[:<folder>...]";
    }

Classes
-------

| Class | Python class | Holds |
| ----- | ------------ | ----- |
| `climate` | `climate.climate.Climate` | the weather of a site, from a weather file or set by the model |
| `weather` | `climate.weather.Weather` | one weather sample (the columns of a CSV weather file) |
| `csv_reader` | `climate.csv_reader.CsvReader` | the samples of a CSV weather file, for a `climate` object |

Globals
-------

- `climate::message_flags`: a `set {QUIET, WARNING, DEBUG, VERBOSE}` added
  to the flags of each climate object: `QUIET` turns off its error
  messages, `WARNING` its warning messages, and `VERBOSE` turns on its
  verbose messages (when the `verbose` global is also set).
- `climate::library_path`: the folders searched for weather files after
  the name as given, separated by `:` (or `;`). The default is the
  `weather/US` folder of the `datadir` global, the user `share` folder of
  `arras.folders`.

Description
-----------

Users load the module from GLM (`module climate;`) or with
`arras.model.Model.load_module("climate")`. The package is an
`arras.modules` entry point (see `arras.model.MODULE_ENTRY_POINTS`), so
when a model loads the module, `load()` is expected to:

1. load the module in `arras.module.Module.registry`;
2. register the classes `climate`, `weather`, and `csv_reader` for module
   `climate` in `arras.oclass.Class.registry` (unless they are registered
   already), with the properties, types, keywords, defaults, flags,
   descriptions, pass configuration, and technology readiness level that
   gridlabd publishes, and the class functions of `climate`; and
3. create the `climate::message_flags` and `climate::library_path`
   globals in the model.

Class `climate` has the event handlers `on_init "python:climate.init"`
and `on_presync "python:climate.presync"`, and class `csv_reader` has
`on_init "python:climate.reader_init"`. They call the behavior that each
class's module documents.

Examples
--------

    >>> from arras import Model, Class
    >>> import climate
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm("module climate;\\n")
    >>> [oclass.name for oclass in climate.classes()]
    ['climate', 'weather', 'csv_reader']
    >>> m.globals.get("climate::library_path").endswith("weather/US")
    True
    >>> Class.reset()

Caveats
-------

- The objects get their behavior from class event handlers, so they work
  only in `arras.runner.Runner` simulations; calling the handlers outside
  a run raises `ClimateError`.
- See each class's module for its caveats and differences from gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The default `climate::library_path` is in the `arras` user folder
   (decision 1.12); gridlabd's is `/usr/local/opt/gridlabd/.../weather/US`.
   After the folders of `climate::library_path`, weather files are
   searched with `arras.folders.findfile()` in place of gridlabd's
   `libdir` and `datadir` folders.

See each class's module for the differences that remain.

References
----------

- `arras-energy/gridlabd`: `module/climate/` (`init.cpp`, `climate.cpp`,
  `csv_reader.cpp`, `weather.cpp`, `solar_angles.cpp`, and the autotests
  in `module/climate/autotest/`), `source/gridlabd.h` (`INIT_MMF()`,
  `gld_object`)
- [Climate module](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Climate.md)
  (`docs/Module/Climate.md`)
"""

import os
from typing import Any

from arras.module import Module
from arras.oclass import Class

from ._common import ClimateError, MODULE, MESSAGE_FLAGS, runner
from .climate import Climate, solar_flux, heat_index
from .weather import Weather
from .csv_reader import CsvReader

CLASSES = (Climate, Weather, CsvReader)
"""Behavior of each class of the module, in gridlabd's registration order"""

__all__ = ["ClimateError", "Climate", "Weather", "CsvReader", "load", "classes", "init",
    "presync", "reader_init", "solar_flux", "heat_index"]

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
    globs = model.globals
    name = f"{MODULE}::message_flags"
    if not globs.isdefined(name):
        globs.create(name, None, ptype="set", keywords=MESSAGE_FLAGS,
            description="module message control flags")
    name = f"{MODULE}::library_path"
    if not globs.isdefined(name):
        datadir = globs.get("datadir") if globs.isdefined("datadir") else None
        path = os.path.join(datadir, "weather", "US") if datadir else os.path.join("weather", "US")
        globs.create(name, path, ptype="char1024")

def classes() -> list[Class]:
    """Classes registered for the module, in registration order"""
    return [oclass for oclass in Class.registry if oclass.module == MODULE]

def _check(model:Any, name:str, cls:Any) -> None:
    oclass = model.objects[name].oclass
    if oclass.module != MODULE or oclass.name != cls.NAME:
        raise ClimateError(f"object '{name}' is not a {cls.NAME} object")

def init(name:str, t:int) -> bool|int: # pylint: disable=unused-argument
    """`on_init` event handler of class `climate`

    Exceptions
    ----------
    - `ClimateError`: no simulation is running, or the object is not a
      climate object
    """
    model = runner().model
    _check(model, name, Climate)
    return Climate.init(model, name)

def presync(name:str, t:int) -> int:
    """`on_presync` event handler of class `climate`

    Exceptions
    ----------
    - `ClimateError`: see `init()`
    """
    model = runner().model
    _check(model, name, Climate)
    return Climate.presync(model, name, t)

def reader_init(name:str, t:int) -> bool: # pylint: disable=unused-argument
    """`on_init` event handler of class `csv_reader`

    Exceptions
    ----------
    - `ClimateError`: no simulation is running, or the object is not a
      csv_reader object
    """
    model = runner().model
    _check(model, name, CsvReader)
    return CsvReader.init(model, name)
