# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras modules

The `Module` class holds an Arras Energy (HiPAS GridLAB-D) module: its name
and version, the object classes it registers, and the solvers that keep the
simulation clock synchronized. It models the module list that
`arras-energy/gridlabd` implements in `source/module.cpp` and the way the
core combines the functions that each module exports: the event-mode hooks
in `source/module.cpp` and `GldExec::clock_update_modules()`
(`source/exec.cpp`), and the deltamode hooks in `source/deltamode.cpp`.

Users can register modules, register the classes that a module provides,
attach a solver to each synchronization hook, and run the core's
dispatchers, which call the solvers of every loaded module in load order and
combine their results as gridlabd does.

Syntax
------

    from arras.module import Module
    m = Module(name, [major], [minor], [**solvers])   # register a module
    m = Module.load(name)                             # GLM `module name;`
    m = Module.find(name)                             # look up a loaded module

Arguments
---------
- `name`: module name (fewer than 1024 characters, without whitespace, `.`,
  or `:`)
- `major`, `minor`: module version, 0 to 65535 (default 0)
- `**solvers`: solvers to attach, keyed on a name from `SOLVERS` (for
  example `sync=f`)

Description
-----------

Given a name, `Module(name)` returns a module that is expected to satisfy:

1. The module is added to the end of `Module.registry` with the next module
   id, as `module_load()` does. Registering a name that is already loaded
   raises `ModuleError`; `Module.load(name)` returns the loaded module
   instead, as `module_load()` does.
2. `register_class(name)` registers an `arras.oclass.Class` for the module,
   and `classes` lists every class in `Class.registry` whose `module` is the
   module's name, in registration order, including classes registered by
   other code (for example `arras.model.Model.load_classes()`).
3. `set_solver(hook, call)` attaches a Python callable to one of the hooks
   in `SOLVERS`, named by its `arras` name or by the symbol that a gridlabd
   module library exports (`on_sync`, `clock_update`, `deltaClockUpdate`,
   ...). A module has at most one solver per hook.
4. The dispatchers call the solvers of every loaded module, in load order,
   and combine the results as the core does:

   | Dispatcher | gridlabd function | Result |
   | ---------- | ----------------- | ------ |
   | `initall()` | `module_initall()` | `False` at the first `init` solver that returns false, else `True` |
   | `precommitall(t)` | `module_precommitall()` | earliest result by absolute time (soft times are negative), `TS_NEVER` when none |
   | `presyncall(t)` | `module_presyncall()` | same as `precommitall()` |
   | `syncall(t)` | `module_syncall()` | same as `precommitall()` |
   | `postsyncall(t)` | `module_postsyncall()` | same as `precommitall()` |
   | `commitall(t)` | `module_commitall()` | `True` when every `commit` solver returns true; all are called |
   | `termall()` | `module_termall()` | `None`; every `term` solver is called |
   | `clockupdateall(t)` | `GldExec::clock_update_modules()` | `t` lowered by `clockupdate` solvers, repeated until no solver lowers it |
   | `deltadesiredall(flags, allowed)` | `delta_modedesired()` | smallest step in ns, `DT_INFINITY` when no module wants deltamode, `DT_INVALID` on error |
   | `preupdateall(clock, deltaclock, timestep)` | `delta_preupdate()` | smallest of `timestep` and the steps returned, `0` on error |
   | `interupdateall(clock, deltaclock, timestep, iteration)` | `delta_interupdate()` | `SM_DELTA_ITER` over `SM_DELTA` over `SM_EVENT`; `SM_ERROR` at the first error |
   | `deltaclockupdateall(curr_clock, timestep, mode)` | `delta_clockupdate()` | next simulation mode, `SM_ERROR` on error |
   | `postupdateall(clock, deltaclock)` | `delta_postupdate()` | `False` at the first `postupdate` solver that returns false, else `True` |

5. The deltamode dispatchers call only the modules that have a
   `deltamode_desired` solver, as `delta_init()` selects them.

Solvers
-------

