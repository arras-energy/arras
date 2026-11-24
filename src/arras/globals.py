"""Arras global variables

The `Globals` class holds the global variables of an Arras Energy
(HiPAS GridLAB-D) run. The constructor defines every global variable that
`arras-energy/gridlabd` registers in `source/globals.cpp` and sets each one
to the default value that `gridlabd` gives it in `source/globals.h`.

Users can get, set, and create global variables, and evaluate the
pseudo-globals and parameter expansions that GLM files write as `${...}`.

Syntax
------

    from arras.globals import Globals
    g = Globals([values], [NAME=VALUE ...])

Arguments
---------
- `values`: dict of initial values that override the defaults (use this
  for names that are not Python identifiers, e.g. `"version.major"`)
- `**kwargs`: initial values that override the defaults

Description
-----------

Given no arguments, `Globals()` returns an object that is expected to satisfy:

1. Every global variable in the `map[]` table of gridlabd's
   `source/globals.cpp` is defined, in the same order, with the same
   property type, access, description, and keywords.
2. `get(name)` returns the same string that `gridlabd` prints for that
   global (`gridlabd --globals`), using the same conversion rules
   (`double_format`, `dateformat`, `TRUE`/`FALSE`, keyword names for
   enumerations, `|`-separated keywords for sets, `INIT`/`NEVER` for
   timestamps).
3. `set(name,value)` converts a string the same way `gridlabd`'s
   `global_setvar()` does, and also accepts typed Python values.
4. `set()` of an undefined name raises `GlobalsError` while `strictnames`
   is true (the gridlabd default) and creates a `char1024` global when it
   is false.
5. `get(spec)` evaluates the pseudo-globals and expansions listed below in
   the same order that `global_getvar()` tests them, and returns `None` when
   `global_getvar()` would return `NULL`.

Pseudo-globals
--------------

| Spec | Result |
| ---- | ------ |
| `GUID` | a new random GUID |
| `RUN` | a GUID that stays the same for this `Globals` object |
| `TODAY` | current UTC date and time, `%Y-%m-%d %H:%M:%S UTC` |
| `NOW [FORMAT]` | current UTC time in `strftime` FORMAT (default `%Y%m%d-%H%M%S`) |
| `URAND`, `NRAND` | uniform(0,1) and normal(0,1) random numbers |
| `RANDOM [SPEC]` | uniform(0,1), an N-bit integer (`N`), a distribution (`normal(0,1)`), or `last` |
| `LINUX`, `APPLE`, `WINDOWS` | `1` on the matching platform only |
| `PYTHON` | `1` |
| `PID` | process ID |
| `SEQ_NAME:INIT`, `SEQ_NAME:INC` | create an int32 sequence at 0, or increment it |
| `SHELL COMMAND` | output of a shell command, newlines replaced by spaces |
| `PYTHON EXPRESSION` | `repr()` of a Python expression |
| `RANGE<d>START,STOP,STEP` | values from START to STOP separated by `d` (space, `,`, `;`, or `:`) |
| `FINDFILE NAME` | full path of NAME found in `arras.folders.search_path()`, else empty |
| `FILENAME SPEC`, `FILEPATH SPEC`, `FILETYPE SPEC` | name, folder, or extension of a path, or of `$GLOBAL` |
| `FIND CRITERIA` | names of objects matching CRITERIA (see `object_finder`) |
| `GEOCODE LAT,LON[#RES]`, `GEOCODE OBJECT[#RES]`, `GEOCODE HASH[.lat|.lon]` | geohash encode and decode |
| `TMPFILE [TAG]` | a temporary file name, created now and deleted by `cleanup()` |
| `object.last` | name of the last object created (see `object_last`) |

Expansions
----------

| Spec | Result |
| ---- | ------ |
| `name:-value` | value of `name` if defined, else `value` |
| `name:=value` | defines `name` as `value` if undefined, then returns its value |
| `name:+value` | `value` if `name` is defined, else empty |
| `name:offset[:length]` | substring of the value of `name` |
| `name/pattern/value` | value of `name` with the first `pattern` replaced |
| `name//pattern/value` | value of `name` with every `pattern` replaced |
| `++name`, `--name` | int32 `name` after increment or decrement |
| `name++`, `name--` | int32 `name` before increment or decrement |
| `[~]name OP [~]number` | int32 arithmetic, OP in `+ - * / % & | ^` |
| `name OP= [~]number` | int32 update, OP in `+ - * / % & | ^`, returns the new value |
| `name REL number[?yes[:no]]` | REL in `== != <> < <= > >= & |~`; `yes`/`no` default to `1`/`0`; `&` and `|~` need `?` (else they are the bitwise forms) |
| `name=number` | creates or sets int32 `name` |
| `name=string` | creates or sets char1024 `name` |

Examples
--------

    >>> from arras.globals import Globals
    >>> g = Globals(randomseed=1)
    >>> g.get("starttime")
    '2000-01-01 00:00:00 UTC'
    >>> g.get("stoptime")
    'NEVER'
    >>> g.get("validate")
    'TSTD|RALL'
    >>> g.set("double_format","%.3f")
    >>> g.get("realtime_metric")
    '0.000'
    >>> g.create("count",0)
    <Globalvar count:int32=0>
    >>> g.get("count++"), g.get("count"), g.get("count+=10"), g.get("count>5?big:small")
    ('0', '1', '11', 'big')
    >>> g.get("SEQ_ID:INIT"), g.get("SEQ_ID:INC"), g.get("SEQ_ID")
    ('0', '1', '1')
    >>> g.get("RANGE,1,5,2")
    '1,3,5'
    >>> g.get("GEOCODE 37.4,-122.2#6")
    '9q9hg2'
    >>> g.expand("start=${starttime}, missing=${nothing:-none}")
    'start=2000-01-01 00:00:00 UTC, missing=none'
    >>> g.set("undefined_name","x")
    Traceback (most recent call last):
    ...
    arras.globals.GlobalsError: strict naming prevents implicit creation of undefined_name

Caveats
-------

- `Globals` is an independent Python model of gridlabd's globals. It
  does not read from or write to a running `gridlabd` process.
- Values that `gridlabd` fixes at build or run time (`version*`,
  `command_line`, `execdir`, `exename`, `modelname`, `origin`,
  `gitbranch`) start empty or are taken from the installed `arras`
  package version. Folder globals come from `arras.folders`, not from a
  gridlabd install: `datadir`, `libdir`, `incdir`, `vardir`, and `tmp` are
  the `share`, `lib`, `include`, `var`, and `tmp` subfolders of the user
  folder (`ARRAS_USERDIR`, else `~/.arras`); `bindir` is the folder where
  Python installs scripts such as `arras`, and `pythonexec` is the running
  Python. The default values name folders without creating them. Override
  any of them in the constructor.
- `set()` does not check `access`, matching `global_setvar()`; the access
  value is recorded for users who need it.
- Random numbers come from Python's `random` module seeded by
  `randomseed`, so sequences differ from gridlabd's generator.
- `FIND`, `object.last`, and `GEOCODE OBJECT` need a model. They call the
  `object_finder` and `object_last` hooks, which users can assign; without
  them, `FIND` returns an empty string and the others return `None`.
- Only `UTC` and IANA zone names (Python `zoneinfo`) are supported for
  `timezone_locale`. gridlabd's own `tzinfo.txt` rules are not read.
- `PYTHON EXPRESSION` and `SHELL COMMAND` run arbitrary code, as they do in
  gridlabd. Do not expand untrusted text.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

Where gridlabd's code and its documentation (`docs/GLM/Global/*.md`)
disagree, `Globals` follows the documentation:

1. `${name//pattern/value}` replaces every match. The core only matches
   this form when `value` is empty (`sscanf(...)==2`).
2. `${name/N}`, `${name/=N}`, `${name&N}`, `${name|N}`, and `${name^N}`
   perform integer operations when `name` is an int32 global; the
   comparisons `&` and `|~` are used only when followed by `?`. In the core,
   `/` is first taken as the `name/pattern/value` replacement form, the
   operator scan set is `[+-*/%]`, `&` is evaluated as the comparison
   form (`1`/`0`), and `|`, `^` are not evaluated.
3. `${RANGE:...}` accepts a colon delimiter. The core's dispatch only
   accepts space, comma, and semicolon.
4. `${name:=value}` and `${name=string}` create `name` when undefined. The
   core refuses to create a string global this way while `strictnames`
   is true.
5. `RANDOM sampled(a,b,...)` picks one of its arguments, and
   `RANDOM gamma(alpha[,beta])` accepts one or two arguments. The core
   rejects `sampled` with more than two arguments and reads `gamma` with
   one argument only.
6. `RANGE` with a zero or negative step raises `GlobalsError`; the core
   loops until its buffer is full.
7. `profile_output_format` has no keywords, matching the core's `map[]`
   entry (its `pof_keys` table is not attached), so its value prints as an
   empty string.

The folder globals do not depend on a gridlabd install (see
`arras.folders`):

8. `datadir`, `bindir`, `libdir`, `vardir`, `incdir`, `pythonexec`,
   `configpath`, `logfile`, `pidfile_dir`, and `tmp` default to folders of
   the user folder and the running Python. `GLD_ETC`, `GLD_BIN`,
   `GLD_LIB`, `GLD_VAR`, `GLD_INC`, and `GLTEMP` are not read.
9. `${FINDFILE NAME}` searches the working folder, the user `share`
   folder, the `GLPATH` folders, and the `arras` package folder.

References
----------

- `arras-energy/gridlabd`: `source/globals.cpp`, `source/globals.h`,
  `source/convert.cpp`, `source/timestamp.cpp`, `source/random.cpp`,
  `source/tmpfile.cpp`
- [Global variables](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/GLM/Global/Expansion.md)
  (`docs/GLM/Global/` and `docs/Global/` in `arras-energy/gridlabd`)
"""

