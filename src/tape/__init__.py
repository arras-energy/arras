# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras Energy `tape` module

The `tape` package implements the gridlabd `tape` module in Python. Its
objects play values from files into a model (players, shapers,
multiplayers) and record properties, aggregates, histograms, violations,
and metrics to files (recorders and collectors) during an
`arras.runner.Runner` simulation.

The file operations that gridlabd loads from its separate `tape_file`
module (the `file` tape mode) are part of this package. The `memory` and
`plot` modes (`tape_memory`, `tape_plot`) are not implemented.

Syntax
------

    module tape {
        gnuplot_path "<path>";
        flush_interval <integer>;
        csv_data_only <integer>;
        csv_header_type {FULL,NONE,NAME};
        csv_keep_clean <integer>;
    }

Classes
-------

| Class | Python class | Does |
| ----- | ------------ | ---- |
| `player` | `tape.player.Player` | plays a file into properties of its parent |
| `shaper` | `tape.shaper.Shaper` | plays a periodic shape into a property of a group of objects |
| `recorder` | `tape.recorder.Recorder` | records properties of its parent |
| `multi_recorder` | `tape.multi_recorder.MultiRecorder` | records properties of any objects |
| `collector` | `tape.collector.Collector` | records aggregates of a property over a group |
| `histogram` | `tape.histogram.Histogram` | records counts of values in bins |
| `group_recorder` | `tape.group_recorder.GroupRecorder` | records a property of every object of a group |
| `violation_recorder` | `tape.violation_recorder.ViolationRecorder` | records powerflow limit violations |
| `metrics_collector` | `tape.metrics_collector.MetricsCollector` | computes metrics of its parent over intervals |
| `metrics_collector_writer` | `tape.metrics_collector_writer.MetricsCollectorWriter` | writes the metrics to JSON files |
| `multiplayer` | `tape.multiplayer.Multiplayer` | plays the columns of a CSV file into properties |

Globals
-------

- `tape::gnuplot_path`: path of `gnuplot` for the `plot` mode (not used).
- `tape::flush_interval`: not used, as in gridlabd.
- `tape::csv_data_only`: header of CSV files: 0 (full comment header), 1
  (no header and no end-of-tape line), 2 (one line of column names).
- `tape::csv_header_type`: the same value as a keyword (`FULL`, `NONE`,
  `NAME`); gridlabd's two globals share one integer, and setting either
  sets both.
- `tape::csv_keep_clean`: when not 0, every row is flushed.
- `tape::delta_mode_needed`: the time deltamode is needed (always
  `NEVER`, since deltamode is not run).

Description
-----------

Users load the module from GLM (`module tape;`) or with
`arras.model.Model.load_module("tape")`. The package is an
`arras.modules` entry point, so when a model loads the module, `load()` is
expected to:

1. load the module in `arras.module.Module.registry`;
2. register the classes above for module `tape` in
   `arras.oclass.Class.registry` (unless they are registered already), in
   gridlabd's registration order, with the properties, types, keywords,
   defaults, flags, descriptions, pass configurations, and technology
   readiness levels that gridlabd publishes; and
3. create the globals above in the model.

Each class has the event handlers `python:tape.EVENT` for the passes its
C++ code synchronizes in (`init`, `precommit`, `presync`, `sync`,
`postsync`, `commit`, `finalize`). They call the behavior that each
class's module documents. An error message of an object, as gridlabd's
`gl_error()` writes it, makes the run end with exit code `RUNERR` without
stopping it (`arras.runner.Runner.setexitcode()`), as in gridlabd.

Examples
--------

    >>> from arras import Model, Class
    >>> import tape
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm("module tape { csv_header_type NAME; }\\n")
    >>> [oclass.name for oclass in tape.classes()]
    ['player', 'shaper', 'recorder', 'multi_recorder', 'collector', 'histogram', 'group_recorder', 'violation_recorder', 'metrics_collector', 'metrics_collector_writer', 'multiplayer']
    >>> m.globals.get("tape::csv_data_only")
    '2'
    >>> Class.reset()

Caveats
-------

- The objects get their behavior from class event handlers, so they work
  only in `arras.runner.Runner` simulations; calling the handlers outside
  a run raises `TapeError`.
- The module's `check()` function (the file checks of `gridlabd --check`)
  is not modeled.
- Deltamode is not run; the module's deltamode functions are not modeled.
- See each class's module for its caveats and differences from gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The `file` tape mode is built in; gridlabd loads it from a separate
   `tape_file` module. Other modes fail as gridlabd fails when it cannot
   find their module.

