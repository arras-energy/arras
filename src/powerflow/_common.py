# pylint: disable=line-too-long
"""@private Helpers shared by the powerflow classes

Constants (phases, flags, bus types), runner access and messages (gridlabd
`gl_error()`, `gld_object::error()`, ...), and the state that the module
and each object keep between handler calls. Property values are read and
written with the helpers of `pypower._common`, which are not specific to
the `pypower` module.
"""

import re
import weakref
from typing import Any

from arras.exceptions import ArrasException
from arras import exitcodes

# pylint: disable=unused-import
from pypower._common import (get_double, get_complex, get_text, set_double,
    set_complex, set_int, set_text, fmt, fmt_complex, text_to_complex, text_to_double)
from pypower._common import get_int as _get_int

MODULE = "powerflow"
"""Module name"""

TS_NEVER = (1 << 63) - 1
"""Timestamp that means no event"""

TS_INVALID = -1
"""Timestamp that reports a failure"""

TRL_PROVEN = 9
"""Technology readiness level `TRL_PROVEN`"""

#
# Phases (powerflow_object.h)
#
NO_PHASE = 0x0000
PHASE_A = 0x0001
PHASE_B = 0x0002
PHASE_C = 0x0004
PHASE_ABC = 0x0007
PHASE_N = 0x0008
PHASE_S1 = 0x0010
PHASE_S2 = 0x0020
PHASE_SN = 0x0040
PHASE_S = 0x0070
GROUND = 0x0080
PHASE_D = 0x0100

PHASE_BITS = (PHASE_A, PHASE_B, PHASE_C)
"""Phase bits by phase index (A, B, C)"""

PHASE_NAMES = ("A", "B", "C")
"""Phase letters by phase index"""

#
# Node bus types and flags (node.h, powerflow_object.h)
#
PQ, PV, SWING, SWING_PQ = range(4)
"""`node.bustype` values"""

NF_HASSOURCE = 0x0001
NF_ISSOURCE = 0x0002

#
# Link status and flow directions (powerflow.h, link.h)
#
LS_OPEN, LS_CLOSED, LS_INIT = range(3)
"""`link.status` values"""

FD_UNKNOWN = 0x000
FD_A_NORMAL, FD_A_REVERSE, FD_A_NONE = 0x001, 0x002, 0x003
FD_B_NORMAL, FD_B_REVERSE, FD_B_NONE = 0x010, 0x020, 0x030
FD_C_NORMAL, FD_C_REVERSE, FD_C_NONE = 0x100, 0x200, 0x300

ROUNDOFF = 1e-6
"""gridlabd `ROUNDOFF`: numerical accuracy for zero in float comparisons"""

#
# Solver methods (powerflow.h; FD_XB, FD_BX, and DC are arras additions)
#
SM_FBS, SM_GS, SM_NR, SM_FD_XB, SM_FD_BX, SM_DC = range(6)
"""`powerflow::solver_method` values"""

SOLVER_METHODS = {"FBS": SM_FBS, "GS": SM_GS, "NR": SM_NR, "FD_XB": SM_FD_XB, "FD_BX": SM_FD_BX, "DC": SM_DC}
"""Keywords of `powerflow::solver_method` (gridlabd `FBS`, `GS`, `NR`; `FD_XB`, `FD_BX`, `DC` added)"""

CEH_FATAL, CEH_IGNORE, CEH_COLLAPSE = range(3)
"""`powerflow::convergence_error_handling` values"""

#
# Message flags
#
OF_QUIET = 0x00010000
OF_WARNING = 0x00020000
OF_DEBUG = 0x00040000
OF_VERBOSE = 0x00080000

MESSAGE_FLAGS = {"QUIET": OF_QUIET, "WARNING": OF_WARNING, "DEBUG": OF_DEBUG, "VERBOSE": OF_VERBOSE}
"""Keywords of the `powerflow::message_flags` global (gridlabd `INIT_MMF()`)"""