# pylint: disable=too-many-lines,line-too-long
# (the gridlabd reference table and the markdown tables above are kept one row per line)

import os
import re
import sys
import math
import random
import logging
import datetime
import sysconfig
import subprocess
from typing import Any, Callable, Iterator

from arras.exceptions import ArrasException
from arras import folders

_logger = logging.getLogger(__file__)

TS_ZERO = 0
"""Timestamp value printed as `INIT`"""

TS_NEVER = (1 << 63) - 1
"""Timestamp value printed as `NEVER`"""

BRANCH = "master"
"""Source branch used for branch-dependent defaults (`version.branch`,
`kmlhost`); an assumption, since gridlabd fixes it at build time"""

GITHUB_ORG = "arras-energy"
"""GitHub organization used for `infourl` (gridlabd `GITHUB_ORG`)"""

SECOND, MINUTE, HOUR, DAY = 1, 60, 3600, 86400

PROPERTY_TYPES = {
    "bool": None,
    "int16": 16,
    "int32": 32,
    "int64": 64,
    "double": None,
    "char8": 8,
    "char32": 32,
    "char256": 256,
    "char1024": 1024,
    "timestamp": None,
    "enumeration": None,
    "set": None,
}
"""Property types supported for global variables (value is the bit width of
integers or the buffer size of strings)"""

ACCESS = ("PUBLIC", "REFERENCE", "PROTECTED", "PRIVATE", "HIDDEN")
"""Property access values"""

class GlobalsError(ArrasException):
    """Global variable error"""

#
# Keyword tables (source/globals.cpp, in the order gridlabd lists them)
#
_KEYS = {
    "cnf": {"DEFAULT":0, "RECT":1, "POLAR_DEG":2, "POLAR_RAD":3},
    "df": {"ISO":0, "US":1, "EURO":2, "ISO8601":3},
    "trl": {"PRINCIPLE":1, "CONCEPT":2, "PROOF":3, "STANDALONE":4,
        "INTEGRATED":5, "DEMONSTRATED":6, "PROTOTYPE":7, "QUALIFIED":8,
        "PROVEN":9, "UNKNOWN":0},
    "cpt": {"NONE":0, "WALL":1, "SIM":2},
    "rng": {"RNG2":2, "RNG3":3},
    "mls": {"INIT":0, "RUNNING":1, "PAUSED":2, "DONE":3, "LOCKED":4},
    "mrm": {"STANDALONE":0, "MASTER":1, "SLAVE":2, "LIBRARY":3},
    "mrc": {"NONE":0, "MEMORY":1, "SOCKET":2},
    "isc": {"CREATION":0, "DEFERRED":1, "BOTTOMUP":2, "TOPDOWN":3},
    "mcf": {"NONE":0x00, "CLEAN":0x01, "KEEPWORK":0x02, "DEBUG":0x04,
        "VERBOSE":0x08},
    "vo": {"NONE":0x0000, "TSTD":0x0007, "TALL":0x000f, "TRUN":0x0001,
        "TERR":0x0002, "TEXC":0x0004, "TOPT":0x0008, "RALL":0x0300,
        "RDIR":0x0100, "RGLM":0x0200},
    "so": {"NAMES":0x0010, "POSITIONS":0x0060},
    "sm": {"INIT":0x00, "EVENT":0x01, "DELTA":0x02, "DELTA_ITER":0x03,
        "ERROR":0xff},
    "dmc": {"NONE":0, "ALL":0x000fffffffffffff, "LOAD":0x4,
        "CREATE":0x8, "EXEC":0x10, "TIME":0x20, "FIND":0x40, "CLASS":0x80,
        "OBJECT":0x100, "MODULE":0x200, "INDEX":0x400, "GLOBALS":0x800,
        "EXCEPTION":0x1000, "AGGREGATE":0x2000, "COMPARE":0x4000,
        "CONVERT":0x8000, "DELTAMODE":0x10000, "ENDUSE":0x20000,
        "ENVIRONMENT":0x40000, "GUI":0x80000, "HTTPCLIENT":0x100000,
        "INSTANCE":0x200000, "INTERPOLATE":0x400000, "JOB":0x800000,
        "KML":0x1000000, "LEGAL":0x2000000, "LINK":0x4000000,
        "LIST":0x8000000, "XML":0x10000000, "LOADSHAPE":0x20000000,
        "LOCALE":0x40000000, "LOCK":0x80000000, "MATCH":0x100000000,
        "MATLAB":0x200000000, "PROPERTY":0x400000000,
        "RANDOM":0x800000000, "REALTIME":0x1000000000,
        "SANITIZE":0x2000000000, "SAVE":0x4000000000,
        "SCHEDULE":0x8000000000, "SERVER":0x10000000000,
        "SETUP":0x20000000000, "STREAM":0x40000000000,
        "TEST":0x80000000000, "THREADPOOL":0x100000000000,
        "TRANSFORM":0x200000000000, "HTTP":0x400000000000,
        "UNIT":0x800000000000, "VALIDATE":0x1000000000000,
        "VERSION":0x2000000000000, "XCORE":0x4000000000000,
        "MAIN":0x1, "PYTHON":0x8000000000000, "CMDARG":0x2},
    "vtc": {"SYNC":0x00, "PRECOMMIT":0x01, "COMMIT":0x02},
    "gso": {"LEGACY":0x0000, "MINIMAL":0x000f, "NOGLOBALS":0x0004,
        "NODEFAULTS":0x0008, "NOMACROS":0x0002, "NOINTERNALS":0x0001,
        "ORIGINAL":0x0010},
    "fso": {"ALLINITIAL":0xc1ff, "ALLMINIMAL":0x81ff, "ALL":0x01ff,
        "MODULES":0x0001, "PROPERTIES":0x0002, "CLASSES":0x0004,
        "GLOBALS":0x0008, "OBJECTS":0x0010, "SCHEDULES":0x0020,
        "FILTERS":0x0040, "SCRIPTS":0x0080, "CLOCK":0x0100,
        "INITIAL":0x4000, "MINIMAL":0x8000},
    "jcf": {"STRING":0x0000, "LIST":0x0001, "DICT":0x0002,
        "DEGREES":0x0010, "RADIANS":0x0020},
}

def _platform() -> str:
    if sys.platform.startswith("win"):
        return "WINDOWS"
    if sys.platform == "darwin":
        return "MACOSX"
    return "LINUX"

def _browser() -> str:
    return {"WINDOWS":"iexplore", "MACOSX":"safari"}.get(_platform(), "firefox")

def _tmp() -> str:
    """Default `tmp`: the `tmp` folder of the user folder (gridlabd uses
    `~/.gridlabd/tmp` in `buildtmp()`)"""
    return folders.userdir("tmp")

def _version() -> tuple[int,int,int,int]:
    """Version numbers from the installed `arras` package"""
    try:
        import importlib.metadata # pylint: disable=import-outside-toplevel
        text = importlib.metadata.version("arras")
    except Exception: # pylint: disable=broad-exception-caught
        text = "0.0.0"
    parts = [int(x) for x in re.findall(r"\d+",text)[:4]]
    return tuple((parts + [0,0,0,0])[:4])