| Hook | gridlabd symbol | Called as | Returns |
| ---- | --------------- | --------- | ------- |
| `init` | `on_init` | `init()` | `bool`: false stops the run |
| `precommit` | `on_precommit` | `precommit(t)` | next time (`TS_NEVER`, a time, a negative soft time, or `TS_INVALID`) |
| `presync` | `on_presync` | `presync(t)` | next time, before the top-down object pass |
| `sync` | `on_sync` | `sync(t)` | next time, after the bottom-up object pass |
| `postsync` | `on_postsync` | `postsync(t)` | next time, before the second top-down object pass |
| `commit` | `on_commit` | `commit(t)` | `bool`: false fails the commit |
| `term` | `on_term`, `term` | `term()` | nothing |
| `clockupdate` | `clock_update` | `clockupdate(t)` | proposed time; a time before `t` lowers the next clock time |
| `deltamode_desired` | `deltamode_desired` | `deltamode_desired(flags)` | step in ns until deltamode is needed, `DT_INFINITY`, or `DT_INVALID` |
| `preupdate` | `preupdate` | `preupdate(clock, deltaclock)` | step in ns; `0` or `DT_INVALID` fails |
| `interupdate` | `interupdate` | `interupdate(clock, deltaclock, timestep, iteration)` | `SM_EVENT`, `SM_DELTA`, `SM_DELTA_ITER`, or `SM_ERROR` |
| `deltaclockupdate` | `deltaClockUpdate` | `deltaclockupdate(next_time, timestep, mode)` | `SM_EVENT`, `SM_DELTA`, `SM_DELTA_ITER`, or `SM_ERROR` |
| `postupdate` | `postupdate` | `postupdate(clock, deltaclock)` | `bool`: false fails the update |

Times are gridlabd `TIMESTAMP` values: seconds since 1970-01-01 00:00:00
UTC as `int`. `clock` is the event clock (`global_clock`), `deltaclock` the
nanoseconds elapsed in deltamode (`global_deltaclock`), and `curr_clock` and
`next_time` are seconds as `float` (`global_delta_curr_clock`).

Examples
--------

    >>> from arras.oclass import Class
    >>> from arras.module import Module, TS_NEVER
    >>> Class.reset(); Module.reset()
    >>> def tape_sync(t):
    ...     return t + 3600              # next sample in one hour
    >>> def network_sync(t):
    ...     return -(t + 60)             # soft event: re-solve within a minute
    >>> tape = Module("tape", 4, 3, sync=tape_sync)
    >>> recorder = tape.register_class("recorder", passconfig="BOTTOMUP")
    >>> powerflow = Module.load("powerflow")
    >>> powerflow.set_solver("on_sync", network_sync)
    >>> node = powerflow.register_class("node", passconfig="PRETOPDOWN|BOTTOMUP|POSTTOPDOWN")
    >>> [oclass.name for oclass in powerflow.classes]
    ['node']
    >>> Module.syncall(946684800)
    -946684860
    >>> Module.presyncall(946684800) == TS_NEVER
    True
    >>> powerflow.set_solver("clock_update", lambda t: min(t, 946684900))
    >>> Module.clockupdateall(946688400)
    946684900
    >>> Module.load("tape") is tape
    True
    >>> Module("tape")
    Traceback (most recent call last):
    ...
    arras.module.ModuleError: module 'tape' is already loaded

Caveats
-------

- `Module` is an independent Python model of gridlabd's modules. It does
  not load module libraries and does not read from or write to a running
  `gridlabd` process. Solvers are Python callables that the user attaches;
  a module's classes are registered by the user or by `arras.model`.
- The registry is shared by all `Module` objects in the Python process, as
  gridlabd's module list is shared by a run. `Module.reset()` empties it; it
  does not remove the modules' classes from `Class.registry` (use
  `Class.reset()`).
- Solvers do not receive the `MODULE*` pointer that gridlabd passes to the
  deltamode functions. Use a closure or a bound method to reach module data.
- gridlabd calls a module's `on_term` and then its `term`; `arras` has one
  `term` hook, and both symbol names attach to it.
