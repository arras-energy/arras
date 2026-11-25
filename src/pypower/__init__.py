# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras Energy `pypower` module

The `pypower` package implements the gridlabd `pypower` module in Python.
Its objects describe a transmission or subtransmission network as
PYPOWER's case tables (buses, branches, generators, generator costs, DC
lines), with model objects that reduce detailed models to those tables
(loads, powerplants, powerlines, transformers, shunts, relays), weather
and geodata inputs, and SCADA points. During an `arras.runner.Runner`
simulation, users solve the network with PYPOWER's power flow (or optimal
power flow) whenever its inputs change, and can control loads,
powerplants, relays, and the solver data from Python functions in a
controllers module.

Syntax
------

    module pypower {
        version <integer>;
        solver_method {NR,FD_XB,FD_BX,GS};
        maximum_timestep <real> s;
        baseMVA <real> MVA;
        enable_opf {TRUE,FALSE};
        opf_update_interval <real> s;
        stop_on_failure {TRUE,FALSE};
        save_case {TRUE,FALSE};
        save_format {CSV,JSON,PY};
        controllers_path "<folder>";
        controllers "<python-module>";
        solver_update_resolution <real>;
        maximum_iterations <integer>;
        solution_tolerance <real>;
        enforce_q_limits {TRUE,FALSE};
        use_dc_powerflow {TRUE,FALSE};
        with_emissions {TRUE,FALSE};
        maximum_iterations_opf <integer>;
        opf_feasibility_tolerance <real>;
        opf_gradient_tolerance <real>;
        opf_condition_tolerance <real>;
        opf_cost_tolerance <real>;
        autosize_angle <real> rad;
        default_dcline_loss0 <real> MW;
        default_dcline_loss1 <real> MW/MW;
        default_reactive_power_fraction <real> pu;
        minimum_voltage_magnitude_deadband <real> pu.kV;
        minimum_voltage_angle_deadband <real> deg;
        timestamp_format "<format>";
        message_flags {QUIET,WARNING,DEBUG,VERBOSE}[|...];
    }

Classes
-------

| Class | Python class | Does |
| ----- | ------------ | ---- |
| `bus` | `pypower.bus.Bus` | PYPOWER bus; base load, weather values and sensitivities |
| `branch` | `pypower.branch.Branch` | PYPOWER branch; autosizing |
| `dcline` | `pypower.dcline.Dcline` | PYPOWER DC line |
| `gen` | `pypower.gen.Gen` | PYPOWER generator |
| `gencost` | `pypower.gencost.Gencost` | PYPOWER generator cost (OPF) |
| `geodata` | `pypower.geodata.Geodata` | plays values by location into objects |
| `load` | `pypower.load.Load` | ZIP load on a bus, with a controller |
| `powerplant` | `pypower.powerplant.Powerplant` | power plant on a bus or generator, with a controller |
| `powerline` | `pypower.powerline.Powerline` | line impedance of a branch, in series or parallel |
| `relay` | `pypower.relay.Relay` | controlled switch on a branch |
| `scada` | `pypower.scada.Scada` | points shared with the controllers module |
| `shunt` | `pypower.shunt.Shunt` | voltage-controlled shunt on a bus |
| `transformer` | `pypower.transformer.Transformer` | transformer parameters of a branch |
| `weather` | `pypower.weather.Weather` | weather values for powerplant derating |

Globals
-------

- `pypower::version`: PYPOWER case version (2).
- `pypower::solver_method`: `NR` (Newton-Raphson, default), `FD_XB`,
  `FD_BX` (fast-decoupled), `GS` (Gauss-Seidel).
- `pypower::maximum_timestep`: the longest time (s) between solutions (0:
  no limit).
- `pypower::baseMVA`: base MVA (100).
- `pypower::enable_opf`: solve an OPF with the `gencost` data.
- `pypower::opf_update_interval`: interval (s) at which OPF results are
  received (0: always).
- `pypower::stop_on_failure`: stop the run when the solver fails.
- `pypower::save_case`, `pypower::save_format`: write the solver's case
  data and results to files (`CSV`, `JSON`, `PY`).
- `pypower::controllers_path`, `pypower::controllers`: folder and name of
  the Python controllers module.
- `pypower::solver_update_resolution`: smallest difference that counts as
  a change (1e-8).
