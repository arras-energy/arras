# pylint: disable=line-too-long
"""@private Helpers shared by the generators classes

Constants, runner access and messages (gridlabd `gl_error()`,
`gld_object::error()`, ...), C arithmetic, access to the properties of
other objects, and the state that each object keeps between its event
handlers. Property values are read and written with the helpers of
`pypower._common`, which are not specific to the `pypower` module.
"""

import math
import re
import weakref
from typing import Any

from arras.exceptions import ArrasException
from arras import exitcodes

# pylint: disable=unused-import
from pypower._common import (get_double, get_complex, get_text, set_double,
    set_complex, set_int, set_text, fmt, fmt_complex, text_to_double, notation, fdiv, csqrt)
from pypower._common import get_int as _get_int

MODULE = "generators"
"""Module name"""

TS_NEVER = (1 << 63) - 1
"""Timestamp printed as `NEVER`"""

TS_INVALID = -1
"""Timestamp that reports a failure"""

INIT_DEFER = 2
"""`init()` result that defers the initialization"""

TRL_PROOF = 4
"""Technology readiness level of `solar` and `inverter` (gridlabd `TRL_PROOF`)"""

PI = 3.1415926535897932384626433832795
"""gridlabd `PI`"""

PHASE_A = 0x0001
PHASE_B = 0x0002
PHASE_C = 0x0004
PHASE_N = 0x0008
PHASE_S = 0x0070
PHASE_S1 = 0x0010

UNKNOWN = 0
"""gridlabd `UNKNOWN` (`generators.h`)"""

OFFLINE = 1
ONLINE = 2
"""`generator_status` values"""

CONSTANT_V = 1
CONSTANT_PQ = 2
CONSTANT_PF = 4
SUPPLY_DRIVEN = 5
"""`generator_mode` values"""

OF_QUIET = 0x00010000
OF_WARNING = 0x00020000
OF_DEBUG = 0x00040000
OF_VERBOSE = 0x00080000
OF_DELTAMODE = 0x00000040

MESSAGE_FLAGS = {"QUIET": OF_QUIET, "WARNING": OF_WARNING, "DEBUG": OF_DEBUG, "VERBOSE": OF_VERBOSE}
"""Keywords of the `generators::message_flags` global (gridlabd `INIT_MMF()`)"""

OBJECT_FLAGS = {"NONE": 0, "HASPLC": 0x1, "LOCKED": 0x2, "RERANKED": 0x4000, "RECALC": 0x8,
    "DELTAMODE": OF_DELTAMODE, **MESSAGE_FLAGS}
"""Keywords of the object `flags` header (gridlabd `oflags[]`)"""

BEHAVIORS: dict[str,Any] = {}
"""Behavior class of each generators class name (filled by the package)"""

class GeneratorsError(ArrasException):
    """Generators module error"""

class Throw(Exception):
    """gridlabd `GL_THROW()`/`throw`: caught by the handler, which writes
    the `INIT_CATCHALL()` or `SYNC_CATCHALL()` message"""

def get_int(model:Any, name:str, prop_:str) -> int:
    """Value of an integer, `bool`, `enumeration`, or `set` property; a
    `set` whose keywords are all one character may be written without
    separators (`ABCN`), as gridlabd reads and writes phases"""
    value = _get_int(model, name, prop_)
    if value:
        return value
    spec = model.objects[name].oclass.find_property(prop_)
    if spec is None or spec.ptype != "set":
        return value
    text = str(model.get_property(name, prop_) or "").strip()
    keys = spec.keywords or {}
    if text and "|" not in text and all(len(key) == 1 for key in keys) and all(c in keys for c in text):
        bits = 0
        for c in text:
            bits |= keys[c]
        return bits
    return value

def keywords(*items:tuple[str,int]) -> dict[str,int]:
    """Keywords in the order gridlabd lists them (reverse publication
    order); `items` are `(name, value)` in publication order"""
    return dict(reversed(items))

def prop(description:str|None=None, default:str|None=None, flags:str|None=None, **kwargs:Any) -> dict[str,Any]:
    """`Class.publish()` options"""
    options: dict[str,Any] = dict(kwargs)
    if description is not None:
        options["description"] = description
    if default is not None:
        options["default"] = default
    if flags is not None:
        options["flags"] = flags
    return options

def register(cls:Any, module:Any) -> Any:
    """Register a behavior class's gridlabd class for `module` (an
    `arras.module.Module`) with its properties and event handlers"""
    oclass = module.register_class(cls.NAME, passconfig=cls.PASSCONFIG)
    oclass.trl = TRL_PROOF
    for name, ptype, options in cls.PROPERTIES:
        oclass.publish(name, ptype, **options)
    for event in cls.EVENTS:
        oclass.set_event(event, f"python:{MODULE}.{event}")
    return oclass

#
# Runner and messages
#
def runner() -> Any:
    """Runner of the calling thread

    Exceptions
    ----------
    - `GeneratorsError`: no simulation is running in the calling thread
    """
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        raise GeneratorsError("generators handlers run only during an arras.runner.Runner simulation")
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