- The dispatchers implement how the core combines module results; they do
  not run the simulation. The main loop that advances the clock, runs the
  object synchronization passes, and applies `deltamode_allowed`,
  `deltamode_timestep`, and `global_delta_curr_clock` is not modeled, so
  those values are arguments.
- `clockupdateall()` repeats until no solver lowers the time, as the core
  does; a solver that always returns an earlier time never ends the loop.
- Module globals, `import_file`, `export_file`, `check`, `cmdargs`,
  `kmldump`, `subload`, `test`, and streams are not modeled. Module globals
  are kept in `arras.globals.Globals` as `MODULE::NAME` by `arras.model`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A module that has a `deltamode_desired` solver but no `preupdate`,
   `interupdate`, or `postupdate` solver makes the deltamode dispatcher that
   needs it raise `ModuleError`. The core calls the missing function
   through a null pointer.
2. Module names are checked: an empty name, a name of 1024 characters or
   more, and a name with whitespace, `.`, or `:` raise `ModuleError`. The
   core uses the name as a library file name and does not check it.
3. A solver result of the wrong type (a time that is not an `int`, or a
   `bool` where a time is expected) raises `ModuleError`.

References
----------

- `arras-energy/gridlabd`: `source/module.h` (`struct s_module_list`),
  `source/module.cpp` (`module_load()`, `module_find()`,
  `module_initall()`, `module_precommitall()`, `module_presyncall()`,
  `module_syncall()`, `module_postsyncall()`, `module_commitall()`,
  `module_termall()`), `source/exec.cpp` (`GldExec::clock_update_modules()`,
  the module calls in the sync passes), `source/deltamode.cpp`
  (`delta_init()`, `delta_modedesired()`, `delta_preupdate()`,
  `delta_interupdate()`, `delta_clockupdate()`, `delta_postupdate()`),
  `source/timestamp.h`, `source/timestamp.cpp` (`absolute_timestamp()`)
- [Module directive](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/GLM/Directive/Module.md)
  (`docs/GLM/Directive/Module.md`)