- `pypower::maximum_iterations`, `pypower::solution_tolerance`: solver
  limits (0: PYPOWER's defaults).
- `pypower::solver_status`: `INIT`, `SUCCESS`, `FAILED` (output).
- `pypower::enforce_q_limits`, `pypower::use_dc_powerflow`: PYPOWER
  options.
- `pypower::total_loss`, `pypower::generation_shortfall`: system line
  losses and generation above `Pmax` (MW, outputs).
- `pypower::with_emissions`: compute powerplant emissions.
- `pypower::maximum_iterations_opf` (10),
  `pypower::opf_feasibility_tolerance` (1.3),
  `pypower::opf_gradient_tolerance` (3.0),
  `pypower::opf_condition_tolerance` (1000), `pypower::opf_cost_tolerance`
  (0.01): PIPS OPF options.
- The class globals listed in each class's module, and
  `pypower::message_flags`, which is ORed into the flags of every object
  when its messages are written.

Description
-----------

Users load the module from GLM (`module pypower;`) or with
`arras.model.Model.load_module("pypower")`. The package is an
`arras.modules` entry point, so when a model loads the module, `load()` is
expected to:

1. load the module in `arras.module.Module.registry` with the solvers
   `init`, `precommit`, `sync`, `commit`, and `term`;
2. register the classes above for module `pypower` in
   `arras.oclass.Class.registry` (unless they are registered already), in
   gridlabd's registration order, with the properties, types, units,
   keywords, defaults, flags, descriptions, pass configurations, and
   technology readiness levels that gridlabd publishes; and
3. create the globals above in the model.

During a run, the module is expected to:

1. initialize once, before its first object initializes: import the
   controllers module (when `controllers` is set; `controllers_path` is
   added to `sys.path`), call its `on_init()` (which must return `True`),
   and keep its `on_precommit`, `on_sync`, `on_commit`, and `on_term`
   functions; and allocate the solver data with the options above (read
   once, here); warn when `enable_opf` is true and the numbers of `gen`
   and `gencost` objects differ;
2. do nothing in its solvers when there is no bus or no branch;
3. at each precommit (after the objects' precommits), send the object
   values to the solver data and call the controllers' `on_precommit(data)`,
   if any, then ask for an event at most `maximum_timestep` later and at
   the next multiple of `opf_update_interval`;
4. at each sync (after the objects' syncs), send the bus, branch, gen,
   gencost, and dcline values that changed by more than
   `solver_update_resolution`, call the controllers' `on_sync(data)`, if
   any, and run the solver (`pypower.solver.solver()`) the first time and
   whenever an input that matters changed; then copy the solution back:
   bus `Vm`, `Va` (and the OPF multipliers when the OPF results are
   received), branch `current` and `loss`, generator `Pg`, `Qg`, `apf`
   (or the setpoints of generators with powerplants when the OPF results
   are received), `pypower::total_loss` and
   `pypower::generation_shortfall`; when a value changed, ask to run again
   at once, else at the controller's time or `maximum_timestep` later;
5. on solver failure, set `solver_status` to `FAILED` and stop the run
   with an error when `stop_on_failure` is true, else warn and go on;
6. at each commit, call the controllers' `on_commit(data)`, if any; a
   result at or before the clock stops the run;
7. at the end, call the controllers' `on_term()`, if any.

A controllers function `on_precommit`, `on_sync`, or `on_commit` takes the
solver data `dict` (with the time `t`) and returns the time of its next
call: a negative time means never, 0 stops the run when
`stop_on_failure` is true, and a time before the clock or a value that is
not an integer stops the run. Object controllers are described in the
`load`, `powerplant`, and `relay` modules; `scada` objects add the
globals `scada` and `historian` to the controllers module.

Error messages of objects and of the module are written as gridlabd's
`gl_error()` writes them, and make the run end with exit code `RUNERR`
without stopping it (`arras.runner.Runner.setexitcode()`), as in gridlabd.

Examples
--------

    >>> from arras import Model, Class
    >>> import pypower
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm("module pypower { solver_method GS; }\\n")
    >>> [oclass.name for oclass in pypower.classes()]
    ['bus', 'branch', 'dcline', 'gen', 'gencost', 'geodata', 'load', 'powerplant', 'powerline', 'relay', 'scada', 'shunt', 'transformer', 'weather']
    >>> m.globals.get("pypower::solver_method"), m.globals.get("pypower::baseMVA")
    ('GS', '+100 MVA')
    >>> Class.reset()

Caveats
-------

- The objects get their behavior from class event handlers, so they work
  only in `arras.runner.Runner` simulations; calling the handlers outside
  a run raises `PypowerError`.
- PYPOWER is vendored in `pypower._pypower` (PYPOWER 5.1.16, the version
  gridlabd pins), because this package takes PYPOWER's import name
  `pypower`; numpy and scipy are required.
- The solver data and options are those of the run; the controllers
  module is imported again (a new module object) for each run.
- When the `modelname` global is empty (`arras` does not set it), the
  name of the first model file of the run is used to name saved case
  files, without its extension; models built in memory use `pypower`.
- The `gridlabd` object that gridlabd adds to the controllers module is
  not added.
- `arras.runner.Runner` initializes modules after objects, while
  gridlabd's `init_all()` initializes modules first; the module therefore
  initializes itself when its first object initializes, until the runner
  offers `preinit` and `postinit` module events (#57).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The module's precommit result is an event, as `arras.runner` uses
   module precommit results (runner decision 2.13): `maximum_timestep`,
   `opf_update_interval`, and the controllers' `on_precommit` times are
   posted from the precommit as well as from the sync. gridlabd's core
   discards module precommit times. The runner keeps a precommit event
   only while the time step does not iterate, and a first solution
   usually makes it iterate (its generator outputs change), so the
   difference shows mostly for `opf_update_interval`.
2. `pypower::total_loss` is the sum of the branch losses of the last
   solution; gridlabd adds each solution's losses to it, so it grows
   during a run (arras-energy/gridlabd#414).
3. Branch OPF multipliers (`mu_sfrom`, `mu_sto`, `mu_angmin`,
   `mu_angmax`) are received from the solution; gridlabd reads them from
   the 13 columns it sends, so it never receives them
   (arras-energy/gridlabd#414).
4. A Python exception in a controller is written as one error line;
   gridlabd prints the traceback (`PyErr_Print()`).
5. See each class's module for the differences that remain.

References
----------

- `arras-energy/gridlabd`: `module/pypower/` (`pypower.cpp`, `pypower.h`,
  `pypower_solver.py`, the class files, and the autotests in
  `module/pypower/autotest/`), `converters/py2glm.py`
- [Pypower module](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Pypower.md)
  (`docs/Module/Pypower.md`, `docs/Module/Pypower/`)
- [PYPOWER](https://github.com/rwl/PYPOWER)
"""

from typing import Any

from arras.module import Module
from arras.oclass import Class

from ._common import MODULE, MESSAGE_FLAGS, PypowerError, runner
from ._module import solver_init, solver_precommit, solver_sync, solver_commit, solver_term
from .bus import Bus
from .branch import Branch
from .dcline import Dcline
from .gen import Gen
from .gencost import Gencost
from .geodata import Geodata
from .load import Load
from .powerplant import Powerplant
from .powerline import Powerline
from .relay import Relay
from .scada import Scada
from .shunt import Shunt
from .transformer import Transformer
from .weather import Weather
from . import solver

CLASSES = (Bus, Branch, Dcline, Gen, Gencost, Geodata, Load, Powerplant, Powerline, Relay, Scada,
    Shunt, Transformer, Weather)
"""Behavior of each class of the module, in gridlabd's registration order"""

GLOBALS: tuple[tuple[str,Any,str,dict[str,Any]],...] = (
    ("message_flags", None, "set", {"keywords": MESSAGE_FLAGS, "description": "module message control flags"}),
    ("autosize_angle", 0.0, "double", {"unit": "rad", "description": "Autosize voltage angle to use (0 for no autosizing)"}),
    ("default_dcline_loss0", 0.0, "double", {"unit": "MW", "description": "Default DC line power loss constant"}),
    ("default_dcline_loss1", 0.05, "double", {"unit": "MW/MW", "description": "Default DC line power loss factor"}),
    ("default_reactive_power_fraction", 0.2, "double", {"unit": "pu", "description": "Default fraction of real power generation available for reactive power"}),
    ("minimum_voltage_magnitude_deadband", 0.002, "double", {"unit": "pu.kV", "description": "Minimum deadband on voltage magnitude control"}),
    ("minimum_voltage_angle_deadband", 0.01, "double", {"unit": "deg", "description": "Minimum deadband on voltage angle control"}),
    ("timestamp_format", "", "char256", {"description": "Format for weather file timestamps ('' is RFC822/ISO8601)"}),
    ("version", 2, "int32", {"description": "Version of pypower used"}),
    ("solver_method", "NR", "enumeration", {"keywords": {"GS": 4, "FD_BX": 3, "FD_XB": 2, "NR": 1}, "description": "PyPower solver method to use"}),
    ("maximum_timestep", 0.0, "double", {"unit": "s", "description": "Maximum timestep allowed between solutions"}),
    ("baseMVA", 100.0, "double", {"unit": "MVA", "description": "Base MVA value"}),
    ("enable_opf", False, "bool", {"description": "Flag to enable optimal powerflow (OPF) solver"}),
    ("opf_update_interval", 0.0, "double", {"unit": "s", "description": "Interval at which to update OPF solution (only if enable_opf is TRUE, 0 is always)"}),
    ("stop_on_failure", False, "bool", {"description": "Flag to stop simulation on solver failure"}),
    ("save_case", False, "bool", {"description": "Flag to save pypower case data and results"}),
    ("controllers_path", "", "char1024", {"description": "Path to find module containing controller functions"}),
    ("controllers", "", "char1024", {"description": "Python module containing controller functions"}),
    ("solver_update_resolution", 1e-8, "double", {"description": "Minimum difference before a value is considered changed"}),
    ("maximum_iterations", 0, "int32", {"description": "Maximum iterations (0 defaults to pypower default for solver_method)"}),
    ("solution_tolerance", 0.0, "double", {"description": "Solver convergence error tolerante (0 defaults to pypower default)"}),
    ("solver_status", "INIT", "enumeration", {"keywords": {"INIT": 0, "SUCCESS": 1, "FAILED": 2}, "description": "Result of the last pypower solver run"}),
    ("enforce_q_limits", False, "bool", {"description": "Enable enforcement of reactive power limits"}),
    ("use_dc_powerflow", False, "bool", {"description": "Enable use of DC powerflow solution"}),
    ("save_format", "CSV", "enumeration", {"keywords": {"CSV": 0, "JSON": 1, "PY": 2}, "description": "Save case format"}),
    ("total_loss", 0.0, "double", {"unit": "MW", "description": "System-wide line losses"}),
    ("generation_shortfall", 0.0, "double", {"unit": "MW", "description": "System-wide generation shortfall"}),
    ("with_emissions", False, "bool", {"description": "Include emissions results"}),
    ("maximum_iterations_opf", 10, "int32", {"description": "Maximum iterations allowed for OPF"}),
    ("opf_feasibility_tolerance", 1.3, "double", {"description": "OPF feasibility condition convergence tolerance"}),
    ("opf_gradient_tolerance", 3.0, "double", {"description": "OPF gradient convergence tolerance"}),
    ("opf_condition_tolerance", 1000.0, "double", {"description": "OPF complimentary condition convergence tolerance"}),
    ("opf_cost_tolerance", 0.01, "double", {"description": "OPF cost convergence tolerance"}),
)
"""Module globals `pypower::NAME` in gridlabd's creation order: name,
default, type, and `Globals.create()` options"""

__all__ = ["PypowerError", "Bus", "Branch", "Dcline", "Gen", "Gencost", "Geodata", "Load",
    "Powerplant", "Powerline", "Relay", "Scada", "Shunt", "Transformer", "Weather",
    "load", "classes", "init", "precommit", "presync", "sync", "postsync", "commit",
    "bus", "branch", "dcline", "gen", "gencost", "geodata", "powerplant", "powerline", "relay",
    "scada", "shunt", "transformer", "weather", "solver"]

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
    for hook, call in (("init", solver_init), ("precommit", solver_precommit), ("sync", solver_sync),
            ("commit", solver_commit), ("term", solver_term)):
        module.set_solver(hook, call)
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

_BY_NAME = {cls.NAME: cls for cls in CLASSES}

def _behavior(model:Any, name:str) -> Any:
    """Behavior of an object: that of its class, or of the nearest class it
    inherits from that the module defines"""
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name in _BY_NAME and oclass.module == MODULE:
            return _BY_NAME[oclass.name]
        oclass = getattr(oclass, "parent", None)
    raise PypowerError(f"object '{name}' is not a pypower object")

def _call(event:str, name:str, t:int) -> Any:
    model = runner().model
    cls = _behavior(model, name)
    return getattr(cls, event)(model, name, t)

def init(name:str, t:int) -> bool|int:
    """`on_init` event handler

    Exceptions
    ----------
    - `PypowerError`: no simulation is running, or the object is not a
      pypower object
    """
    return _call("init", name, t)

def precommit(name:str, t:int) -> int:
    """`on_precommit` event handler (exceptions: see `init()`)"""
    return _call("precommit", name, t)

def presync(name:str, t:int) -> int:
    """`on_presync` event handler (exceptions: see `init()`)"""
    return _call("presync", name, t)

def sync(name:str, t:int) -> int:
    """`on_sync` event handler (exceptions: see `init()`)"""
    return _call("sync", name, t)

def postsync(name:str, t:int) -> int:
    """`on_postsync` event handler (exceptions: see `init()`)"""
    return _call("postsync", name, t)

def commit(name:str, t:int) -> int:
    """`on_commit` event handler (exceptions: see `init()`)"""
    return _call("commit", name, t)