def parse_flags(text:Any, table:dict[str,int]) -> int:
    """Bits of a set value (`|`-separated keywords or an integer)"""
    if text in (None, ""):
        return 0
    text = str(text).strip()
    if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", text):
        return int(text, 0)
    bits = 0
    for key in text.split("|"):
        bits |= table.get(key.strip(), 0)
    return bits

def object_flags(model:Any, name:str) -> int:
    """Flag bits of an object: its `flags` header ORed with the
    `generators::message_flags` global"""
    flags = parse_flags(model.objects[name].get("flags"), OBJECT_FLAGS)
    if model.globals.isdefined(f"{MODULE}::message_flags"):
        flags |= parse_flags(model.globals.get(f"{MODULE}::message_flags"), MESSAGE_FLAGS)
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
        """`gld_object::warning()`: unless the object has the `WARNING` flag"""
        if not object_flags(self.model, self.name) & OF_WARNING:
            gl_warning(f"{self.name}: {message}")

    def verbose(self, message:str) -> None:
        """`gld_object::verbose()`: only for `VERBOSE` objects"""
        if object_flags(self.model, self.name) & OF_VERBOSE:
            gl_verbose(f"{self.name}: {message}")

def msg(model:Any, name:str) -> Messages:
    """Messages of an object"""
    return Messages(model, name)

def header_name(model:Any, name:str) -> str:
    """`obj->name` as the C++ code prints it with `%s` (or the fallback of
    `obj->name?obj->name:"unnamed"`): `None` for an unnamed object"""
    obj = model.objects[name]
    return None if name == f"{obj.oclass.name}:{obj.id}" else name # type: ignore[return-value]

def label(model:Any, name:str, unnamed:str="unnamed") -> str:
    """`obj->name?obj->name:"unnamed"`"""
    found = header_name(model, name)
    return unnamed if found is None else found

def object_id(model:Any, name:str) -> int:
    """`obj->id`"""
    return model.objects[name].id

def catchall(event:str, model:Any, name:str, err:Exception) -> None:
    """`INIT_CATCHALL()` and `SYNC_CATCHALL()`: the error message gridlabd
    writes when a class function throws"""
    cname = model.objects[name].oclass.name
    gl_error(f"{event}_{cname}(obj={object_id(model, name)};{label(model, name)}): {err}")

#
# C arithmetic
#
def cacos(x:float) -> float:
    """C `acos()`: `nan` outside [-1, 1]"""
    if math.isnan(x) or x < -1 or x > 1:
        return math.nan
    return math.acos(x)

def mag(z:complex) -> float:
    """gridlabd `complex::Mag()`"""
    return abs(z)

def cdiv(a:complex, b:complex) -> complex:
    """gridlabd complex division: `nan` parts when `b` is 0"""
    if b == 0:
        return complex(math.nan, math.nan)
    return a / b

#
# Object state
#
_STATE: "weakref.WeakKeyDictionary[Any,dict[str,dict[str,Any]]]" = weakref.WeakKeyDictionary()

def object_state(model:Any, name:str) -> dict[str,Any]:
    """State that gridlabd keeps in unpublished members of an object (a
    `dict`), created on first use and dropped with the model"""
    objects = _STATE.get(model)
    if objects is None:
        objects = {}
        _STATE[model] = objects
    if name not in objects:
        objects[name] = {}
    return objects[name]

def has_state(model:Any, name:str) -> bool:
    """`True` when the object has state (it has been initialized)"""
    return name in _STATE.get(model, {})

#
# Other objects
#
def class_name(model:Any, name:str) -> str:
    """Class name of an object"""
    return model.objects[name].oclass.name

def isa(model:Any, name:str|None, cname:str, module:str|None=None) -> bool:
    """`gl_object_isa(obj, cname[, module])`: the object's class or one it
    inherits from is `cname` (of `module`, when given)"""
    if name is None or name not in model.objects:
        return False
    if module == "powerflow" or (module is None and cname in ("meter", "triplex_meter", "node", "link", "triplex_node")):
        try:
            from powerflow._common import isa as pf_isa # pylint: disable=import-outside-toplevel
        except ImportError: # pragma: no cover
            pf_isa = None
        if pf_isa is not None and pf_isa(model, name, cname):
            return True
        if module == "powerflow":
            return False
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name == cname and (module is None or oclass.module == module):
            return True
        oclass = getattr(oclass, "parent", None)
    return False

def ref(model:Any, name:str, prop_:str) -> str|None:
    """Name of the object an `object` property refers to, or `None`"""
    text = get_text(model, name, prop_)
    if text in ("", "NULL", "(null)"):
        return None
    return text if text in model.objects else None

def header_double(model:Any, name:str, prop_:str) -> float:
    """A `double` header (`latitude`, `longitude`): `nan` when unset, as
    gridlabd's `QNAN` default"""
    text = model.objects[name].get(prop_)
    if text in (None, ""):
        return math.nan
    try:
        return float(str(text).split()[0])
    except ValueError:
        return get_double(model, name, prop_)

def post(model:Any, name:str, prop_:str, delta:complex) -> None:
    """`*pointer += delta` on a complex property of another object (the
    accumulators of the parent meter), keeping the value's notation"""
    if delta == 0:
        return
    value = get_complex(model, name, prop_) + delta
    set_complex(model, name, prop_, value, notation(model, name, prop_) if model.objects[name].get(prop_) else "j")