def _defaults() -> list[tuple]:
    """Global variable table: `(name, type, default, access, description,
    keywords)` in gridlabd `map[]` order. An alias is given as
    `(name, "alias", target, ...)`."""
    userdir = folders.userdir
    major, minor, patch, build = _version()
    K = _KEYS # pylint: disable=invalid-name
    P, R, X = "PUBLIC", "REFERENCE", "PROTECTED" # pylint: disable=invalid-name
    return [
        ("version.major", "int32", major, R, "major version", None),
        ("version.minor", "int32", minor, R, "minor version", None),
        ("version.patch", "int32", patch, R, "patch number", None),
        ("version.build", "int32", build, R, "build number", None),
        ("version.branch", "char256", BRANCH, R, "branch name", None),
        ("version", "char1024", f"{major}.{minor}.{patch}-{build}-{BRANCH}", R, "full version information", None),
        ("command_line", "char1024", "", R, "command line", None),
        ("environment", "char1024", "batch", P, "operating environment", None),
        ("quiet", "bool", False, P, "quiet output status flag", None),
        ("warn", "bool", True, P, "warning output status flag", None),
        ("debugger", "bool", False, P, "debugger enable flag", None),
        ("gdb", "bool", False, P, "gdb enable flag", None),
        ("debug", "bool", False, P, "debug output status flag", None),
        ("test", "alias", "debugger", P, "test enable flag", None),
        ("verbose", "bool", False, P, "verbose enable flag", None),
        ("iteration_limit", "int32", 100, P, "iteration limit", None),
        ("workdir", "char1024", ".", R, "working directory", None),
        ("dumpfile", "char1024", "gridlabd.json", P, "dump filename", None),
        ("savefile", "char1024", "", P, "save filename", None),
        ("dumpall", "bool", False, P, "dumpall enable flag", None),
        ("runchecks", "bool", False, P, "runchecks enable flag", None),
        ("threadcount", "int32", 1, P, "number of threads to use while using multicore", None),
        ("profiler", "bool", False, P, "profiler enable flag", None),
        ("pauseatexit", "bool", False, P, "pause at exit flag", None),
        ("testoutputfile", "char1024", "test.txt", P, "filename for test output", None),
        ("xml_encoding", "int32", 8, P, "XML data encoding", None),
        ("clock", "timestamp", TS_ZERO, P, "global clock", None),
        ("starttime", "timestamp", 946684800, P, "simulation start time", None),
        ("stoptime", "timestamp", TS_NEVER, P, "simulation stop time", None),
        ("double_format", "char32", "%+lg", P, "format for writing double values", None),
        ("complex_format", "char256", "%+lg%+lg%c", P, "format for writing complex values", None),
        ("complex_output_format", "enumeration", 0, P, "complex output representation", K["cnf"]),
        ("object_format", "char32", "%s:%d", P, "format for writing anonymous object names", None),
        ("object_scan", "char32", "%[^:]:%d", P, "format for reading anonymous object names", None),
        ("object_tree_balance", "bool", False, P, "object index tree balancing enable flag", None),
        ("kmlfile", "char1024", "", P, "KML output file name", None),
        ("kmlhost", "char1024", f"https://code.arras.energy/{BRANCH}/runtime", P, "KML server URL", None),
        ("modelname", "char1024", "", R, "model name", None),
        ("execdir", "char1024", "", R, "directory where executable binary was found", None),
        ("strictnames", "bool", True, P, "strict global name enable flag", None),
        ("website", "alias", "urlbase", P, "url base string (deprecated)", None),
        ("urlbase", "char1024", "http://www.gridlabd.org/", P, "url base string", None),
        ("randomstate", "int32", 0, P, "random number generator state value", None),
        ("randomseed", "int32", 0, P, "random number generator seed value", None),
        ("include", "char1024", "", R, "include folder path", None),
        ("trace", "char1024", "", P, "trace function list", None),
        ("gdb_window", "bool", False, P, "gdb window enable flag", None),
        ("tmp", "char1024", _tmp(), P, "temporary folder name", None),
        ("force_compile", "int32", 0, P, "force recompile enable flag", None),
        ("nolocks", "bool", False, P, "locking disable flag", None),
        ("skipsafe", "bool", False, P, "skip sync safe enable flag", None),
        ("dateformat", "enumeration", 0, P, "date format string", K["df"]),
        ("init_sequence", "enumeration", 1, P, "initialization sequence control flag", K["isc"]),
        ("minimum_timestep", "int32", 1, P, "minimum timestep", None),
        ("platform", "char8", _platform(), R, "operating platform", None),
        ("suppress_repeat_messages", "bool", True, P, "suppress repeated messages enable flag", None),
        ("maximum_synctime", "int32", 60, P, "maximum sync time for deltamode", None),
        ("run_realtime", "bool", False, P, "realtime enable flag", None),
        ("enter_realtime", "timestamp", TS_NEVER, P, "timestamp to transition to realtime mode", None),
        ("realtime_metric", "double", 0.0, R, "realtime performance metric (0=worst, 1=best)", None),
        ("no_deprecate", "bool", False, P, "suppress deprecated usage message enable flag", None),
        ("streaming_io", "bool", False, X, "streaming I/O enable flag", None),
        ("compileonly", "bool", False, X, "compile only enable flag", None),
        ("initializeonly", "bool", False, X, "initialize only enable flag", None),
        ("relax_naming_rules", "bool", False, P, "relax object naming rules enable flag", None),
        ("browser", "char1024", _browser(), P, "browser selection", None),
        ("server_portnum", "int32", 0, P, "server port number (default is find first open starting at 6267)", None),
        ("server_quit_on_close", "bool", False, P, "server quit on connection closed enable flag", None),
        ("client_allowed", "char1024", "", P, "clients from which to accept connecdtions", None),
        ("autoclean", "bool", True, P, "autoclean enable flag", None),
        ("technology_readiness_level", "enumeration", 0, P, "technology readiness level", K["trl"]),
        ("show_progress", "bool", True, P, "show progress enable flag", None),
        ("checkpoint_type", "enumeration", 0, P, "checkpoint type usage flag", K["cpt"]),
        ("checkpoint_file", "char1024", "", P, "checkpoint file base name", None),
        ("checkpoint_seqnum", "int32", 0, P, "checkpoint sequence number", None),
        ("checkpoint_interval", "int32", 0, P, "checkpoint interval", None),
        ("checkpoint_keepall", "bool", False, P, "checkpoint file keep enable flag", None),
        ("check_version", "bool", False, P, "check version enable flag", None),
        ("random_number_generator", "enumeration", 3, P, "random number generator version control flag", K["rng"]),
        ("mainloop_state", "enumeration", 0, P, "main sync loop state flag", K["mls"]),
        ("pauseat", "timestamp", TS_NEVER, P, "pause at time", None),
        ("infourl", "char1024", f"http://docs.arras.energy/index.html?owner={GITHUB_ORG}&project=gridlabd&search=", P, "URL to use for obtaining online help", None),
        ("hostname", "char1024", "localhost", P, "unused", None),
        ("hostaddr", "char32", "127.0.0.1", P, "unused", None),
        ("autostart_gui", "bool", True, P, "automatic GUI start enable flag", None),
        ("master", "char1024", "", P, "master server hostname", None),
        ("master_port", "int64", 0, P, "master server port number", None),
        ("multirun_mode", "enumeration", 0, P, "multirun enable flag", K["mrm"]),
        ("multirun_conn", "enumeration", 0, P, "unused", K["mrc"]),
        ("signal_timeout", "int32", 5000, P, "unused", None),
        ("slave_port", "int16", 6267, P, "unused", None),
        ("slave_id", "int64", 0, P, "unused", None),
        ("return_code", "int32", 0, R, "unused", None),
        ("exit_code", "int16", 0, R, "The exit code for GridLAB-D", None),
        ("module_compiler_flags", "set", 0, P, "module compiler flags", K["mcf"]),
        ("init_max_defer", "int32", 64, R, "deferred initialization limit", None),
        ("mt_analysis", "bool", False, P, "perform multithread profile optimization analysis", None),
        ("inline_block_size", "int32", 16*65536, P, "inline code block size", None),
        ("validate", "set", 0x0307, P, "validation test options", K["vo"]),
        ("sanitize", "set", 0x0070, P, "sanitize process options", K["so"]),
        ("sanitize_prefix", "char8", "GLD_", P, "sanitized name prefix", None),
        ("sanitize_index", "char1024", ".txt", P, "sanitization index file spec", None),
        ("sanitize_offset", "char32", "", P, "sanitization lat/lon offset", None),
        ("simulation_mode", "enumeration", 0, P, "current time simulation type", K["sm"]),
        ("deltamode_allowed", "bool", False, P, "flag to allow simulation in deltamode", None),
        ("deltamode_timestep", "int32", 10000000, P, "uniform step size for deltamode simulations", None),
        ("deltamode_maximumtime", "int64", 3600000000000, P, "maximum time (ns) deltamode can run", None),
        ("deltaclock", "int64", 0, P, "cumulative delta runtime with respect to the global clock", None),
        ("delta_current_clock", "double", 0.0, P, "Absolute delta time (global clock offset)", None),
        ("deltamode_updateorder", "char1024", "", R, "order in which modules are update in deltamode", None),
        ("deltamode_iteration_limit", "int32", 10, P, "iteration limit for each delta timestep (object and interupdate)", None),
        ("deltamode_forced_extra_timesteps", "int32", 0, P, "forced extra deltamode timesteps before returning to event-driven mode", None),
        ("deltamode_forced_always", "bool", False, P, "forced deltamode for debugging -- prevents event-driven mode", None),
        ("run_powerworld", "bool", False, P, "boolean that that says your system is set up correctly to run with PowerWorld", None),
        ("bigranks", "bool", True, P, "enable fast/blind set_rank operations", None),
        ("exename", "char1024", "", R, "argv[0] value", None),
        ("wget_options", "char1024", "maxsize:100MB;update:newer", P, "wget/curl options", None),
        ("curl_options", "alias", "wget_options", P, "wget/curl options", None),
        ("svnroot", "char1024", "https://github.com/arras-energy/gridlabd", P, "svnroot", None),
        ("github", "char1024", "https://github.com/arras-energy/gridlabd", P, "github file repository", None),
        ("gitraw", "char1024", "https://raw.githubusercontent.com/arras-energy/gridlabd", P, "github raw file access", None),
        ("allow_reinclude", "bool", False, P, "allow the same include file to be included multiple times", None),
        ("output_message_context", "set", K["dmc"]["ALL"], P, "control context from which debug messages are allowed", K["dmc"]),
        ("permissive_access", "int32", 0, P, "enable permissive property access", None),
        ("relax_undefined_if", "bool", False, P, "allow #if macro to handle undefined global variable as empty strings", None),
        ("literal_if", "bool", True, P, "do not interpret lhs of #if macro as a variable name", None),
        ("validto_context", "enumeration", 0, P, "events to which valid_to time applies, rather than just sync passes", K["vtc"]),
        ("daemon_configfile", "char1024", "gridlabd.cnf", P, "name of configuration file used by the daemon", None),
        ("timezone_locale", "char1024", "UTC", R, "timezone specified by the clock directive", None),
        ("glm_save_options", "set", 0, P, "options to control GLM file save format", K["gso"]),
        ("filesave_options", "set", 0x01ff, P, "control elements saved on output", K["fso"]),
        ("ignore_errors", "bool", False, P, "disable exit on error behavior", None),
        ("keep_progress", "bool", False, P, "keep each progress line", None),
        ("allow_variant_aggregates", "bool", False, P, "permits aggregates to include time-varying criteria", None),
        ("progress", "double", 0.0, R, "computed progress based on clock, start, and stop times", None),
        ("server_keepalive", "bool", False, P, "flag to keep server alive after simulation is complete", None),
        ("pythonpath", "char1024", os.getenv("PYTHONPATH",""), P, "folder to append to python module search path", None),
        ("pythonexec", "char1024", sys.executable, R, "python executable used to build gridlabd", None),
        ("datadir", "char1024", userdir("share"), R, "folder in which share data is stored", None),
        ("bindir", "char1024", sysconfig.get_path("scripts"), R, "folder in which share data is stored", None),
        ("vardir", "char1024", userdir("var"), R, "folder in which share data is stored", None),
        ("libdir", "char1024", userdir("lib"), R, "folder in which share data is stored", None),
        ("incdir", "char1024", userdir("include"), R, "folder in which share data is stored", None),
        ("logfile", "char1024", userdir("var","arras-log"), R, "daemon logfile name", None),
        ("pidfile_dir", "char1024", userdir("var","pid"), R, "folder in which share data is stored", None),
        ("configpath", "char1024", userdir("share","solver_py.conf"), R, "folder in which share data is stored", None),
        ("json_complex_format", "set", 0, P, "JSON complex number format", K["jcf"]),
        ("rusage_file", "char1024", "gridlabd-rusage.csv", P, "file in which resource usage data is collected", None),
        ("rusage_rate", "int64", 0, P, "rate at which resource usage data is collected (in seconds)", None),
        ("rusage", "char1024", "{}", P, "rusage data", None),
        ("echo", "bool", False, P, "echo subcommands", None),
        ("filename", "char1024", "", R, "current filename processed by loader", None),
        ("country", "char8", "US", P, "country code", None),
        ("region", "char32", "", P, "region code", None),
        ("organization", "char32", "arras-energy", P, "organization name", None),
        ("profile_output_format", "set", 0, P, "profiler output data format", None),
        ("maximum_runtime", "int64", 0, P, "maximum wall clock runtime allowed", None),
        ("flush_output", "int32", 0, P, "flush output buffers continuously", None),
        ("origin", "char1024", "", R, "origin of source code", None),
        ("gitbranch", "char1024", "", R, "branch of source code at origin", None),
    ]