See each class's module for the differences that remain.

References
----------

- `arras-energy/gridlabd`: `module/tape/` (`tape.cpp`, `tape.h`, the class
  files, and the autotests in `module/tape/autotest/`),
  `module/tape_file/tape_file.cpp`, `source/aggregate.cpp`
- [Tape module](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape.md)
  (`docs/Module/Tape.md`)
"""

from typing import Any

from arras.module import Module
from arras.oclass import Class

from ._common import MODULE, TapeError, runner
from .player import Player
from .shaper import Shaper
from .recorder import Recorder
from .multi_recorder import MultiRecorder
from .collector import Collector
from .histogram import Histogram
from .group_recorder import GroupRecorder
from .violation_recorder import ViolationRecorder
from .metrics_collector import MetricsCollector
from .metrics_collector_writer import MetricsCollectorWriter
from .multiplayer import Multiplayer

CLASSES = (Player, Shaper, Recorder, MultiRecorder, Collector, Histogram, GroupRecorder,
    ViolationRecorder, MetricsCollector, MetricsCollectorWriter, Multiplayer)
"""Behavior of each class of the module, in gridlabd's registration order"""

CSV_HEADER_TYPES = {"NAME": 2, "NONE": 1, "FULL": 0}
"""Keywords of `tape::csv_header_type`, in the order gridlabd lists them"""

__all__ = ["TapeError", "Player", "Shaper", "Recorder", "MultiRecorder", "Collector", "Histogram",
    "GroupRecorder", "ViolationRecorder", "MetricsCollector", "MetricsCollectorWriter", "Multiplayer",
    "load", "classes", "init", "precommit", "presync", "sync", "postsync", "commit", "finalize",
    "player", "shaper", "recorder", "multi_recorder", "collector", "histogram", "group_recorder",
    "violation_recorder", "metrics_collector", "metrics_collector_writer", "multiplayer"]

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
    for name, value, ptype, keywords in (
            ("gnuplot_path", "/usr/bin/gnuplot", "char1024", None),
            ("flush_interval", 0, "int32", None),
            ("csv_data_only", 0, "int32", None),
            ("csv_header_type", "FULL", "enumeration", CSV_HEADER_TYPES),
            ("csv_keep_clean", 0, "int32", None),
            ("delta_mode_needed", "NEVER", "timestamp", None)):
        gname = f"{MODULE}::{name}"
        if not globs.isdefined(gname):
            globs.create(gname, value, ptype=ptype, keywords=keywords)
    data_only = globs.find(f"{MODULE}::csv_data_only")
    header_type = globs.find(f"{MODULE}::csv_header_type")
    def share(name:str, value:str) -> None: # pylint: disable=unused-argument
        """Keep the two globals that share gridlabd's `csv_data_only` in step"""
        if name.endswith("csv_header_type"):
            data_only.value = header_type.to_python() if isinstance(header_type.to_python(), int) else CSV_HEADER_TYPES.get(value, 0)
        else:
            header_type.value = int(data_only.to_python() or 0)
    data_only.callback = share
    header_type.callback = share

def classes() -> list[Class]:
    """Classes registered for the module, in registration order"""
    return [oclass for oclass in Class.registry if oclass.module == MODULE]

_BY_NAME = {cls.NAME: cls for cls in CLASSES}

def _behavior(model:Any, name:str) -> Any:
    """Behavior of an object: that of its class, or of the nearest class it
    inherits from that the module defines"""
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name in _BY_NAME:
            return _BY_NAME[oclass.name]
        oclass = getattr(oclass, "parent", None)
    raise TapeError(f"object '{name}' is not a tape object")

def _call(event:str, name:str, t:int) -> Any:
    model = runner().model
    cls = _behavior(model, name)
    return getattr(cls, event)(model, name, t)

def init(name:str, t:int) -> bool:
    """`on_init` event handler

    Exceptions
    ----------
    - `TapeError`: no simulation is running, or the object is not a tape
      object
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

def postsync(name:str, t:int) -> int|None:
    """`on_postsync` event handler (exceptions: see `init()`)"""
    return _call("postsync", name, t)

def commit(name:str, t:int) -> int|None:
    """`on_commit` event handler (exceptions: see `init()`)"""
    return _call("commit", name, t)

def finalize(name:str, t:int) -> None:
    """`on_finalize` event handler (exceptions: see `init()`)"""
    _call("finalize", name, t)