OBJECT_FLAGS = {"NONE": 0, "HASPLC": 0x1, "LOCKED": 0x2, "RERANKED": 0x4000, "RECALC": 0x8,
    "DELTAMODE": 0x40, **MESSAGE_FLAGS}
"""Keywords of the object `flags` header (gridlabd `oflags[]`)"""

class PowerflowError(ArrasException):
    """Powerflow module error"""

BEHAVIORS: dict[str,Any] = {}
"""Behavior class of each powerflow class name (filled by the package and
by the classes ported later)"""

#
# Runner and messages
#
def runner() -> Any:
    """Runner of the calling thread

    Exceptions
    ----------
    - `PowerflowError`: no simulation is running in the calling thread
    """
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        raise PowerflowError("powerflow handlers run only during an arras.runner.Runner simulation")
    return current

def gl_error(message:str) -> None:
    """`gl_error()`: an error line; the run goes on but ends with exit code
    `RUNERR`, as gridlabd's `output_error()` sets it"""
    current = runner()
    current.error(message)
    current.setexitcode(exitcodes.RUNERR)

def gl_warning(message:str) -> None:
    """`gl_warning()`: a warning line"""
    runner().warning(message)

def gl_verbose(message:str) -> None:
    """`gl_verbose()`: a verbose line"""
    runner().verbose(message)

def _parse_flags(text:Any, keywords:dict[str,int]) -> int:
    if text in (None, ""):
        return 0
    if isinstance(text, (set, frozenset)):
        return sum(keywords.get(x, 0) for x in text)
    text = str(text).strip()
    if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", text):
        return int(text, 0)
    bits = 0
    for key in text.split("|"):
        bits |= keywords.get(key.strip(), 0)
    return bits

def object_flags(model:Any, name:str) -> int:
    """Flag bits of an object: its `flags` header ORed with the
    `powerflow::message_flags` global"""
    flags = _parse_flags(model.objects[name].get("flags"), OBJECT_FLAGS)
    if model.globals.isdefined(f"{MODULE}::message_flags"):
        flags |= _parse_flags(model.globals.get(f"{MODULE}::message_flags"), MESSAGE_FLAGS)
    return flags

class Messages:
    """`gld_object` messages of one object: `error()`, `warning()`,
    `verbose()` write `NAME: message` as gridlabd does, following the
    object's flags"""

    def __init__(self, model:Any, name:str):
        self.model = model
        self.name = name

    def error(self, message:str) -> None:
        """`gld_object::error()`: unless the object is `QUIET`"""
        if not object_flags(self.model, self.name) & OF_QUIET:
            gl_error(f"{self.name}: {message}")

    def warning(self, message:str) -> None:
        """`gld_object::warning()`: unless the object has the `WARNING`
        flag"""
        if not object_flags(self.model, self.name) & OF_WARNING:
            gl_warning(f"{self.name}: {message}")

    def verbose(self, message:str) -> None:
        """`gld_object::verbose()`: only for `VERBOSE` objects"""
        if object_flags(self.model, self.name) & OF_VERBOSE:
            gl_verbose(f"{self.name}: {message}")

def msg(model:Any, name:str) -> Messages:
    """Messages of an object"""
    return Messages(model, name)

#
# Module and object state
#
_STATE: "weakref.WeakKeyDictionary[Any,Any]" = weakref.WeakKeyDictionary()

def module_state(model:Any) -> Any:
    """State of the module for a model (`powerflow._module.ModuleState`),
    created on first use and dropped with the model"""
    state = _STATE.get(model)
    if state is None:
        from ._module import ModuleState # pylint: disable=import-outside-toplevel
        state = ModuleState(model)
        _STATE[model] = state
    return state

def object_state(model:Any, name:str) -> dict[str,Any]:
    """State of an object (a `dict`), created on first use"""
    objects = module_state(model).objects
    if name not in objects:
        objects[name] = {}
    return objects[name]

