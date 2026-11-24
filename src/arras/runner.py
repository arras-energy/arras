# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras simulation runner

The `Runner` class runs an Arras Energy (HiPAS GridLAB-D) simulation in
Python. It reads the model files named on the command line into an
`arras.model.Model` and solves the quasi-steady time series as the main
loop of the gridlabd core does (`GldExec::exec_start()` in
`source/exec.cpp`): it initializes the objects, advances the clock from
`starttime` toward `stoptime` from one event to the next, runs the object
synchronization passes at each time until no object asks for another
iteration, commits each time step, and finalizes the objects. The
`gridlabd` executable is not run.

Object behavior comes from the event handlers that gridlabd objects and
classes accept (`on_init`, `on_precommit`, `on_presync`, `on_sync`,
`on_postsync`, `on_commit`, `on_finalize`).

Syntax
------

    from arras.runner import Runner
    r = Runner(*args, [model=], [background=], [progress=])
    r.wait([timeout])     # wait for a background run; returns the exit code
    r.stop()              # stop the run at the next time step
    Runner.current()      # runner of the calling thread (for event handlers)

Arguments
---------
- `*args`: command line arguments (see Command line)
- `model`: `arras.model.Model` that files are read into and that is run
  (default is a new `Model()`); with no file arguments, the model given is
  run as it is
- `background`: run in a background thread and return at once (default
  `False`)
- `progress`: function called after each time step and once at the end
  (see Progress callback)

Command line
------------

Arguments are processed in order, as gridlabd processes them, so a global
defined before a file name is set before the file is read.

| Argument | Effect |
| -------- | ------ |
| `FILE.glm`, `FILE.json` | read the file into the model (`Model.read()`) |
| `-D NAME=VALUE`, `--define NAME=VALUE`, `--define=NAME=VALUE` | set a global variable |
| `-o FILE`, `--output FILE`, `--output=FILE` | write the model to FILE (`.glm` or `.json`) when the run ends |
| `-c`, `--check` | check the model (`Model.check()`) before the run; problems fail the load |
| `-C`, `--compile` | load (and check) only; do not initialize or run |
| `-I`, `--initialize` | load and initialize only; do not run the time series |
| `-q`, `--quiet` | toggle the `quiet` global: only errors are output |
| `-v`, `--verbose` | toggle the `verbose` global: output verbose messages |
| `-w`, `--warn` | toggle the `warn` global: output warnings |
| `--debug` | toggle the `debug` global: output debug messages |

Any other argument that starts with `-` fails with exit code
`arras.exitcodes.ARGERR`.

Description
-----------

Given command line arguments, `Runner(*args)` runs a simulation that is
expected to satisfy:

1. Exit codes are those of `arras.exitcodes`: `SUCCESS`, `ARGERR` for a
   command line error or a model with no objects and no file, `LDERR` for a
   file that cannot be read or a failed check, `INIERR` for an
   initialization failure, `RUNERR` for a failure or stop during the run,
   and `IOERR` for an output file that cannot be written.
2. Every object starts with `clock` set to `starttime`. Objects are
   initialized in creation order. An `on_init` handler that returns `False`
   fails the initialization; one that returns `2` is deferred and called
   again after the others, up to `init_max_defer` rounds, as
   `init_by_deferral()` does.
3. The clock starts at `starttime`. At each time, `on_precommit` handlers
   run once, then the presync handlers top-down (parents before children),
   the sync handlers bottom-up (children before parents), and the postsync
   handlers top-down. An object's rank is its `rank` header value, raised
   so that each parent ranks above its children, as `object_set_parent()`
   does; objects of equal rank run in creation order.
4. A sync handler returns the time of the object's next event: a positive
   time is a hard event, a negative time `-t` is a soft event at `t`, and
   `None` or `TS_NEVER` means no event. The next time is the earliest event,
   rounded up to a multiple of `minimum_timestep` for hard events. A time
   before the clock, `TS_INVALID`, or 0 stops the run.