def _c_format(fmt:str) -> str:
    """Convert a C printf format to a Python %-format"""
    return re.sub(r"%([-+ #0]*\d*(?:\.\d+)?)(?:hh|h|ll|l|L|q|j|z|t)([diouxXeEfFgGcs])",
        r"%\1\2", fmt)

def _wrap(value:int, bits:int) -> int:
    """Wrap an integer to a signed C integer of `bits` bits"""
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits-1) else value

def _cdiv(a:int, b:int) -> int:
    """C integer division (truncates toward zero)"""
    if b == 0:
        raise GlobalsError("integer division by zero")
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q

def _cmod(a:int, b:int) -> int:
    """C integer remainder (sign of dividend)"""
    return a - _cdiv(a,b) * b

class Globalvar: # pylint: disable=too-many-instance-attributes
    """Global variable

    Attributes
    ----------
    - `name`: variable name
    - `ptype`: property type (see `PROPERTY_TYPES`)
    - `access`: property access (see `ACCESS`)
    - `description`: description
    - `keywords`: dict of keyword values for `enumeration` and `set` types
    - `unit`: unit of a `double` (printed after the value)
    - `callback`: function called as `callback(name,value)` after each set
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
            owner:"Globals",
            name:str,
            ptype:str="char1024",
            value:Any=None,
            access:str="PUBLIC",
            description:str|None=None,
            keywords:dict[str,int]|None=None,
            unit:str|None=None,
            ):
        """Create a global variable (use `Globals.create()` instead)"""
        if ptype not in PROPERTY_TYPES:
            raise GlobalsError(f"property type '{ptype}' is not supported")
        if access not in ACCESS:
            raise GlobalsError(f"property access '{access}' is not valid")
        if unit is not None and ptype != "double":
            raise GlobalsError(f"unit '{unit}' is only valid for double properties")
        self.owner = owner
        self.name = name
        """Variable name"""
        self.ptype = ptype
        """Property type"""
        self.access = access
        """Property access"""
        self.description = description
        """Description"""
        self.keywords = dict(keywords) if keywords else {}
        """Keyword values for enumeration and set types"""
        self.unit = unit
        """Unit of a double"""
        self.callback = None
        """Function called as `callback(name,value)` after each set"""
        self.value = self._default()
        if value is not None:
            self.set(value)

    def __repr__(self):
        return f"<Globalvar {self.name}:{self.ptype}={self.to_string()}>"

    def _default(self) -> Any:
        if self.ptype.startswith("char"):
            return ""
        if self.ptype == "bool":
            return False
        if self.ptype == "double":
            return 0.0
        return 0

    def set(self, value:Any) -> None:
        """Set the value from a string (gridlabd conversion rules) or a
        Python value"""
        self.value = self.from_string(value) if isinstance(value,str) \
            else self._from_python(value)

    def _from_python(self, value:Any) -> Any: # pylint: disable=too-many-return-statements
        ptype = self.ptype
        if ptype.startswith("char"):
            return self._fit(str(value))
        if ptype == "bool":
            return bool(value)
        if ptype == "double":
            return float(value)
        if ptype.startswith("int"):
            return self._check_int(int(value))
        if ptype == "timestamp":
            if isinstance(value,datetime.datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=self.owner.timezone())
                return int(value.timestamp())
            return int(value)
        if ptype == "enumeration":
            return int(value)
        if ptype == "set":
            if isinstance(value,int):
                return value
            result = 0
            for item in value:
                result |= self._keyword(item)
            return result
        raise GlobalsError(f"{self.name}: cannot convert {value!r}") # pragma: no cover

    def _fit(self, text:str) -> str:
        size = PROPERTY_TYPES[self.ptype]
        if len(text) > size - 1:
            _logger.warning("%s: value truncated to %d characters", self.name, size-1)
            text = text[:size-1]
        return text

    def _check_int(self, value:int) -> int:
        bits = PROPERTY_TYPES[self.ptype]
        if not -(1 << (bits-1)) <= value < (1 << (bits-1)):
            raise GlobalsError(f"{self.name}: value {value} is out of range for {self.ptype}")
        return value

    def _keyword(self, key:str) -> int:
        if key not in self.keywords:
            raise GlobalsError(f"{self.name}: '{key}' is not a keyword of {self.name}")
        return self.keywords[key]

    def from_string(self, text:str) -> Any:
        """Convert a string to a value (per gridlabd `source/convert.cpp`)"""
        # pylint: disable=too-many-return-statements,too-many-branches
        ptype = self.ptype
        if ptype.startswith("char"):
            if text.startswith('"'):
                text = text[1:].split('"',1)[0]
            else:
                text = text.split("\n",1)[0]
            return self._fit(text)
        if ptype == "bool":
            match = re.match(r"[A-Za-z]+",text)
            if match:
                if match.group(0).upper() in ("TRUE","FALSE"):
                    return match.group(0).upper() == "TRUE"
                raise GlobalsError(f"{self.name}: '{text}' is not a valid bool")
            match = re.match(r"\s*([-+]?\d+)",text)
            if match:
                return int(match.group(1)) != 0
            raise GlobalsError(f"{self.name}: '{text}' is not a valid bool")
        if ptype.startswith("int"):
            match = re.match(r"\s*([-+]?\d+)",text)
            if not match:
                raise GlobalsError(f"{self.name}: '{text}' is not a valid {ptype}")
            return self._check_int(int(match.group(1)))
        if ptype == "double":
            return self._double_from_string(text)
        if ptype == "timestamp":
            return self.owner.timestamp_from_string(text)
        if ptype == "enumeration":
            if text in self.keywords:
                return self.keywords[text]
            if text.startswith("0x"):
                return int(text[2:],16)
            if text[:1].isdigit():
                return int(re.match(r"\d+",text).group(0))
            raise GlobalsError(f"{self.name}: '{text}' is not a keyword of {self.name}")
        if ptype == "set":
            if text[:2].lower() == "0x":
                return int(text[2:],16)
            if text[:1].isdigit():
                return int(re.match(r"\d+",text).group(0))
            return self._from_python([x for x in text.split("|") if x])
        raise GlobalsError(f"{self.name}: cannot convert '{text}'") # pragma: no cover

    def _double_from_string(self, text:str) -> float:
        if text == "":
            raise GlobalsError(f"{self.name}: empty value is not a valid double")
        body = text[1:] if text[:1] in "+-" else text
        if body[:3].upper() == "NAN":
            return math.nan
        match = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?inf(?:inity)?)\s*(\S*)",
            text, re.IGNORECASE)
        if not match:
            raise GlobalsError(f"{self.name}: '{text}' is not a valid double")
        value, unit = float(match.group(1)), match.group(2)
        if unit and unit != self.unit:
            if self.unit is None:
                raise GlobalsError(f"{self.name}: unit given to unitless property")
            raise GlobalsError(f"{self.name}: unit '{unit}' cannot be converted to '{self.unit}'")
        return value

    def to_string(self) -> str:
        """Convert the value to a string (per gridlabd `source/convert.cpp`)"""
        # pylint: disable=too-many-return-statements
        ptype, value = self.ptype, self.value
        if ptype.startswith("char"):
            return value
        if ptype == "bool":
            return "TRUE" if value else "FALSE"
        if ptype.startswith("int"):
            return str(value)
        if ptype == "double":
            if math.isnan(value):
                return "NAN"
            text = _c_format(self.owner.getvalue("double_format")) % value
            return f"{text} {self.unit}" if self.unit else text
        if ptype == "timestamp":
            return self.owner.timestamp_to_string(value)
        if ptype == "enumeration":
            for key, code in self.keywords.items():
                if code == value:
                    return key
            return str(value)
        if ptype == "set":
            return "|".join(self._set_keys())
        return str(value) # pragma: no cover

    def _set_keys(self) -> list[str]:
        value, keys = self.value, []
        for key, code in self.keywords.items():
            if (value and code and code & value == code) or (code == 0 and self.value == 0):
                value &= ~code
                keys.append(key)
        return keys

    def to_python(self) -> Any:
        """Get the value as a Python value: `str` for char and enumeration
        types, `set[str]` for set types, `int` for integer and timestamp
        types, `float` for doubles, and `bool` for booleans"""
        if self.ptype == "enumeration":
            return self.to_string()
        if self.ptype == "set":
            return set(self._set_keys())
        return self.value

class Globals: # pylint: disable=too-many-instance-attributes
    """Arras global variables

    See the module documentation for the description, pseudo-globals, and
    expansions.
    """

    object_finder: Callable[[str],list[str]]|None = None
    """Function called as `object_finder(criteria)` by `${FIND criteria}`;
    returns a list of object names"""

    object_last: Callable[[],str|None]|None = None
    """Function called as `object_last()` by `${object.last}`; returns the
    name of the last object created"""

    object_locator: Callable[[str],tuple[float,float]|None]|None = None
    """Function called as `object_locator(name)` by `${GEOCODE name}`;
    returns `(latitude,longitude)` of the object or `None`"""

    def __init__(self, values:dict[str,Any]|None=None, **kwargs):
        """Create the gridlabd global variables with their default values

        Arguments
        ---------
        - `values`: initial values that override the defaults
        - `**kwargs`: initial values that override the defaults

        Exceptions
        ----------
        - `GlobalsError`: an initial value names an undefined global or
          cannot be converted
        """
        self._vars: dict[str,Globalvar] = {}
        self._alias: dict[str,str] = {}
        self._names: list[str] = []
        self._rng = random.Random()
        self._run = None
        self._last_random: tuple[str,Any] = ("none",None)
        self._tmpfiles: dict[str,str] = {}
        self.python_namespace: dict[str,Any] = {}
        """Namespace in which `${PYTHON expression}` is evaluated"""

        for name, ptype, default, access, description, keywords in _defaults():
            if ptype == "alias":
                self._alias[name] = default
                self._names.append(name)
                continue
            self.create(name, default, ptype=ptype, access=access,
                description=description, keywords=keywords)
        for name in ("randomseed","randomstate"):
            self._vars[name].callback = self._random_init
        self._random_init(None,None)

        for name, value in {**(values or {}), **kwargs}.items():
            if not self.isdefined(name):
                raise GlobalsError(f"global '{name}' is not defined")
            self.set(name,value)

    #
    # Container protocol
    #
    def __contains__(self, name:str) -> bool:
        return self.isdefined(name)

    def __getitem__(self, name:str) -> Any:
        var = self.find(name)
        if var is None:
            raise KeyError(name)
        return var.to_python()

    def __setitem__(self, name:str, value:Any):
        self.set(name,value)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._names))

    def __len__(self) -> int:
        return len(self._names)

    def __repr__(self) -> str:
        return f"<Globals ({len(self)} variables)>"

    #
    # Core operations
    #
    def find(self, name:str) -> Globalvar|None:
        """Find a global variable

        Arguments
        ---------
        - `name`: variable name; the aliases `test` (of `debugger`),
          `website` (of `urlbase`), and `curl_options` (of `wget_options`)
          return the variable they share storage with, as in gridlabd

        Returns
        -------
        - `Globalvar`: the variable, or `None` if not defined
        """
        return self._vars.get(self._alias.get(name,name))

    def isdefined(self, name:str) -> bool:
        """Check whether a global variable is defined"""
        return self.find(name) is not None

    def create(self,
            name:str,
            value:Any=None,
            ptype:str|None=None,
            access:str="PUBLIC",
            description:str|None=None,
            keywords:dict[str,int]|None=None,
            unit:str|None=None,
            ) -> Globalvar:
        """Create a global variable

        Arguments
        ---------
        - `name`: variable name
        - `value`: initial value (string or Python value)
        - `ptype`: property type (see `PROPERTY_TYPES`); default is
          inferred from `value`: `bool`, `int32` for `int`, `double` for
          `float`, `timestamp` for `datetime`, else `char1024`
        - `access`: property access (see `ACCESS`)
        - `description`: description
        - `keywords`: keyword values for `enumeration` and `set` types
        - `unit`: unit of a `double`

        Returns
        -------
        - `Globalvar`: the new variable

        Exceptions
        ----------
        - `GlobalsError`: the name is already defined or invalid, or the
          value cannot be converted
        """
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        if not isinstance(name,str) or not name or len(name) > 63:
            raise GlobalsError(f"global name {name!r} is not valid")
        if self.isdefined(name):
            raise GlobalsError(f"global '{name}' is already defined")
        if ptype is None:
            if isinstance(value,bool):
                ptype = "bool"
            elif isinstance(value,int):
                ptype = "int32"
            elif isinstance(value,float):
                ptype = "double"
            elif isinstance(value,datetime.datetime):
                ptype = "timestamp"
            else:
                ptype = "char1024"
        var = Globalvar(self, name, ptype, value, access, description, keywords, unit)
        self._vars[name] = var
        self._names.append(name)
        return var

    def push(self, name:str, value:str) -> Globalvar:
        """Define a `char1024` global variable without checking for an
        existing one (gridlabd `global_push()`); an existing variable of the
        same name is replaced"""
        if name in self._vars:
            del self._vars[name]
            self._names.remove(name)
        return self.create(name,value,ptype="char1024")

    def set(self, name:str, value:Any=None) -> None:
        """Set a global variable

        Arguments
        ---------
        - `name`: variable name, or a definition `"NAME=VALUE"` when
          `value` is `None`
        - `value`: new value (string converted per gridlabd, or Python value)

        Exceptions
        ----------
        - `GlobalsError`: the definition is malformed, the variable is
          undefined while `strictnames` is true, or the value cannot be
          converted
        """
        if value is None:
            match = re.match(r"([^ \t=]{1,64})[ \t=]+([^\r\n]*)",name)
            if not match:
                raise GlobalsError(f"global variable definition '{name}' not formatted correctly")
            name, value = match.groups()
        var = self.find(name)
        if var is None:
            if self.getvalue("strictnames"):
                raise GlobalsError(f"strict naming prevents implicit creation of {name}")
            var = self.create(name,ptype="char1024")
        var.set(value)
        if var.callback:
            var.callback(var.name, var.to_string())

    def getvalue(self, name:str) -> Any:
        """Get the value of a global variable as a Python value

        Returns
        -------
        - see `Globalvar.to_python()`; `None` if not defined
        """
        var = self.find(name)
        return None if var is None else var.to_python()

    def get(self, name:str) -> str|None:
        """Get the string value of a global variable, pseudo-global, or
        expansion (gridlabd `global_getvar()`)

        Arguments
        ---------
        - `name`: variable name, pseudo-global, or expansion, without `${}`

        Returns
        -------
        - `str`: the value
        - `None`: the name is not defined or the spec is not valid
        """
        # pylint: disable=too-many-return-statements,too-many-branches
        if not isinstance(name,str):
            raise GlobalsError(f"global name {name!r} is not valid")

        simple = {
            "GUID": self._guid,
            "TODAY": lambda: self._now("%Y-%m-%d %H:%M:%S UTC"),
            "RUN": self._run_id,
            "URAND": lambda: f"{self._rng.uniform(0,1):f}",
            "NRAND": lambda: f"{self._rng.normalvariate(0,1):f}",
            {"WINDOWS":"WINDOWS","MACOSX":"APPLE"}.get(_platform(),"LINUX"): lambda: "1",
            "PYTHON": lambda: "1",
            "PID": lambda: str(os.getpid()),
        }
        if name in simple:
            return simple[name]()

        if name.startswith("SEQ_") and ":" in name:
            return self._seq(name)
        if name.startswith("SHELL "):
            return self._shell(name[6:])
        if name.startswith("RANGE") and name[5:6] in (" ",";",",",":"):
            return self._range(name)
        if name.startswith("PYTHON "):
            return repr(eval(name[7:], self.python_namespace)) # pylint: disable=eval-used
        for key, call in (("FINDFILE ",self._findfile), ("FILEPATH ",self._filepath),
                ("FILENAME ",self._filename), ("FILETYPE ",self._filetype),
                ("FIND ",self._findobj), ("GEOCODE ",self._geocode)):
            if name.startswith(key):
                return call(name[len(key):])
        if name == "TMPFILE":
            return self._tmpfile("".join(f"{self._rng.getrandbits(31):x}" for _ in range(4)))
        if name.startswith("TMPFILE "):
            return self._tmpfile(name[8:].lstrip())
        if name == "NOW":
            return self._now("%Y%m%d-%H%M%S")
        if name.startswith("NOW") and name[3].isspace():
            return self._now(name[4:])
        if name == "RANDOM":
            return self._random(None)
        if name.startswith("RANDOM") and name[6].isspace():
            return self._random(name[7:])

        found, value = self._expand(name)
        if found:
            return value

        match = re.match(r"([^.]+)\.(\S+)(?: ([^\n]*))?$",name)
        if match and match.group(1) == "object":
            return self._object(match.group(2), match.group(3) or "")

        var = self.find(name)
        return None if var is None else var.to_string()

    def expand(self, text:str) -> str:
        """Replace each `${...}` in `text` with its value (as the GLM loader does)

        Exceptions
        ----------
        - `GlobalsError`: a `${...}` has no value
        """
        def _replace(match):
            value = self.get(match.group(1))
            if value is None:
                raise GlobalsError(f"global '{match.group(1)}' is not defined")
            return value
        return re.sub(r"\$\{([^}]*)\}", _replace, text)

    def dump(self) -> list[str]:
        """List all global variables as `NAME=VALUE;` (gridlabd `global_dump()`)"""
        return [f"{name}={self.find(name).to_string()};" for name in self._names]

    def saveall(self) -> str:
        """GLM text that restores the global variables (gridlabd
        `global_saveall()`); empty when `glm_save_options` includes
        `NOGLOBALS`"""
        if self.find("glm_save_options").value & _KEYS["gso"]["NOGLOBALS"]:
            return ""
        lines = []
        for name in self._names:
            if "::" in name:
                continue
            value = self.find(name).to_string()
            lines.append(f"#ifdef {name}\n#define {name}={value}\n#else\n#set {name}={value}\n#endif\n")
        return "".join(lines)

    def cleanup(self) -> None:
        """Delete the temporary files created by `${TMPFILE}`"""
        for path in self._tmpfiles.values():
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        self._tmpfiles.clear()

    #
    # Timestamps
    #
    def timezone(self) -> datetime.tzinfo:
        """Time zone named by `timezone_locale` (UTC if not an IANA zone name)"""
        name = self.getvalue("timezone_locale")
        if name in ("","UTC","GMT"):
            return datetime.timezone.utc
        try:
            import zoneinfo # pylint: disable=import-outside-toplevel
            return zoneinfo.ZoneInfo(name)
        except Exception: # pylint: disable=broad-exception-caught
            _logger.warning("timezone_locale '%s' is not supported, using UTC", name)
            return datetime.timezone.utc

    def timestamp_to_string(self, ts:int) -> str:
        """Convert a timestamp to a string (gridlabd `convert_from_timestamp()`)"""
        # pylint: disable=too-many-return-statements
        if ts >= TS_NEVER:
            return "NEVER"
        if ts >= 365*DAY:
            dt = datetime.datetime.fromtimestamp(ts, self.timezone())
            fmt = self.getvalue("dateformat")
            if fmt == "ISO8601":
                offset = int(dt.utcoffset().total_seconds())
                sign = "+" if offset > 0 else "-"
                return dt.strftime(f"%Y-%m-%dT%H:%M:%S{sign}{abs(offset)//3600:02d}:{abs(offset)//60%60:02d}")
            tzname = dt.strftime("%Z")
            if fmt == "US":
                return dt.strftime(f"%m-%d-%Y %H:%M:%S {tzname}")
            if fmt == "EURO":
                return dt.strftime(f"%d-%m-%Y %H:%M:%S {tzname}")
            return dt.strftime(f"%Y-%m-%d %H:%M:%S {tzname}")
        if ts >= DAY:
            return f"{ts/DAY:f}d"
        if ts >= HOUR:
            return f"{ts/HOUR:f}h"
        if ts >= MINUTE:
            return f"{ts/MINUTE:f}m"
        if ts >= SECOND:
            return f"{ts/SECOND:f}s"
        if ts == 0:
            return "INIT"
        return str(ts)

    def timestamp_from_string(self, text:str) -> int:
        """Convert a string to a timestamp (gridlabd `convert_to_timestamp()`)

        Exceptions
        ----------
        - `GlobalsError`: the string is not a valid timestamp
        """
        # pylint: disable=too-many-return-statements,too-many-locals,invalid-name
        text = text.lstrip("'\"").strip()
        match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d+(?:\.\d*)?)(Z|[-+]\d{2}:?\d{2})$",text)
        if match:
            Y, m, d, H, M = (int(x) for x in match.groups()[:5])
            S, tz = float(match.group(6)), match.group(7)
            offset = 0 if tz == "Z" else (1 if tz[0] == "+" else -1) * (int(tz[1:3])*60 + int(tz[-2:])) * 60
            dt = datetime.datetime(Y,m,d,H,M,int(S),tzinfo=datetime.timezone.utc)
            return int(dt.timestamp()) - offset
        patterns = [(r"(\d+)-(\d+)-(\d+)", "YMD")]
        patterns.append((r"(\d+)/(\d+)/(\d+)", {"ISO":"YMD","US":"MDY","EURO":"DMY"}.get(self.getvalue("dateformat"),"YMD")))
        for date, order in patterns:
            match = re.match(date + r"(?: (\d+):(\d+):(\d+))?(?: ([-+:A-Za-z0-9/_]+))?$", text)
            if match:
                parts = dict(zip(order,(int(x) for x in match.groups()[:3])))
                H, M, S = (int(x or 0) for x in match.groups()[3:6])
                tz = self._tzinfo(match.group(7))
                try:
                    dt = datetime.datetime(parts["Y"],parts["M"],parts["D"],H,M,S,tzinfo=tz)
                except ValueError as err:
                    raise GlobalsError(f"'{text}' is not a valid timestamp ({err})") from err
                return int(dt.timestamp())
        if text == "INIT":
            return TS_ZERO
        if text == "NEVER":
            return TS_NEVER
        if text == "NOW":
            return self._vars["clock"].value
        match = re.match(r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([A-Za-z]{0,3})$",text)
        if match:
            scale = {"":1,"s":SECOND,"m":MINUTE,"h":HOUR,"d":DAY,"w":7*DAY}.get(match.group(2).lower())
            if scale is None:
                raise GlobalsError(f"'{text}' is not a valid timestamp")
            base = self._vars["clock"].value if text[0] in "+-" else 0
            return base + int(float(match.group(1))*scale + 0.5)
        raise GlobalsError(f"'{text}' is not a valid timestamp")

    def _tzinfo(self, name:str|None) -> datetime.tzinfo:
        if name is None:
            return self.timezone()
        if name in ("UTC","GMT","Z"):
            return datetime.timezone.utc
        try:
            import zoneinfo # pylint: disable=import-outside-toplevel
            return zoneinfo.ZoneInfo(name)
        except Exception as err: # pylint: disable=broad-exception-caught
            raise GlobalsError(f"timezone '{name}' is not supported") from err

    #
    # Pseudo-globals
    #
    def _random_init(self, name, value): # pylint: disable=unused-argument
        seed = self._vars["randomseed"].value
        self._rng.seed(seed if seed != 0 else None)

    def _guid(self) -> str:
        r = [self._rng.getrandbits(16) for _ in range(8)]
        return f"{r[0]:04x}{r[1]:04x}-{r[2]:04x}-4{r[3]&0x0fff:03x}-{r[4]:04x}-{r[5]:04x}{r[6]:04x}{r[7]:04x}"

    def _run_id(self) -> str:
        if self._run is None:
            self._run = self._guid()
        return self._run

    @staticmethod
    def _now(fmt:str) -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime(fmt)

    def _seq(self, name:str) -> str|None:
        match = re.match(r"([^:]{1,63}):(\S{1,63})",name)
        if not match:
            _logger.error("sequence spec '%s' is invalid",name)
            return None
        seq, opt = match.groups()
        if opt == "INIT":
            if self.isdefined(seq):
                _logger.warning("sequence '%s' is already initialized",seq)
                return None
            self.create(seq,0,ptype="int32")
            return self.get(seq)
        if opt == "INC":
            var = self.find(seq)
            if var is None or var.ptype != "int32":
                _logger.error("sequence '%s' is missing or not an int32 variable",seq)
                return None
            var.value = _wrap(var.value+1,32)
            return var.to_string()
        _logger.error("sequence spec '%s' is invalid",opt)
        return None

    @staticmethod
    def _shell(command:str) -> str:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        if result.stderr:
            _logger.error("%s",result.stderr.strip())
        return result.stdout.replace("\n"," ")

    @staticmethod
    def _range(spec:str) -> str:
        delim = spec[5]
        values = [0.0, 1.0, 1.0]
        for n, item in enumerate(spec[6:].split(",")[:3]):
            try:
                values[n] = float(item)
            except ValueError:
                break
        start, stop, step = values
        if step <= 0:
            raise GlobalsError(f"RANGE step {step:g} must be positive")
        result, value = [], start
        while value <= stop:
            result.append(f"{value:g}")
            value += step
        return delim.join(result)

    def _findfile(self, spec:str) -> str:
        if os.path.isabs(spec):
            return spec if os.path.exists(spec) else ""
        for folder in folders.search_path(self.getvalue("workdir") or "."):
            path = os.path.join(folder,spec)
            if os.path.exists(path):
                return os.path.abspath(path)
        return ""

    def _filespec(self, spec:str) -> str|None:
        if not spec.startswith("$"):
            return spec
        value = self.get(spec[1:])
        if value is None:
            _logger.error("global '%s' is not found",spec[1:])
        return value

    def _filename(self, spec:str) -> str|None:
        var = self._filespec(spec)
        if var is None:
            return None
        name = var.rsplit("/",1)[-1]
        return name.rsplit(".",1)[0] if "." in name else name

    def _filepath(self, spec:str) -> str|None:
        var = self._filespec(spec)
        if var is None:
            return None
        return var.rsplit("/",1)[0] if "/" in var else "."

    def _filetype(self, spec:str) -> str|None:
        var = self._filespec(spec)
        if var is None:
            return None
        return var.rsplit(".",1)[1] if "." in var else ""

    def _findobj(self, criteria:str) -> str:
        finder = self.object_finder
        return "" if finder is None else " ".join(finder(criteria))

    def _object(self, kind:str, arg:str) -> str|None: # pylint: disable=unused-argument
        last = self.object_last
        return last() if kind == "last" and last is not None else None # pylint: disable=not-callable

    def _tmpfile(self, tag:str) -> str:
        if tag not in self._tmpfiles:
            ext, name = tag.split(":",1) if ":" in tag else ("tmp",tag)
            tmp = os.getenv("TMPDIR") or os.getenv("TMP") or "/tmp"
            sep = "" if tmp.endswith("/") else "/"
            path = f"{tmp}{sep}gridlabd_tmp_{self.get('hostname')}_{os.getpid()}_{name}.{ext}"
            try:
                os.close(os.open(path, os.O_EXCL|os.O_CREAT|os.O_RDWR))
            except OSError:
                _logger.warning("unable to create temporary file '%s'",path)
            self._tmpfiles[tag] = path
        return self._tmpfiles[tag]

    def _random(self, spec:str|None) -> str|None:
        # pylint: disable=too-many-return-statements
        if spec is None:
            value = self._rng.random()
            self._last_random = ("double",value)
            return f"{value:g}"
        if spec == "last":
            kind, value = self._last_random
            if kind == "none":
                return str(self._vars["randomseed"].value)
            return f"{value:g}" if kind == "double" else str(value)
        match = re.match(r"(\d+)",spec)
        if match and 0 < int(match.group(1)) <= 64:
            value = self._rng.getrandbits(int(match.group(1)))
            self._last_random = ("integer",value)
            return str(value)
        match = re.match(r"([a-z]{1,63})\(([^)]{1,1023})\)",spec)
        if not match:
            _logger.error("random spec '%s' is invalid",spec)
            return None
        try:
            args = [float(x) for x in match.group(2).split(",")]
            value = self._distribution(match.group(1),args)
        except (ValueError, ZeroDivisionError) as err:
            _logger.error("random spec '%s' is invalid (%s)",spec,err)
            return None
        self._last_random = ("double",value)
        return f"{value:g}"

    def _distribution(self, name:str, args:list[float]) -> float:
        """Random value from a gridlabd distribution (`source/random.cpp`)"""
        # pylint: disable=too-many-return-statements,too-many-branches
        rng = self._rng
        nargs = {"degenerate":1, "uniform":2, "normal":2, "bernoulli":1,
            "pareto":2, "lognormal":2, "exponential":1, "rayleigh":1,
            "weibull":2, "beta":2, "triangle":2}
        if name in nargs and len(args) != nargs[name]:
            raise ValueError(f"{name} expects {nargs[name]} arguments")
        if name == "degenerate":
            return args[0]
        if name == "uniform":
            return rng.uniform(*args)
        if name == "normal":
            return rng.normalvariate(*args)
        if name == "bernoulli":
            return 1.0 if args[0] >= rng.random() else 0.0
        if name == "pareto":
            if args[1] <= 0:
                raise ValueError("pareto k must be positive")
            return args[0] * (1 - rng.random()) ** (-1/args[1])
        if name == "lognormal":
            return math.exp(rng.normalvariate(0,1)*args[1]+args[0])
        if name == "exponential":
            if args[0] <= 0:
                raise ValueError("exponential lambda must be positive")
            return rng.expovariate(args[0])
        if name == "rayleigh":
            return args[0] * math.sqrt(-2*math.log(1-rng.random()))
        if name == "weibull":
            if args[1] <= 0:
                raise ValueError("weibull k must be positive")
            return args[0] * (-math.log(1-rng.random())) ** (1/args[1])
        if name == "gamma":
            if len(args) not in (1,2):
                raise ValueError("gamma expects 1 or 2 arguments")
            return rng.gammavariate(args[0], args[1] if len(args) > 1 else 1.0)
        if name == "beta":
            return rng.betavariate(*args)
        if name == "triangle":
            return (rng.random()+rng.random())*(args[1]-args[0])/2 + args[0]
        if name == "sampled":
            return rng.choice(args)
        raise ValueError(f"distribution '{name}' is not valid")

    def _geocode(self, spec:str) -> str:
        match = re.match(r"([-+]?[\d.]+(?:[eE][-+]?\d+)?),([-+]?[\d.]+(?:[eE][-+]?\d+)?)(?:#(\d+))?$",spec)
        if match:
            return geocode_encode(float(match.group(1)),float(match.group(2)),int(match.group(3) or 5))
        match = re.match(r"([^#]{1,63})(?:#(\d+))?$",spec)
        locator = self.object_locator
        if match and locator is not None:
            location = locator(match.group(1)) # pylint: disable=not-callable
            if location is not None:
                lat, lon = location
                if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                    return geocode_encode(lat,lon,int(match.group(2) or 5))
                _logger.warning("${GEOCODE %s}: object location is not valid",spec)
                return ""
        result = geocode_decode(spec)
        if result is not None:
            return result
        _logger.warning("${GEOCODE %s}: geocode spec is not valid",spec)
        return ""

    #
    # Expansions (gridlabd GldGlobals::parameter_expansion)
    #
    _NAME = r"[^-+*/%&|^~?=!<>:]{1,63}"

    def _int32(self, name:str) -> Globalvar|None:
        var = self.find(name)
        return var if var is not None and var.ptype == "int32" else None

    def _expand(self, spec:str) -> tuple[bool,str|None]:
        """Evaluate an expansion; returns `(matched, value)`"""
        # pylint: disable=too-many-return-statements,too-many-branches,too-many-locals,too-many-statements
        match = re.match(r"([^:]{1,63}):-([^}]{1,1023})$",spec)
        if match:
            value = self.get(match.group(1))
            return True, match.group(2) if value is None else value

        match = re.match(r"([^:]{1,63}):=([^}]{1,1023})$",spec)
        if match:
            name, value = match.groups()
            if not self.isdefined(name):
                self.create(name,value,ptype="char1024")
            return True, self.get(name)

        match = re.match(r"([^:]{1,63}):\+([^}]{1,1023})$",spec)
        if match:
            return True, match.group(2) if self.isdefined(match.group(1)) else ""

        match = re.match(r"([^:]{1,63}):([-+]?\d+)(?::([-+]?\d+))?$",spec)
        if match:
            value = self.get(match.group(1))
            if value is None:
                return True, None
            offset = max(0,int(match.group(2)))
            if match.group(3) is None:
                return True, value[offset:]
            return True, value[offset:offset+max(0,int(match.group(3)))]

        match = re.match(rf"({self._NAME})([-+*/%&|^])=(~?)([-+]?\d+)$",spec)
        if match:
            var = self._int32(match.group(1))
            if var is not None:
                number = int(match.group(4))
                number = ~number if match.group(3) else number
                var.value = self._arith(var.value,match.group(2),number)
                return True, str(var.value)

        match = re.match(rf"(~?)({self._NAME})([-+*/%&|^])(~?)([-+]?\d+)$",spec)
        if match:
            var = self._int32(match.group(2))
            if var is not None:
                left = ~var.value if match.group(1) else var.value
                number = int(match.group(5))
                number = ~number if match.group(4) else number
                return True, str(self._arith(left,match.group(3),number))

        match = re.match(r"([^/]{1,63})(//?)([^/]{1,63})(?:/([^}]{0,63}))?$",spec)
        if match:
            name, op, pattern, string = match.groups()
            value = self.get(name)
            if value is None:
                return True, None
            return True, value.replace(pattern, string or "", -1 if op == "//" else 1)

        match = re.match(r"(\+\+|--)(\S{1,63})$",spec)
        if match:
            var = self._int32(match.group(2))
            if var is None:
                return True, None
            var.value = _wrap(var.value + (1 if match.group(1) == "++" else -1),32)
            return True, str(var.value)

        match = re.match(r"([^-+]{1,63})(\+\+|--)$",spec)
        if match:
            var = self._int32(match.group(1))
            if var is not None:
                old = var.value
                var.value = _wrap(old + (1 if match.group(2) == "++" else -1),32)
                return True, str(old)

        match = re.match(rf"({self._NAME})(==|!=|<>|<=|>=|<|>|&|\|~)([-+]?\d+)"
            r"(?:\?([^:]{0,1023})(?::(\S{0,1023}))?)?$",spec)
        if match:
            var = self._int32(match.group(1))
            if var is not None:
                yes = "1" if match.group(4) is None else match.group(4)
                no = "0" if match.group(5) is None else match.group(5)
                a, b = var.value, int(match.group(3))
                test = {"==": a == b, "!=": a != b, "<>": a != b, "<=": a <= b,
                    ">=": a >= b, "<": a < b, ">": a > b, "&": bool(a & b),
                    "|~": bool(a | ~b)}[match.group(2)]
                return True, yes if test else no

        match = re.match(r"([A-Za-z0-9_:.]{1,63})=([-+]?\d+)$",spec)
        if match:
            name, number = match.group(1), int(match.group(2))
            if self.isdefined(name):
                self.find(name).set(number)
            else:
                self.create(name,number,ptype="int32")
            return True, str(number)

        match = re.match(r"([A-Za-z0-9_:.]{1,63})=([^\n]+)$",spec)
        if match:
            name, string = match.groups()
            if self.isdefined(name):
                self.set(name,string)
            else:
                self.create(name,string,ptype="char1024")
            return True, string

        return False, None

    @staticmethod
    def _arith(a:int, op:str, b:int) -> int:
        result = {
            "+": lambda: a + b,
            "-": lambda: a - b,
            "*": lambda: a * b,
            "/": lambda: _cdiv(a,b),
            "%": lambda: _cmod(a,b),
            "&": lambda: a & b,
            "|": lambda: a | b,
            "^": lambda: a ^ b,
        }[op]()
        return _wrap(result,32)

_GEOHASH = "0123456789bcdefghjkmnpqrstuvwxyz"

def geocode_encode(lat:float, lon:float, resolution:int=5) -> str:
    """Encode a latitude and longitude as a geohash (gridlabd `geocode_encode()`)

    Arguments
    ---------
    - `lat`: latitude in degrees
    - `lon`: longitude in degrees
    - `resolution`: number of geohash characters (5 is about 2.4 km)
    """
    lat_interval, lon_interval = [-90.0,90.0], [-180.0,180.0]
    result, bits, bit, ch, even = [], (16,8,4,2,1), 0, 0, True
    while len(result) < resolution:
        interval, value = (lon_interval, lon) if even else (lat_interval, lat)
        mid = (interval[0]+interval[1])/2
        if value > mid:
            ch |= bits[bit]
            interval[0] = mid
        else:
            interval[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            result.append(_GEOHASH[ch])
            bit, ch = 0, 0
    return "".join(result)

def geocode_decode(code:str) -> str|None:
    """Decode a geohash (gridlabd `geocode_decode()`)

    Arguments
    ---------
    - `code`: geohash, optionally followed by `.lat` or `.lon`

    Returns
    -------
    - `str`: `"LAT,LON"`, `"LAT"`, or `"LON"` with as many decimals as the
      geohash resolves
    - `None`: the code is not a valid geohash
    """
    code, _, spec = code.partition(".")
    if not code:
        return None
    lat_err, lon_err = 90.0, 180.0
    lat_interval, lon_interval = [-90.0,90.0], [-180.0,180.0]
    is_even = True
    for c in code.lower():
        cd = _GEOHASH.find(c)
        if cd < 0:
            return None
        for mask in (16,8,4,2,1):
            if is_even:
                lon_err /= 2
                lon_interval[0 if cd & mask else 1] = (lon_interval[0]+lon_interval[1])/2
            else:
                lat_err /= 2
                lat_interval[0 if cd & mask else 1] = (lat_interval[0]+lat_interval[1])/2
            is_even = not is_even
    res = -int(math.log10(lat_err))
    if res < 0: # C printf treats a negative precision as omitted
        res = 6
    lat = (lat_interval[0]+lat_interval[1])/2
    lon = (lon_interval[0]+lon_interval[1])/2
    if spec == "":
        return f"{lat:.{res}f},{lon:.{res}f}"
    if spec == "lat":
        return f"{lat:.{res}f}"
    if spec == "lon":
        return f"{lon:.{res}f}"
    return None
