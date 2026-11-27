# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras Energy `generators` module

The `generators` package implements the gridlabd `generators` module in
Python. This first step ports the classes that a photovoltaic system needs
in event mode: `solar` arrays and the `inverter` objects that connect them
(or a DC source set in the model) to a powerflow `meter` or
`triplex_meter`.

Syntax
------

    module generators {
        message_flags "[QUIET|WARNING|DEBUG|VERBOSE]";
        enable_subsecond_models FALSE;
        deltamode_timestep 1e7 ns;
    }

Classes
-------

| Class | Python class | Models |
| ----- | ------------ | ------ |
| `inverter` | `generators.inverter.Inverter` | a DC to AC inverter: legacy `CONSTANT_PF` types and four-quadrant `CONSTANT_PF` and `CONSTANT_PQ` modes |
| `solar` | `generators.solar.Solar` | a photovoltaic array driven by a `climate` object or by player values |

Globals
-------

- `generators::message_flags`: a `set {QUIET, WARNING, DEBUG, VERBOSE}`
  added to the flags of each generators object.
- `generators::enable_subsecond_models` (`bool`, default `FALSE`): enable
  deltamode in the module. Deltamode is not ported: an inverter with the
  `DELTAMODE` flag fails at init when it is true.
- `generators::deltamode_timestep` (`double`, ns, default `1e7`): the
  deltamode time step; published, not used.

Description
-----------

Users load the module from GLM (`module generators;`) or with
`arras.model.Model.load_module("generators")`. The package is an
`arras.modules` entry point (see `arras.model.MODULE_ENTRY_POINTS`), so
when a model loads the module, `load()` is expected to:

1. load the module in `arras.module.Module.registry`;
2. register the classes `inverter` and `solar` for module `generators` in
   `arras.oclass.Class.registry` (unless they are registered already),
   with the properties, types, keywords, defaults (those of the C++
   `create()` functions), flags, descriptions, pass configuration, and
   technology readiness level that gridlabd publishes; and
3. create the module globals in the model.

Both classes have the event handlers `on_init "python:generators.init"`,
`on_presync "python:generators.presync"`, `on_sync
"python:generators.sync"`, and `on_postsync "python:generators.postsync"`.
They call the behavior that each class's module documents. A gridlabd
`GL_THROW()` in `init()` or `sync()` writes the message of gridlabd's
`INIT_CATCHALL()` or `SYNC_CATCHALL()` (`init_inverter(obj=ID;NAME):
message`) and fails the object, as gridlabd does.

An inverter posts its output to the accumulators of its parent meter
(`current_X` or `current_12` for the legacy types, `power_X` or
`power_12` for four-quadrant) in its bottom-up pass and removes it in its
post-top-down pass. The `powerflow` module solves the network in its
module `sync` solver, after the objects' bottom-up pass, so the solution
of each pass includes the inverters' outputs, as gridlabd's NR solver
does when the swing node synchronizes.

Examples
--------

    >>> from arras import Model, Class
    >>> import generators
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm("module generators;\\n")
    >>> [oclass.name for oclass in generators.classes()]
    ['inverter', 'solar']
    >>> m.globals.get("generators::enable_subsecond_models")
    'FALSE'
    >>> Class.reset()

Caveats
-------

- Not ported yet: the classes `diesel_dg`, `windturb_dg`,
  `power_electronics`, `energy_storage`, `dc_dc_converter`, `rectifier`,
  `microturbine`, `battery`, `central_dg_control`, and `controller_dg`;
  deltamode; and the inverter modes listed in `generators.inverter`.
- The objects get their behavior from class event handlers, so they work
  only in `arras.runner.Runner` simulations; calling the handlers outside
  a run raises `GeneratorsError`.
- See each class's module for its caveats and differences from gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Only `inverter` and `solar` are registered, in that order; gridlabd
   registers twelve classes, `diesel_dg` first and `solar` tenth. The
   order will match gridlabd's once the other classes are ported.

See each class's module for the differences that remain.

References
----------

- `arras-energy/gridlabd`: `module/generators/` (`init.cpp`,
  `generators.h`, `inverter.cpp`, `solar.cpp`, `power_electronics.cpp`,
  and the autotests in `module/generators/autotest/`),
  `source/gridlabd.h` (`INIT_MMF()`, `INIT_CATCHALL()`,
  `SYNC_CATCHALL()`, `gld_object`)
- [Generators module](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Generators.md)
"""

from typing import Any

from arras.module import Module
from arras.oclass import Class

from ._common import (GeneratorsError, MODULE, MESSAGE_FLAGS, TS_INVALID, BEHAVIORS, Throw,
    runner, catchall, object_state)
from .inverter import Inverter
from .solar import Solar

CLASSES = (Inverter, Solar)
"""Behavior of each class of the module, in registration order"""

for _cls in CLASSES:
    BEHAVIORS[_cls.NAME] = _cls

GLOBALS: tuple[tuple[str,Any,str,dict[str,Any]],...] = (
    ("message_flags", None, "set", {"keywords": MESSAGE_FLAGS, "description": "module message control flags"}),
    ("enable_subsecond_models", "FALSE", "bool", {"description": "Enable deltamode capabilities within the generators module"}),
    ("deltamode_timestep", "1e+07", "double", {"unit": "ns", "description": "Desired minimum timestep for deltamode-related simulations"}),
)
"""Module globals as `(name, default, type, Globals.create() options)`, in
gridlabd's order"""

__all__ = ["GeneratorsError", "Inverter", "Solar", "load", "classes", "init", "presync", "sync", "postsync"]

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
    for name, value, ptype, options in GLOBALS:
        gname = f"{MODULE}::{name}"
        if not globs.isdefined(gname):
            globs.create(gname, value, ptype=ptype, **options)

def classes() -> list[Class]:
    """Classes registered for the module, in registration order"""
    return [oclass for oclass in Class.registry if oclass.module == MODULE]

def _behavior(model:Any, name:str) -> Any:
    oclass = model.objects[name].oclass
    if oclass.module != MODULE or oclass.name not in BEHAVIORS:
        raise GeneratorsError(f"object '{name}' is not a generators object")
    return BEHAVIORS[oclass.name]

def init(name:str, t:int) -> bool|int:
    """`on_init` event handler

    Exceptions
    ----------
    - `GeneratorsError`: no simulation is running, or the object is not a
      generators object
    """
    model = runner().model
    cls = _behavior(model, name)
    try:
        result = cls.init(model, name, t)
    except Throw as err:
        catchall("init", model, name, err)
        return False
    if result is True:
        object_state(model, name)["initialized"] = True
    return result

def _sync(event:str, name:str, t:int) -> int:
    model = runner().model
    cls = _behavior(model, name)
    try:
        return getattr(cls, event)(model, name, t)
    except Throw as err:
        catchall("sync", model, name, err)
        return TS_INVALID

def presync(name:str, t:int) -> int:
    """`on_presync` event handler (see `init()`)"""
    return _sync("presync", name, t)

def sync(name:str, t:int) -> int:
    """`on_sync` event handler (see `init()`)"""
    return _sync("sync", name, t)

def postsync(name:str, t:int) -> int:
    """`on_postsync` event handler (see `init()`)"""
    return _sync("postsync", name, t)