5. When the earliest event is the current time, the passes run again
   without advancing the clock, up to `iteration_limit` times in a row;
   reaching the limit stops the run.
6. Otherwise the time step is committed: `on_commit` handlers run with the
   current time, every object's `clock` is set to it, and the clock
   advances to the next time. A commit result at or before the current time
   stops the run; an earlier result than the next time becomes the next
   time.
7. The run ends when the next time is after `stoptime`, or when it is
   `TS_NEVER`, or when only soft events remain and `stoptime` is `NEVER`.
   `stoptime` 0 means `NEVER`.
8. Objects are synchronized only while in service: before `in_svc` an
   object's next event is `in_svc`; after `out_svc` its handlers are not
   called.
9. `on_finalize` handlers run when the time series ends, also after a
   failure or a stop during the time series.
10. The `clock` and `progress` globals follow the run (`progress` is the
    fraction of the time from `starttime` to `stoptime` that is done).

Event handlers
--------------

A handler is an object's `on_<event>` property, or else its class's
`on_<event>` handler (`arras.oclass.Class.set_event()`):

- `python:MODULE.FUNCTION` calls `FUNCTION(name, t)` in Python module
  `MODULE`, where `name` is the object name and `t` the clock. Modules are
  imported by name, then from the working folder. Time handlers
  (`precommit`, the three sync passes, `commit`) return a timestamp or
  `None`; `init` returns `True`, `None`, `False`, or `2`; the result of
  `finalize` is not used. An exception or a value of the wrong type is a
  handler failure.
- Any other text is a shell command, run with the environment variables
  `CLOCK` (the clock in seconds), `HOSTNAME`, `PORT`, and `OBJECT` set. Its
  standard output and error lines are added to `stdout` and `stderr`. A
  nonzero exit status is a handler failure.

Handlers reach the model and the run through `Runner.current()`, e.g.
`Runner.current().model.get_property(name, "x")`, and add output lines with
`Runner.current().output(...)` and `Runner.current().error(...)`.

Progress callback
-----------------

The callback takes any of these optional arguments:

- `timestamp`: the clock (`int`, seconds since 1970-01-01 00:00:00 UTC),
  or `None` before the time series starts
- `percent`: percent of the time from `starttime` to `stoptime` that is
  done (`float`, 0 to 100), `100.0` when the run ends successfully, or
  `None` while `stoptime` is `NEVER`
- `stdout`: the output lines added since the previous call (`list[str]`)
- `stderr`: the error, warning, and message lines added since the previous
  call (`list[str]`)

It is called with only the arguments that its signature names (all of them
when it takes `**kwargs`), after each committed time step and once when the
run ends, including a run that ends before its time series starts. A
callback that returns `False` stops the run, as `stop()` does. A callback
that raises stops the run with `RUNERR`.

Examples
--------

The event handler in this example is made in memory; handlers are normally
functions in an importable module.

    >>> import sys, types
    >>> from arras.oclass import Class
    >>> from arras.model import Model
    >>> from arras.runner import Runner
    >>> Class.reset()
    >>> def sync(name, t):
    ...     runner = Runner.current()
    ...     runner.output(name, runner.model.globals.timestamp_to_string(t))
    ...     return t + 3600
    >>> sys.modules["example"] = types.SimpleNamespace(sync=sync)
    >>> m = Model()
    >>> m.read_glm('''
    ... clock {
    ...     starttime "2020-01-01 00:00:00 UTC";
    ...     stoptime "2020-01-01 02:00:00 UTC";
    ... }
    ... class timer { double x; }
    ... object timer { name "t1"; on_sync "python:example.sync"; }
    ... ''')
    >>> r = Runner(model=m)
    >>> r.returncode
    0
    >>> print(*r.stdout, sep="\\n")
    t1 2020-01-01 00:00:00 UTC
    t1 2020-01-01 01:00:00 UTC
    t1 2020-01-01 02:00:00 UTC
    >>> m.get_property("t1", "clock")
    '2020-01-01 02:00:00 UTC'