#
# Classes and objects
#
def isa(model:Any, name:str|None, cname:str) -> bool:
    """`True` when the object's class is the powerflow class `cname` or
    inherits from it (gridlabd `gl_object_isa(obj, cname, "powerflow")`):
    through the class's parents, or through the behavior classes, since a
    C++ class can answer `isa()` for a class it does not inherit
    publications from (`triplex_line_configuration` is a
    `line_configuration`)"""
    if name is None or name not in model.objects:
        return False
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name == cname and oclass.module == MODULE:
            return True
        if oclass.module == MODULE and oclass.name in BEHAVIORS and cname in BEHAVIORS \
                and issubclass(BEHAVIORS[oclass.name], BEHAVIORS[cname]) and cname not in ("powerflow_library",):
            return True
        oclass = getattr(oclass, "parent", None)
    return False

def objects_of(model:Any, cname:str) -> list[str]:
    """Names of the objects of a powerflow class (or classes that inherit
    from it), in creation order"""
    return [name for name in model.objects if isa(model, name, cname)]

def ref(model:Any, name:str, prop:str) -> str|None:
    """Name of the object an `object` property (or the `parent` header)
    refers to, or `None`"""
    value = model.objects[name].get(prop) if prop == "parent" else model.get_property(name, prop)
    if value in (None, "", "NULL"):
        return None
    value = str(value).strip().strip('"')
    return value if value in model.objects else None

def g(model:Any, name:str) -> Any:
    """Value of global `powerflow::NAME`: numbers for `double`, `int`,
    `bool`, and `enumeration` (the keyword's value), text for the others"""
    gname = f"{MODULE}::{name}"
    var = model.globals.find(gname)
    if var is None:
        return None
    value = model.globals.getvalue(gname)
    keywords = getattr(var, "keywords", None) or {}
    if var.ptype == "enumeration" and isinstance(value, str):
        return keywords.get(value, 0)
    if var.ptype == "set" and isinstance(value, (set, frozenset)):
        return sum(keywords.get(x, 0) for x in value)
    return value

def get_int(model:Any, name:str, prop:str) -> int:
    """Value of an integer, `bool`, `enumeration`, or `set` property; a
    `set` whose keywords are all one character may be written without
    separators (`ABCN`), as gridlabd reads and writes phases"""
    value = _get_int(model, name, prop)
    if value:
        return value
    spec = model.objects[name].oclass.find_property(prop)
    if spec is None or spec.ptype != "set":
        return value
    text = str(model.get_property(name, prop) or "").strip()
    keys = spec.keywords or {}
    if text and "|" not in text and all(len(key) == 1 for key in keys) and all(c in keys for c in text):
        bits = 0
        for c in text:
            bits |= keys[c]
        return bits
    return value

def set_flags(model:Any, name:str, prop:str, value:int) -> None:
    """Set a `set` property to bits, written with its keywords as
    gridlabd's `convert_from_set()` writes them: in keyword order, without
    separators when every keyword is one character, else joined by `|`"""
    spec = model.objects[name].oclass.find_property(prop)
    if int(value) == 0:
        zero = [key for key, bits in (spec.keywords or {}).items() if bits == 0]
        model.objects[name][prop] = zero[0] if zero else "0"
        return
    items = [(key, bits) for key, bits in (spec.keywords or {}).items() if bits]
    names, rest = [], int(value)
    for key, bits in items:
        if rest & bits == bits:
            names.append(key)
            rest &= ~bits
    if rest or not names:
        model.objects[name][prop] = str(int(value))
        return
    sep = "" if all(len(key) == 1 for key, _ in items) else "|"
    model.objects[name][prop] = sep.join(names)

def phase_list(phases:int) -> list[int]:
    """Indexes (0, 1, 2) of the phases A, B, C present in a phase set"""
    return [k for k, bit in enumerate(PHASE_BITS) if phases & bit]