"""

import math
import re
import logging
from typing import Callable

from arras.exceptions import ArrasException
from arras.oclass import Class

_logger = logging.getLogger(__file__)

MAXNAMELEN = 1024
"""Module names must be shorter than this (gridlabd `char name[1024]`)"""

TS_ZERO = 0
"""Time zero (gridlabd `TS_ZERO`)"""

TS_MAX = 32482080000
"""Latest valid time, about 3000 CE (gridlabd `TS_MAX`)"""

TS_INVALID = -1
"""Invalid time; a solver returns it to report a failure (gridlabd `TS_INVALID`)"""

TS_NEVER = (1 << 63) - 1
"""No next time (gridlabd `TS_NEVER`)"""

DT_SECOND = 1000000000
"""Nanoseconds per second (gridlabd `DT_SECOND`)"""

DT_INFINITY = 0xfffffffe
"""Deltamode not needed (gridlabd `DT_INFINITY`)"""

DT_INVALID = 0xffffffff
"""Invalid deltamode step (gridlabd `DT_INVALID`)"""

DT_DEFAULT = 10000000
"""Default deltamode step in ns, 10 ms (gridlabd `global_deltamode_timestep`)"""

SM_INIT = 0
"""Simulation mode: initialization (reserved)"""

SM_EVENT = 1
"""Simulation mode: event-driven (leave deltamode)"""

SM_DELTA = 2
"""Simulation mode: deltamode"""

SM_DELTA_ITER = 3
"""Simulation mode: deltamode, iterate on the current step"""

SM_ERROR = 255
"""Simulation mode: error"""

SIMULATIONMODE = {
    "INIT": SM_INIT,
    "EVENT": SM_EVENT,
    "DELTA": SM_DELTA,
    "DELTA_ITER": SM_DELTA_ITER,
    "ERROR": SM_ERROR,
}
"""Simulation modes (gridlabd `SIMULATIONMODE`)"""

SOLVERS = {
    "init": ("on_init",),
    "precommit": ("on_precommit",),
    "presync": ("on_presync",),
    "sync": ("on_sync",),
    "postsync": ("on_postsync",),
    "commit": ("on_commit",),
    "term": ("on_term", "term"),
    "clockupdate": ("clock_update",),
    "deltamode_desired": ("deltamode_desired",),
    "preupdate": ("preupdate",),
    "interupdate": ("interupdate",),
    "deltaclockupdate": ("deltaClockUpdate",),
    "postupdate": ("postupdate",),
}
"""Solver hooks as `name: (gridlabd symbols)`, in the order of gridlabd's
`struct s_module_list` call sequence"""

_ALIASES = {symbol: name for name, symbols in SOLVERS.items() for symbol in symbols}

class ModuleError(ArrasException):
    """Module error"""

def _absolute(t:int) -> int:
    """Absolute time of a soft time (gridlabd `absolute_timestamp()`)"""
    return -t if -TS_MAX <= t < 0 else t

class Module: # pylint: disable=too-many-public-methods
    """Arras module

    See the module documentation for the description and examples.

    Attributes
    ----------
    - `id`: module id (load order, from 0)
    - `name`: module name
    - `major`, `minor`: module version
    - `solvers`: dict of solver hook name to callable (see `SOLVERS`)
    """

    registry: list["Module"] = []
    """Loaded modules, in load order"""

    _count: int = 0

    def __init__(self, name:str, major:int=0, minor:int=0, **solvers:Callable):
        """Register a module (gridlabd `module_load()`)

        Arguments
        ---------
        - `name`: module name
        - `major`, `minor`: module version, 0 to 65535
        - `**solvers`: solvers keyed on a hook name or gridlabd symbol (see
          `SOLVERS`)

        Exceptions
        ----------
        - `ModuleError`: the name is not valid or is already loaded, the
          version is not valid, or a solver is not valid
        """
        if not isinstance(name,str) or not name or re.search(r"[\s.:]",name):
            raise ModuleError(f"module name {name!r} is not valid")
        if len(name) >= MAXNAMELEN:
            raise ModuleError(f"module name '{name}' is too long")
        if Module.find(name) is not None:
            raise ModuleError(f"module '{name}' is already loaded")
        for value in (major,minor):
            if not isinstance(value,int) or isinstance(value,bool) or not 0 <= value <= 0xffff:
                raise ModuleError(f"module '{name}' version {value!r} is not valid")
        self.id = Module._count
        """Module id"""
        self.name = name
        """Module name"""
        self.major = major
        """Major version"""
        self.minor = minor
        """Minor version"""
        self.solvers: dict[str,Callable] = {}
        """Solvers keyed on hook name"""
        for hook, call in solvers.items():
            self._check_solver(hook, call)
        for hook, call in solvers.items():
            self.solvers[_ALIASES.get(hook,hook)] = call
        Module._count += 1
        Module.registry.append(self)
        _logger.debug("module %s loaded ok", name)

    def __repr__(self) -> str:
        return f"<Module {self.name}>"

    #
    # Registry
    #
    @classmethod
    def reset(cls) -> None:
        """Remove all loaded modules and restart module ids at 0"""
        cls.registry.clear()
        cls._count = 0

    @classmethod
    def find(cls, name:str) -> "Module|None":
        """Find a loaded module (gridlabd `module_find()`)

        Returns
        -------
        - `Module`: the module, or `None` if no module of that name is loaded
        """
        for module in cls.registry:
            if module.name == name:
                return module
        return None

    @classmethod
    def load(cls, name:str, major:int=0, minor:int=0, **solvers:Callable) -> "Module":
        """Load a module, as GLM `module name;` does (gridlabd `module_load()`)

        Returns
        -------
        - `Module`: the module already loaded with that name (the other
          arguments are ignored, as gridlabd ignores them), else a new module

        Exceptions
        ----------
        - `ModuleError`: see `Module()`
        """
        module = cls.find(name)
        if module is not None:
            _logger.debug("module '%s' already loaded", name)
            return module
        return cls(name, major, minor, **solvers)

    #
    # Classes
    #
    @property
    def classes(self) -> list[Class]:
        """Classes registered for the module, in registration order"""
        return [oclass for oclass in Class.registry if oclass.module == self.name]

    def register_class(self, name:str, passconfig:int|str|None=0) -> Class:
        """Register a class for the module (gridlabd `class_register()`)

        Arguments
        ---------
        - `name`: class name
        - `passconfig`: `arras.oclass.PASSCONFIG` bits or a `|`-separated
          string of its keys

        Returns
        -------
        - `Class`: the new class

        Exceptions
        ----------
        - `arras.oclass.ClassError`: see `arras.oclass.Class()`
        """
        return Class(name, module=self.name, passconfig=passconfig)

    #
    # Solvers
    #
    def _check_solver(self, hook:str, call:Callable) -> str:
        name = _ALIASES.get(hook, hook)
        if name not in SOLVERS:
            raise ModuleError(f"module '{self.name}' solver hook '{hook}' is not valid")
        if not callable(call):
            raise ModuleError(f"module '{self.name}' solver '{hook}' is not callable")
        return name

    def set_solver(self, hook:str, call:Callable|None) -> None:
        """Attach a solver to a hook, replacing any solver it has

        Arguments
        ---------
        - `hook`: hook name or gridlabd symbol (see `SOLVERS`)
        - `call`: solver, or `None` to remove the hook's solver

        Exceptions
        ----------
        - `ModuleError`: the hook is not valid or `call` is not callable
        """
        if call is None:
            name = _ALIASES.get(hook, hook)
            if name not in SOLVERS:
                raise ModuleError(f"module '{self.name}' solver hook '{hook}' is not valid")
            self.solvers.pop(name, None)
            return
        self.solvers[self._check_solver(hook, call)] = call

    def get_solver(self, hook:str) -> Callable|None:
        """Get the solver attached to a hook (name or gridlabd symbol), or
        `None`"""
        return self.solvers.get(_ALIASES.get(hook, hook))

    def has_solver(self, hook:str) -> bool:
        """Check whether a solver is attached to a hook"""
        return self.get_solver(hook) is not None

    def _time(self, hook:str, *args) -> int:
        """Call a solver that returns a time and check the result"""
        result = self.solvers[hook](*args)
        if not isinstance(result,int) or isinstance(result,bool):
            raise ModuleError(f"module '{self.name}' solver '{hook}' returned {result!r}, not a time")
        return result

    #
    # Event-mode dispatchers
    #
    @classmethod
    def _solving(cls, hook:str) -> list["Module"]:
        return [module for module in cls.registry if hook in module.solvers]

    @classmethod
    def initall(cls) -> bool:
        """Call every `init` solver (gridlabd `module_initall()`)

        Returns
        -------
        - `bool`: `False` at the first solver that returns false (later
          modules are not called), else `True`
        """
        for module in cls._solving("init"):
            if not module.solvers["init"]():
                _logger.error("module %s on_init() failed", module.name)
                return False
        return True

    @classmethod
    def _earliest(cls, hook:str, t:int) -> int:
        """Earliest solver result by absolute time (gridlabd
        `module_presyncall()` and its siblings)"""
        result = TS_NEVER
        for module in cls._solving(hook):
            value = module._time(hook, t) # pylint: disable=protected-access
            _logger.debug("%s.on_%s(t=%d) -> %d", module.name, hook, t, value)
            if _absolute(value) < _absolute(result):
                result = value
        return result

    @classmethod
    def precommitall(cls, t:int) -> int:
        """Call every `precommit` solver (gridlabd `module_precommitall()`)

        Returns
        -------
        - `int`: the result earliest in absolute time (a soft time stays
          negative; `TS_INVALID` wins), or `TS_NEVER` when there is none
        """
        return cls._earliest("precommit", t)

    @classmethod
    def presyncall(cls, t:int) -> int:
        """Call every `presync` solver (gridlabd `module_presyncall()`);
        results are combined as by `precommitall()`"""
        return cls._earliest("presync", t)

    @classmethod
    def syncall(cls, t:int) -> int:
        """Call every `sync` solver (gridlabd `module_syncall()`); results
        are combined as by `precommitall()`"""
        return cls._earliest("sync", t)

    @classmethod
    def postsyncall(cls, t:int) -> int:
        """Call every `postsync` solver (gridlabd `module_postsyncall()`);
        results are combined as by `precommitall()`"""
        return cls._earliest("postsync", t)

    @classmethod
    def commitall(cls, t:int) -> bool:
        """Call every `commit` solver (gridlabd `module_commitall()`)

        Returns
        -------
        - `bool`: `True` when every solver returns true; every solver is
          called even after one returns false
        """
        result = True
        for module in cls._solving("commit"):
            ok = bool(module.solvers["commit"](t))
            _logger.debug("%s.on_commit(t=%d) -> ok = %s", module.name, t, ok)
            result &= ok
        return result

    @classmethod
    def termall(cls) -> None:
        """Call every `term` solver (gridlabd `module_termall()`)"""
        for module in cls._solving("term"):
            module.solvers["term"]()

    @classmethod
    def clockupdateall(cls, t:int) -> int:
        """Lower the next clock time with the `clockupdate` solvers
        (gridlabd `GldExec::clock_update_modules()`)

        Every solver is offered the time; when one returns an earlier time,
        that time is kept and every solver is offered it again, until no
        solver lowers it.

        Returns
        -------
        - `int`: the next clock time
        """
        done = False
        while not done:
            done = True
            for module in cls._solving("clockupdate"):
                value = module._time("clockupdate", t) # pylint: disable=protected-access
                if value < t:
                    t = value
                    done = False
        return t

    #
    # Deltamode dispatchers
    #
    @classmethod
    def _delta(cls, hook:str|None=None) -> list["Module"]:
        """Modules that take part in deltamode (gridlabd `delta_init()`),
        checked for a solver on `hook`"""
        modules = cls._solving("deltamode_desired")
        if hook is not None:
            for module in modules:
                if hook not in module.solvers:
                    raise ModuleError(f"module '{module.name}' has a deltamode_desired solver but no {hook} solver")
        return modules

    @classmethod
    def deltadesiredall(cls, flags:int=0, allowed:bool=False) -> int:
        """Ask the deltamode modules when deltamode is needed (gridlabd
        `delta_modedesired()`)

        Arguments
        ---------
        - `flags`: deltamode flags passed to each solver
        - `allowed`: the `deltamode_allowed` global (gridlabd default `FALSE`)

        Returns
        -------
        - `int`: the smallest step in ns; `DT_INFINITY` when no module wants
          deltamode; `DT_INVALID` when a solver returns it, or when a module
          wants deltamode and `allowed` is false
        """
        desired = DT_INFINITY
        for module in cls._delta():
            dt = module.solvers["deltamode_desired"](flags)
            if dt == DT_INVALID:
                _logger.error("module '%s' return invalid/infinite dt for delta mode inquiry", module.name)
                return DT_INVALID
            if 0 <= dt < desired:
                desired = dt
        if desired != DT_INFINITY and not allowed:
            _logger.error("request to enter delta-mode cannot be satisfied when deltamode_allowed is FALSE")
            return DT_INVALID
        return desired

    @classmethod
    def preupdateall(cls, clock:int, deltaclock:int, timestep:int=DT_DEFAULT) -> int:
        """Call every deltamode `preupdate` solver (gridlabd `delta_preupdate()`)

        Arguments
        ---------
        - `clock`: event clock (`global_clock`)
        - `deltaclock`: ns elapsed in deltamode (`global_deltaclock`)
        - `timestep`: deltamode step in ns (`global_deltamode_timestep`)

        Returns
        -------
        - `int`: the smallest of `timestep` and the steps returned, or `0`
          when a solver returns `0` or `DT_INVALID` (later modules are not
          called)

        Exceptions
        ----------
        - `ModuleError`: a deltamode module has no `preupdate` solver
        """
        for module in cls._delta("preupdate"):
            dt = module.solvers["preupdate"](clock, deltaclock)
            if dt in (0, DT_INVALID):
                _logger.error("delta_preupdate(): module %s failed", module.name)
                return 0
            timestep = min(timestep, dt)
        return timestep

    @classmethod
    def interupdateall(cls, clock:int, deltaclock:int, timestep:int, iteration:int) -> int:
        """Call every deltamode `interupdate` solver (gridlabd
        `delta_interupdate()`)

        Returns
        -------
        - `int`: `SM_ERROR` at the first solver that returns it (later
          modules are not called); else `SM_DELTA_ITER` if any solver
          returns it; else `SM_DELTA` if any solver returns it; else
          `SM_EVENT`

        Exceptions
        ----------
        - `ModuleError`: a deltamode module has no `interupdate` solver
        """
        mode = SM_EVENT
        for module in cls._delta("interupdate"):
            result = module.solvers["interupdate"](clock, deltaclock, timestep, iteration)
            if result == SM_DELTA_ITER:
                mode = SM_DELTA_ITER
            elif result == SM_DELTA:
                if mode != SM_DELTA_ITER:
                    mode = SM_DELTA
            elif result == SM_ERROR:
                return SM_ERROR
        return mode

    @classmethod
    def deltaclockupdateall(cls, curr_clock:float, timestep:int, mode:int) -> int:
        """Tell the deltamode modules that the current step is finished
        (gridlabd `delta_clockupdate()`)

        When `mode` is `SM_DELTA`, each `deltaclockupdate` solver is called
        with the next time `curr_clock + timestep/DT_SECOND`. When `mode` is
        `SM_EVENT`, deltamode is ending: each solver is called with the next
        whole second and the step to it in ns. Modules without the solver
        are skipped.

        Arguments
        ---------
        - `curr_clock`: current deltamode time in seconds
          (`global_delta_curr_clock`)
        - `timestep`: deltamode step in ns
        - `mode`: result of `interupdateall()`

        Returns
        -------
        - `int`: `SM_DELTA` or `SM_EVENT` (unchanged `SM_DELTA` for other
          modes); `SM_ERROR` when a solver returns it, when a solver asks to
          stay in deltamode while it ends, or when a solver asks to iterate
          while it ends; `SM_EVENT` when a solver asks to iterate in
          deltamode
        """
        result = SM_DELTA
        if mode == SM_DELTA:
            next_time = curr_clock + timestep / DT_SECOND
            for module in cls._delta():
                if "deltaclockupdate" in module.solvers:
                    value = module.solvers["deltaclockupdate"](next_time, timestep, mode)
                    if value == SM_DELTA_ITER:
                        _logger.error("delta_clockupdate(): It is too late to reiterate on the current time step.")
                        return SM_EVENT
                    if value == SM_ERROR:
                        return SM_ERROR
                    # SM_DELTA, SM_EVENT, and other values leave SM_DELTA
        elif mode == SM_EVENT:
            next_time = math.ceil(curr_clock)
            exit_step = int((next_time - curr_clock) * DT_SECOND)
            for module in cls._delta():
                if "deltaclockupdate" in module.solvers:
                    value = module.solvers["deltaclockupdate"](float(next_time), exit_step, mode)
                    if value == SM_DELTA_ITER:
                        _logger.error("delta_clockupdate(): It is too late to reiterate on the current time step.")
                        return SM_ERROR
                    if value == SM_DELTA:
                        _logger.error("delta_clockupdate(); Every object wishes to exit delta mode. It is too late to stay in it.")
                        return SM_ERROR
                    if value == SM_ERROR:
                        return SM_ERROR
                    if value == SM_EVENT:
                        result = SM_EVENT
        return result

    @classmethod
    def postupdateall(cls, clock:int, deltaclock:int) -> bool:
        """Call every deltamode `postupdate` solver (gridlabd
        `delta_postupdate()`)

        Returns
        -------
        - `bool`: `False` at the first solver that returns false (later
          modules are not called), else `True`

        Exceptions
        ----------
        - `ModuleError`: a deltamode module has no `postupdate` solver
        """
        for module in cls._delta("postupdate"):
            if not module.solvers["postupdate"](clock, deltaclock):
                return False
        return True