The same model run in the background with a progress callback, which is
called after each of the three time steps and once more at the end:

    >>> steps = []
    >>> def progress(timestamp, percent):
    ...     steps.append((timestamp, percent))
    >>> r = Runner(model=m, background=True, progress=progress)
    >>> r.wait()
    0
    >>> steps
    [(1577836800, 0.0), (1577840400, 50.0), (1577844000, 100.0), (1577844000, 100.0)]
    >>> del sys.modules["example"]
    >>> Class.reset()

Caveats
-------

- Only event handlers give objects behavior. The classes that gridlabd
  modules implement in C++ (`powerflow`, `residential`, ...) have no
  synchronization code in `arras`, so their objects take part in a run only
  through handlers. Class `PASSCONFIG` bits do not add objects to passes.
- A background run is a thread of the calling Python process, not a
  separate process. Handlers and the progress callback run in that thread;
  do not change the model from another thread while it runs.
- Python handlers that `print` write to `sys.stdout` of the process; use
  `Runner.current().output()` to add lines to `stdout`.
- `-W`, `-M`, and gridlabd's other options are not supported, nor are
  realtime mode, deltamode, multithreading, schedules, transforms, filters,
  `#exec` and script events, module `on_*` hooks, and object heartbeats.
- `${PYTHON ...}`, `${SHELL ...}`, `python:` handlers, and shell handlers
  run code. Do not run untrusted models.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Objects of the same rank are synchronized in creation order; gridlabd
   shuffles each rank (`index_shuffle()`).
2. Messages are written as `ERROR [TIME]: text`, `WARNING [TIME]: text`,
   `VERBOSE [TIME]: text`, and `DEBUG [TIME]: text`, which differs from
   gridlabd's layout, and gridlabd's progress line is not written.
3. An `on_init` Python handler fails by returning `False`; gridlabd's
   `object_init()` tests the converted value `1` as failure.
4. A Python time handler that returns `None` means no event, and one that
   returns a `bool` or a non-integer fails.
5. The model is written with `-o` whenever the model was loaded, also
   after a failed run.

References
----------

- `arras-energy/gridlabd`: `source/exec.cpp` (`GldExec::exec_start()`,
  `ss_do_object_sync()`, `sync_set()`, `sync_isrunning()`,
  `init_by_deferral()`, `commit_all()`), `source/object.cpp`
  (`object_sync()`, `object_event()`, `object_init()`,
  `object_precommit()`, `object_commit()`, `object_finalize()`,
  `set_rank()`)
- [Object events](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/GLM/Object/Events.md)
  (`docs/GLM/Object/Events.md`), `docs/Module/Python.md`
"""

import os
import sys
import socket
import inspect
import logging
import importlib
import threading
import subprocess
from typing import Any, Callable

from arras.exceptions import ArrasException
import arras.exitcodes as exitcodes

_logger = logging.getLogger(__file__)

TS_ZERO = 0
"""Timestamp printed as `INIT` (same as `arras.globals.TS_ZERO`)"""

TS_NEVER = (1 << 63) - 1
"""Timestamp printed as `NEVER` (same as `arras.globals.TS_NEVER`)"""

TS_INVALID = -1
"""Timestamp that reports a failure (gridlabd `TS_INVALID`)"""

PASSES = (("presync", True), ("sync", False), ("postsync", True))
"""Synchronization passes in order, each with `True` for top-down
(gridlabd `GldExec::passtype[]`: `PC_PRETOPDOWN`, `PC_BOTTOMUP`,
`PC_POSTTOPDOWN`)"""

PROGRESS_ARGUMENTS = ("timestamp", "percent", "stdout", "stderr")
"""Arguments that the progress callback may take"""

INIT_DEFER = 2
"""`on_init` result that defers an object's initialization"""

class RunnerError(ArrasException):
    """Runner error"""

class _Failure(Exception):
    """@private Simulation failure with its exit code"""

    def __init__(self, code:int, message:str|None=None):
        super().__init__(message)
        self.code = code
        self.message = message

class Runner: # pylint: disable=too-many-instance-attributes
    """Arras simulation runner

    See the module documentation for the description and examples.

    Attributes
    ----------
    - `args`: command line arguments
    - `model`: the model run (`arras.model.Model`)
    - `returncode`: exit code (see `arras.exitcodes`), `None` while running
    - `stdout`: output lines (`list[str]`)
    - `stderr`: error, warning, and message lines (`list[str]`)
    - `clock`: clock of the run (`int`), `None` before the time series starts
    - `steps`: number of committed time steps
    - `stopped`: `True` when `stop()` or the progress callback stopped the run
    """

    GRIDLABD_PATH = "/usr/local/opt/gridlabd/current"
    """Path to the gridlabd install, used for the folder globals that
    `arras.globals` takes from `GLD_*` when they are not set"""

    _local = threading.local()

    def __init__(self, *args:str, model:Any=None, background:bool=False, progress:Callable|None=None):
        """Run a simulation

        Arguments
        ---------
        - `*args`: command line arguments
        - `model`: `arras.model.Model` to read files into and run (default
          is a new `Model()`)
        - `background`: run in a background thread and return at once
        - `progress`: progress callback

        Exceptions
        ----------
        - `RunnerError`: an argument is not a string, `model` is not a
          `Model`, or `progress` is not callable or has a required argument
          other than `timestamp`, `percent`, `stdout`, and `stderr`
        """
        from arras.model import Model # pylint: disable=import-outside-toplevel
        for arg in args:
            if not isinstance(arg, str):
                raise RunnerError(f"argument {arg!r} is not a string")
        if model is None:
            model = Model()
        elif not isinstance(model, Model):
            raise RunnerError(f"model {model!r} is not an arras.model.Model")
        self._progress = progress
        self._progress_args = self._callback_arguments(progress)
        self.args = list(args)
        """Command line arguments"""
        self.model = model
        """Model run"""
        self.returncode: int|None = None
        """Exit code (see `arras.exitcodes`), `None` while running"""
        self.stdout: list[str] = []
        """Output lines"""
        self.stderr: list[str] = []
        """Error, warning, and message lines"""
        self.clock: int|None = None
        """Clock of the run"""
        self.steps = 0
        """Number of committed time steps"""
        self.stopped = False
        """The run was stopped by `stop()` or the progress callback"""
        self._stop = threading.Event()
        self._sent = [0, 0]
        self._handlers: dict[str,Callable] = {}
        self._percent: float|None = None
        self._thread: threading.Thread|None = None
        self._done = threading.Event()
        if background:
            self._thread = threading.Thread(target=self._main, name="arras-runner", daemon=True)
            self._thread.start()
        else:
            self._main()

    def __repr__(self) -> str:
        return f"<Runner {' '.join(self.args)!r} returncode={self.returncode}>"

    @staticmethod
    def _callback_arguments(progress:Callable|None) -> tuple[str,...]:
        if progress is None:
            return ()
        if not callable(progress):
            raise RunnerError(f"progress {progress!r} is not callable")
        try:
            params = inspect.signature(progress).parameters
        except (TypeError, ValueError):
            return PROGRESS_ARGUMENTS
        names = []
        for name, param in params.items():
            if param.kind == param.VAR_KEYWORD:
                return PROGRESS_ARGUMENTS
            if param.kind == param.VAR_POSITIONAL:
                continue
            if name in PROGRESS_ARGUMENTS and param.kind != param.POSITIONAL_ONLY:
                names.append(name)
            elif param.default is param.empty:
                raise RunnerError(f"progress callback argument '{name}' is not one of {', '.join(PROGRESS_ARGUMENTS)}")
        return tuple(names)

    #
    # Control
    #
    @classmethod
    def current(cls) -> "Runner|None":
        """Runner whose simulation is running in the calling thread, or
        `None`"""
        return getattr(cls._local, "runner", None)

    @property
    def running(self) -> bool:
        """`True` while the simulation runs"""
        return not self._done.is_set()

    def wait(self, timeout:float|None=None) -> int|None:
        """Wait for the run to end

        Arguments
        ---------
        - `timeout`: seconds to wait (default is no limit)

        Returns
        -------
        - `int`: the exit code
        - `None`: the run did not end within `timeout`
        """
        self._done.wait(timeout)
        return self.returncode

    def stop(self) -> None:
        """Stop the run at the next time step (the run ends with
        `arras.exitcodes.RUNERR` after the objects are finalized)"""
        self._stop.set()

    #
    # Output
    #
    def _simtime(self) -> str:
        if self.clock is None:
            return "INIT"
        return self.model.globals.timestamp_to_string(self.clock)

    def output(self, *args:Any) -> None:
        """Add a line to `stdout` (arguments joined with spaces, as `print`
        joins them)"""
        self.stdout.append(" ".join(str(x) for x in args))

    def error(self, *args:Any) -> None:
        """Add an error line to `stderr`"""
        self.stderr.append(f"ERROR [{self._simtime()}]: " + " ".join(str(x) for x in args))

    def warning(self, *args:Any) -> None:
        """Add a warning line to `stderr` when the `warn` global is true and
        `quiet` is false"""
        if self._flag("warn") and not self._flag("quiet"):
            self.stderr.append(f"WARNING [{self._simtime()}]: " + " ".join(str(x) for x in args))

    def _verbose(self, *args:Any) -> None:
        if self._flag("verbose") and not self._flag("quiet"):
            self.stderr.append(f"VERBOSE [{self._simtime()}]: " + " ".join(str(x) for x in args))

    def _debug(self, *args:Any) -> None:
        if self._flag("debug") and not self._flag("quiet"):
            self.stderr.append(f"DEBUG [{self._simtime()}]: " + " ".join(str(x) for x in args))

    def _flag(self, name:str) -> bool:
        return bool(self.model.globals.getvalue(name))

    def _report(self, final:bool=False) -> None:
        """Call the progress callback with the lines added since the last call"""
        if self._progress is None:
            return
        out = self.stdout[self._sent[0]:]
        err = self.stderr[self._sent[1]:]
        self._sent = [self._sent[0]+len(out), self._sent[1]+len(err)]
        values = {
            "timestamp": self.clock,
            "percent": 100.0 if final and self.returncode == exitcodes.SUCCESS else self._percent,
            "stdout": out,
            "stderr": err,
        }
        try:
            result = self._progress(**{name: values[name] for name in self._progress_args})
        except Exception as err: # pylint: disable=broad-exception-caught
            if final:
                self.error(f"progress callback failed: {type(err).__name__}: {err}")
                self.returncode = exitcodes.RUNERR
                return
            raise _Failure(exitcodes.RUNERR, f"progress callback failed: {type(err).__name__}: {err}") from err
        if result is False and not final:
            self._stop.set()

    #
    # Run
    #
    def _main(self) -> None:
        previous = Runner.current()
        Runner._local.runner = self
        try:
            code = self._run()
        except _Failure as err:
            if err.message:
                self.error(err.message)
            code = err.code
        except Exception as err: # pylint: disable=broad-exception-caught
            self.error(f"{type(err).__name__}: {err}")
            code = exitcodes.EXCEPTION
        finally:
            Runner._local.runner = previous
        self.returncode = code
        try:
            self._report(final=True)
        finally:
            self._done.set()

    def _run(self) -> int:
        options = self._commandline()
        try:
            if options["check"]:
                problems = self.model.check()
                for problem in problems:
                    self.error(problem)
                if problems:
                    raise _Failure(exitcodes.LDERR, f"model check found {len(problems)} problem(s)")
            if not options["compile"]:
                self._simulate(options["initialize"])
        finally:
            self._save()
        return exitcodes.SUCCESS

    def _commandline(self) -> dict[str,bool]:
        """Process the command line arguments in order"""
        from arras.model import ModelError # pylint: disable=import-outside-toplevel
        from arras.globals import GlobalsError # pylint: disable=import-outside-toplevel
        options = {"check": False, "compile": False, "initialize": False}
        toggles = {"-q": "quiet", "--quiet": "quiet", "-v": "verbose", "--verbose": "verbose",
            "-w": "warn", "--warn": "warn", "--debug": "debug"}
        flags = {"-c": "check", "--check": "check", "-C": "compile", "--compile": "compile",
            "-I": "initialize", "--initialize": "initialize"}
        globs = self.model.globals
        files = 0
        args = list(self.args)
        while args:
            arg = args.pop(0)
            if arg in toggles:
                globs.set(toggles[arg], not globs.getvalue(toggles[arg]))
            elif arg in flags:
                options[flags[arg]] = True
            elif arg in ("-D", "--define", "-o", "--output") or arg.startswith(("--define=", "--output=")):
                if "=" in arg and arg.startswith("--"):
                    arg, value = arg.split("=", 1)
                elif args:
                    value = args.pop(0)
                else:
                    raise _Failure(exitcodes.ARGERR, f"command line option '{arg}' is missing its value")
                try:
                    if arg in ("-D", "--define"):
                        globs.set(value)
                    else:
                        globs.set("savefile", value)
                except GlobalsError as err:
                    raise _Failure(exitcodes.ARGERR, f"command line option '{arg} {value}': {err}") from err
            elif arg.startswith("-") and arg != "-":
                raise _Failure(exitcodes.ARGERR, f"command line option '{arg}' is not supported")
            else:
                try:
                    self.model.read(arg)
                except (ModelError, OSError) as err:
                    raise _Failure(exitcodes.LDERR, f"{arg}: {err}") from err
                files += 1
                self._verbose(f"model file '{arg}' loaded ok")
        if files == 0 and len(self.model.objects) == 0:
            raise _Failure(exitcodes.ARGERR, "no model file specified")
        return options

    def _save(self) -> None:
        from arras.model import ModelError # pylint: disable=import-outside-toplevel
        savefile = self.model.globals.getvalue("savefile")
        if savefile:
            try:
                self.model.write(savefile)
            except (ModelError, OSError) as err:
                raise _Failure(exitcodes.IOERR, f"unable to save model to '{savefile}': {err}") from err
            self._verbose(f"model saved to '{savefile}'")

    def _time(self, obj:dict, key:str, default:int) -> int:
        value = obj.get(key)
        if value is None or value == "":
            return default
        return self.model.globals.timestamp_from_string(value)

    def _ranks(self, names:list[str]) -> dict[str,int]:
        """Object ranks: each parent ranks above its children (gridlabd
        `set_rank()`)"""
        objects = self.model.objects
        ranks = {name: int(objects[name].get("rank") or 0) for name in names}
        for name in names:
            rank = ranks[name]
            parent = objects[name].get("parent")
            while parent:
                rank = max(ranks[parent], rank+1)
                ranks[parent] = rank
                parent = objects[parent].get("parent")
        return ranks

    def _simulate(self, initialize_only:bool) -> None: # pylint: disable=too-many-locals
        globs = self.model.globals
        objects = self.model.objects
        names = sorted(objects, key=lambda name: objects[name].id)
        start = globs.getvalue("starttime")
        stop = globs.getvalue("stoptime")
        if stop == TS_ZERO:
            stop = TS_NEVER
            globs.set("stoptime", stop)
        if stop < start:
            raise _Failure(exitcodes.INIERR, "stoptime is before starttime")
        limit = globs.getvalue("iteration_limit")
        if limit < 1:
            raise _Failure(exitcodes.INIERR, f"iteration_limit {limit} is not positive")
        mts = globs.getvalue("minimum_timestep")

        # initialization
        globs.set("clock", start)
        stamp = globs.timestamp_to_string(start)
        for name in names:
            objects[name]["clock"] = stamp
        self._initialize(names)
        if initialize_only:
            return

        # passes in rank order (only objects with a handler for the pass)
        ranks = self._ranks(names)
        passes = []
        for event, topdown in PASSES:
            members = [name for name in names if self._handler(name, event)]
            members.sort(key=lambda name, td=topdown: -ranks[name] if td else ranks[name])
            passes.append((event, members))
        service = {name: (self._time(objects[name], "in_svc", TS_ZERO),
            self._time(objects[name], "out_svc", TS_NEVER)) for name in names}

        self._verbose("simulation started")
        try:
            self._loop(names, passes, service, start, stop, limit, mts)
        finally:
            self._finalize(names)
        if self.stopped:
            raise _Failure(exitcodes.RUNERR, f"simulation stopped at {self._simtime()}")
        self._verbose(f"simulation ended after {self.steps} time step(s)")

    def _initialize(self, names:list[str]) -> None:
        deferred = list(names)
        tries = 0
        maxdefer = self.model.globals.getvalue("init_max_defer")
        while deferred:
            if tries >= maxdefer:
                raise _Failure(exitcodes.INIERR, f"initialization of {', '.join(deferred)} deferred too many times (init_max_defer={maxdefer})")
            retry = []
            for name in deferred:
                result = self._event(name, "init", self.model.globals.getvalue("clock"))
                if result is None or result is True:
                    continue
                if result is False:
                    raise _Failure(exitcodes.INIERR, f"object {name} initialization failed")
                if result == INIT_DEFER and not isinstance(result, bool):
                    retry.append(name)
                    continue
                raise _Failure(exitcodes.INIERR, f"object {name} init handler returned {result!r}, not True, False, None, or 2")
            deferred = retry
            tries += 1

    def _loop(self, names, passes, service, start, stop, limit, mts) -> None: # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches
        globs = self.model.globals
        objects = self.model.objects
        counter = limit
        step, hard = start, True
        while hard and step != TS_NEVER and step <= stop:
            if self._stop.is_set():
                self.stopped = True
                return
            self.clock = step
            globs.set("clock", step)
            step, hard = TS_NEVER, False
            if stop != TS_NEVER:
                step, hard = stop + 1, True

            # precommit only on the first iteration of a time step
            if counter == limit:
                for name in names:
                    result = self._time_event(name, "precommit")
                    if result is not None and result != TS_NEVER and result < self.clock:
                        raise _Failure(exitcodes.RUNERR, f"object {name} precommit failed (returned {result})")

            # synchronization passes
            for event, members in passes:
                for name in members:
                    in_svc, out_svc = service[name]
                    if self.clock < in_svc:
                        t = in_svc
                    elif self.clock <= out_svc:
                        t = self._time_event(name, event)
                    else:
                        continue
                    if t is None or t == TS_NEVER:
                        continue
                    if t < -1:
                        t = -t
                    else:
                        hard = True
                    if t < self.clock:
                        raise _Failure(exitcodes.RUNERR, f"object {name} stopped its clock (its {event} handler returned {t})")
                    if counter == 2 and t == self.clock:
                        self._verbose(f"object {name} iteration limit imminent")
                    if mts > 1 and self.clock < t < TS_NEVER:
                        t = ((t-1)//mts + 1) * mts
                    step = min(step, t)

            # commit or iterate
            if step != self.clock:
                commit = TS_NEVER
                for name in names:
                    result = self._time_event(name, "commit")
                    if result is None or result == TS_NEVER:
                        continue
                    if result == TS_INVALID:
                        raise _Failure(exitcodes.RUNERR, f"object {name} commit failed")
                    if abs(commit) > abs(result):
                        commit = result
                if commit != TS_NEVER:
                    if abs(commit) <= self.clock:
                        raise _Failure(exitcodes.RUNERR, "model commit failed")
                    if commit > 0:
                        hard = True
                    step = min(step, abs(commit))
                stamp = globs.timestamp_to_string(self.clock)
                for obj in objects.values():
                    obj["clock"] = stamp
                counter = limit
                self.steps += 1
                self._progress_update(start, stop)
                self._report()
            else:
                counter -= 1
                if counter == 0:
                    raise _Failure(exitcodes.RUNERR, f"convergence iteration limit reached at {self._simtime()}")

    def _progress_update(self, start:int, stop:int) -> None:
        if stop == TS_NEVER:
            self._percent = None
            return
        fraction = 1.0 if stop == start else min(max((self.clock-start)/(stop-start), 0.0), 1.0)
        self._percent = round(100.0 * fraction, 6)
        self.model.globals.set("progress", fraction)

    def _finalize(self, names:list[str]) -> None:
        failed = []
        for name in names:
            try:
                self._event(name, "finalize", self.clock)
            except _Failure as err:
                self.error(err.message)
                failed.append(name)
        if failed:
            raise _Failure(exitcodes.RUNERR, f"finalize failed for {', '.join(failed)}")

    #
    # Event handlers
    #
    def _handler(self, name:str, event:str) -> str|None:
        """Handler script of an object for an event: the object's own, else
        its class's"""
        obj = self.model.objects[name]
        script = obj.get(f"on_{event}")
        if script is None:
            script = obj.oclass.get_event(event)
        return script or None

    def _time_event(self, name:str, event:str) -> int|None:
        result = self._event(name, event, self.clock)
        if result is None:
            return None
        if isinstance(result, bool) or not isinstance(result, int):
            raise _Failure(exitcodes.RUNERR, f"object {name} {event} handler returned {result!r}, not a timestamp")
        return result

    def _event(self, name:str, event:str, t:int) -> Any:
        """Call an object's event handler; `None` when it has none"""
        script = self._handler(name, event)
        if script is None:
            return None
        code = exitcodes.INIERR if event == "init" else exitcodes.RUNERR
        self._debug(f"object {name} {event} handler '{script}' called")
        if script.startswith("python:"):
            call = self._python(script[7:], code)
            try:
                return call(name, t)
            except Exception as err: # pylint: disable=broad-exception-caught
                raise _Failure(code, f"object {name} {event} handler '{script}' failed: {type(err).__name__}: {err}") from err
        return self._shell(name, event, script, t, code)

    def _python(self, spec:str, code:int) -> Callable:
        if spec in self._handlers:
            return self._handlers[spec]
        modname, _, funcname = spec.rpartition(".")
        if not modname or not funcname:
            raise _Failure(code, f"python handler '{spec}' is not MODULE.FUNCTION")
        try:
            module = self._import(modname)
            call = getattr(module, funcname)
        except (ImportError, AttributeError) as err:
            raise _Failure(code, f"python handler '{spec}' not found: {err}") from err
        if not callable(call):
            raise _Failure(code, f"python handler '{spec}' is not callable")
        self._handlers[spec] = call
        return call

    @staticmethod
    def _import(modname:str) -> Any:
        try:
            return importlib.import_module(modname)
        except ModuleNotFoundError:
            cwd = os.getcwd()
            if cwd in sys.path:
                raise
            sys.path.insert(0, cwd)
            try:
                return importlib.import_module(modname)
            finally:
                sys.path.remove(cwd)

    def _shell(self, name:str, event:str, script:str, t:int, code:int) -> None:
        env = dict(os.environ)
        env.update({
            "CLOCK": str(t),
            "HOSTNAME": str(self.model.globals.get("hostname") or socket.gethostname()),
            "PORT": str(self.model.globals.get("server_portnum") or 0),
            "OBJECT": name,
        })
        result = subprocess.run(script, shell=True, env=env, capture_output=True, text=True, check=False)
        self.stdout.extend(result.stdout.splitlines())
        self.stderr.extend(result.stderr.splitlines())
        if result.returncode != 0:
            raise _Failure(code, f"object {name} {event} handler '{script}' failed with code {result.returncode}")
