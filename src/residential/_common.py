# pylint: disable=line-too-long
"""@private Helpers shared by the residential classes

Constants (circuit types, enduse configuration, flags), runner access and
messages (gridlabd `gl_error()`, `gld_object::error()`, ...), the state
that the module and each object keep between handler calls, object
random number generators, and `Members`, which reads an object's
published properties into Python attributes named as the C++ members and
writes back the ones that changed. Property values are read and written
with the helpers of `pypower._common`, which are not specific to the
`pypower` module.
"""

import math
import random
import weakref
from typing import Any

from arras.exceptions import ArrasException
from arras import exitcodes

# pylint: disable=unused-import
from pypower._common import (get_double, get_complex, get_int, get_text, set_double,
    set_complex, set_int, set_text, fmt, fmt_complex, text_to_double, text_to_complex, notation)

MODULE = "residential"
"""Module name"""

TS_NEVER = (1 << 63) - 1
"""Timestamp that means no event"""

TS_INVALID = -1
"""Timestamp that reports a failure"""

TS_ZERO = 0
"""Timestamp printed as `INIT`"""

TRL_PROVEN = 9
"""Technology readiness level `TRL_PROVEN`"""

TRL_UNKNOWN = 0
"""Technology readiness level `TRL_UNKNOWN` (classes that do not set one)"""

INIT_DEFER = 2
"""`init()` result that defers the initialization"""

#
# residential.h, enduse.h
#
BTUPHPW = 3.4120
"""Btu/h per W"""

BTUPHPKW = 1e3*3.4120
"""Btu/h per kW"""

KWPBTUPH = 1e-3/BTUPHPW
"""kW per Btu/h"""

BRK_OPEN, BRK_CLOSED, BRK_FAULT = 0, 1, -1
"""Breaker states"""

X12, X23, X13 = range(3)
"""Circuit types: line 1 to line 2 (240 V), line 2 to neutral, line 1 to
neutral (120 V)"""

EUC_IS110, EUC_IS220, EUC_HEATLOAD = 0, 1, 2
"""Enduse configuration bits (`EUC_IS110` is no bit)"""

OV_NORMAL, OV_ON, OV_OFF = range(3)
"""`override` values"""

PS_OFF, PS_ON, PS_UNKNOWN = range(3)
"""`power_state` values"""

#
# Message flags
#
OF_QUIET = 0x00010000
OF_WARNING = 0x00020000
OF_DEBUG = 0x00040000
OF_VERBOSE = 0x00080000

MESSAGE_FLAGS = {"QUIET": OF_QUIET, "WARNING": OF_WARNING, "DEBUG": OF_DEBUG, "VERBOSE": OF_VERBOSE}
"""Keywords of the `residential::message_flags` global (gridlabd `INIT_MMF()`)"""

OBJECT_FLAGS = {"NONE": 0, "HASPLC": 0x1, "LOCKED": 0x2, "RERANKED": 0x4000, "RECALC": 0x8,
    "DELTAMODE": 0x40, **MESSAGE_FLAGS}
"""Keywords of the object `flags` header (gridlabd `oflags[]`)"""

class ResidentialError(ArrasException):
    """Residential module error"""

BEHAVIORS: dict[str,Any] = {}
"""Behavior class of each residential class name (filled by the package)"""

#
# Runner and messages
#
def runner() -> Any:
    """Runner of the calling thread

    Exceptions
    ----------
    - `ResidentialError`: no simulation is running in the calling thread
    """
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        raise ResidentialError("residential handlers run only during an arras.runner.Runner simulation")
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
    try:
        return int(text, 0)
    except ValueError:
        pass
    bits = 0
    for key in text.split("|"):
        bits |= keywords.get(key.strip(), 0)
    return bits

def object_flags(model:Any, name:str) -> int:
    """Flag bits of an object: its `flags` header ORed with the
    `residential::message_flags` global"""
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

def init_failed(model:Any, name:str, err:Exception) -> None:
    """`INIT_CATCHALL()`: the error message gridlabd writes when `init()`
    throws"""
    obj = model.objects[name]
    text = "unnamed" if name == f"{obj.oclass.name}:{obj.id}" else name
    runner().error(f"init_{obj.oclass.name}(obj={obj.id};{text}): {err}")

def sync_failed(model:Any, name:str, err:Exception) -> None:
    """`SYNC_CATCHALL()`: the error message gridlabd writes when `sync()`
    throws"""
    obj = model.objects[name]
    text = "unnamed" if name == f"{obj.oclass.name}:{obj.id}" else name
    runner().error(f"sync_{obj.oclass.name}(obj={obj.id};{text}): {err}")

#
# Module and object state
#
class ModuleState: # pylint: disable=too-few-public-methods
    """State of the module for one model"""

    def __init__(self) -> None:
        self.objects: dict[str,Any] = {}
        """Object states keyed on name"""
        self.initialized: set[str] = set()
        """Residential objects that are initialized"""
        self.climate_warned = False
        """Whether the several-climates warning was written (gridlabd keeps
        the climate list in a static variable, so the first house writes
        it)"""

_STATE: "weakref.WeakKeyDictionary[Any,ModuleState]" = weakref.WeakKeyDictionary()

def module_state(model:Any) -> ModuleState:
    """State of the module for a model, created on first use and dropped
    with the model"""
    state = _STATE.get(model)
    if state is None:
        state = ModuleState()
        _STATE[model] = state
    return state

def object_state(model:Any, name:str, factory:Any=dict) -> Any:
    """State of an object, created with `factory()` on first use"""
    objects = module_state(model).objects
    if name not in objects:
        objects[name] = factory()
    return objects[name]

def object_rng(model:Any, name:str) -> random.Random:
    """Random number generator of an object, seeded with the `randomseed`
    global and the object id, so runs are repeatable (gridlabd's
    `RNGSTATE` is the object's own random state too, but its sequence
    differs)"""
    seed = int(model.globals.getvalue("randomseed") or 0)
    return random.Random(seed * 1000003 + model.objects[name].id)

#
# Classes and objects
#
def isa(model:Any, name:str|None, cname:str, module:str=MODULE) -> bool:
    """`True` when the object's class is `cname` of `module` or inherits
    from it"""
    if name is None or name not in model.objects:
        return False
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name == cname and oclass.module == module:
            return True
        oclass = getattr(oclass, "parent", None)
    return False

def behavior(model:Any, name:str) -> Any:
    """Behavior class of an object: that of its class, or of the nearest
    class it inherits from that has one

    Exceptions
    ----------
    - `ResidentialError`: the object is not a residential object
    """
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name in BEHAVIORS and oclass.module == MODULE:
            return BEHAVIORS[oclass.name]
        oclass = getattr(oclass, "parent", None)
    raise ResidentialError(f"object '{name}' is not a residential object")

def parent_of(model:Any, name:str) -> str|None:
    """Name of the object's parent, or `None`"""
    value = model.objects[name].get("parent")
    if value in (None, "", "NULL"):
        return None
    value = str(value).strip().strip('"')
    return value if value in model.objects else None

def ref(model:Any, name:str, prop:str) -> str|None:
    """Name of the object an `object` property refers to, or `None`"""
    value = model.get_property(name, prop)
    if value in (None, "", "NULL"):
        return None
    value = str(value).strip().strip('"')
    return value if value in model.objects else None

def g(model:Any, name:str) -> Any:
    """Value of global `residential::NAME`: numbers for `double`, `int`,
    `bool`, and `enumeration` (the keyword's value), set bits for `set`,
    text for the others"""
    gname = f"{MODULE}::{name}"
    var = model.globals.find(gname)
    if var is None:
        return None
    value = model.globals.getvalue(gname)
    keywords = getattr(var, "keywords", None) or {}
    if var.ptype == "enumeration" and isinstance(value, str):
        return keywords.get(value, 0)
    if var.ptype == "set":
        if isinstance(value, (set, frozenset)):
            return sum(keywords.get(x, 0) for x in value)
        return _parse_flags(value, keywords)
    return value

def label(model:Any, name:str) -> str:
    """Object name as gridlabd's `obj->name` prints it in messages:
    `None` objects (unnamed) print `(null)`"""
    obj = model.objects[name]
    return "(null)" if name == f"{obj.oclass.name}:{obj.id}" else name

def strtime(model:Any, t:int) -> str:
    """`gl_strftime()` of a timestamp"""
    return model.globals.timestamp_to_string(t)

#
# Published properties as Python attributes
#
_TIMESTAMPS: "weakref.WeakKeyDictionary[Any,dict[tuple[str,str],tuple[str,int]]]" = weakref.WeakKeyDictionary()

def _get_timestamp(model:Any, name:str, prop:str) -> int:
    text = model.get_property(name, prop)
    if text in (None, ""):
        return 0
    text = str(text).strip()
    cached = _TIMESTAMPS.get(model, {}).get((name, prop))
    if cached is not None and cached[0] == text:
        return cached[1]
    try:
        return int(text)
    except ValueError:
        pass
    if text in ("INIT", "NEVER"):
        return 0 if text == "INIT" else TS_NEVER
    try:
        return int(model.globals.timestamp_from_string(text))
    except Exception: # pylint: disable=broad-exception-caught
        # a time zone the parser does not know (e.g. 'PST'): the time in the
        # model's time zone
        return int(model.globals.timestamp_from_string(text.rsplit(" ", 1)[0]))

def _set_timestamp(model:Any, name:str, prop:str, value:int) -> None:
    value = int(value)
    if value == 0:
        text = "0"
    elif value == TS_NEVER:
        text = "NEVER"
    else:
        text = model.globals.timestamp_to_string(value)
    model.objects[name][prop] = text
    _TIMESTAMPS.setdefault(model, {})[(name, prop)] = (str(model.get_property(name, prop)).strip(), value)

class Members:
    """The published properties of an object as attributes named as the
    C++ members, read by `read()` and written back by `write()`

    `MAP` lists `(member, property, kind)` with `kind` one of `d`
    (double), `c` (complex), `i` (integer, enumeration, set, bool), `t`
    (timestamp), and `s` (text). A property that gridlabd publishes at the
    address of another member (an alias) is listed with that member;
    `read()` takes the value of the alias that changed since the last
    `write()`, or before the first write the last alias the model sets (the
    last alias listed when it sets none, whose default gridlabd applies
    last), and `write()` writes every alias.
    """

    MAP: tuple[tuple[str,str,str],...] = ()

    def __init__(self, model:Any, name:str):
        self._model = model
        self._name = name
        self._saved: dict[str,Any] = {}
        self._loaded: dict[str,Any] = {}

    def written(self, prop:str) -> Any:
        """Value of a property as last written by `write()` (read back), or
        `None`"""
        return self._saved.get(prop)

    def _get_prop(self, prop:str, kind:str) -> Any:
        model, name = self._model, self._name
        if kind == "d":
            return get_double(model, name, prop)
        if kind == "c":
            return get_complex(model, name, prop)
        if kind == "i":
            return get_int(model, name, prop)
        if kind == "t":
            return _get_timestamp(model, name, prop)
        return get_text(model, name, prop)

    def _set_prop(self, prop:str, kind:str, value:Any) -> None:
        model, name = self._model, self._name
        if kind == "d":
            set_double(model, name, prop, value)
        elif kind == "c":
            set_complex(model, name, prop, complex(value), "j")
        elif kind == "i":
            spec = model.objects[name].oclass.find_property(prop)
            if spec is not None and spec.ptype == "set":
                set_flags(model, name, prop, int(value))
            else:
                set_int(model, name, prop, int(value))
        elif kind == "t":
            _set_timestamp(model, name, prop, value)
        else:
            set_text(model, name, prop, value)

    def read(self) -> None:
        """Read the published properties into the members"""
        groups: dict[str,list[tuple[str,str]]] = {}
        for member, prop, kind in self.MAP:
            groups.setdefault(member, []).append((prop, kind))
        for member, props in groups.items():
            values = [(prop, self._get_prop(prop, kind)) for prop, kind in props]
            value = values[0][1]
            if len(values) > 1:
                if self._saved:
                    changed = [v for p, v in values if v != self._saved.get(p)]
                    if changed:
                        value = changed[-1]
                else:
                    obj = self._model.objects[self._name]
                    given = [v for p, v in values if obj.get(p) not in (None, "")]
                    value = given[-1] if given else values[-1][1]
            self._set(member, value)
            self._loaded[member] = value

    def write(self) -> None:
        """Write back the members that changed since `read()` (all the
        aliases of a member), and remember the values written"""
        for member, prop, kind in self.MAP:
            value = self._get(member)
            if prop not in self._saved or value != self._loaded.get(member) or value != self._saved[prop]:
                self._set_prop(prop, kind, value)
                self._saved[prop] = self._get_prop(prop, kind)
        for member, _, _ in self.MAP:
            self._loaded[member] = self._get(member)

    def _get(self, member:str) -> Any:
        obj: Any = self
        for part in member.split("."):
            obj = getattr(obj, part)
        return obj

    def _set(self, member:str, value:Any) -> None:
        obj: Any = self
        *path, last = member.split(".")
        for part in path:
            obj = getattr(obj, part)
        setattr(obj, last, value)

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
    for key, bits in sorted(items, key=lambda x: -bin(x[1]).count("1")):
        if rest & bits == bits:
            names.append(key)
            rest &= ~bits
    if rest or not names:
        model.objects[name][prop] = str(int(value))
        return
    sep = "" if all(len(key) == 1 for key, _ in items) else "|"
    model.objects[name][prop] = sep.join(names)

class Enduse: # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """The core's `enduse` structure (`source/enduse.h`), as
    `enduse_create()` initializes it; the published members are mapped by
    `enduse_map()`"""

    def __init__(self, name:str|None=None):
        self.total = 0j
        self.energy = 0j
        self.demand = 0j
        self.config = 0
        self.breaker_amps = 0.0
        self.admittance = 0j
        self.current = 0j
        self.power = 0j
        self.impedance_fraction = 0.0
        self.current_fraction = 0.0
        self.power_fraction = 0.0
        self.power_factor = 1.0
        self.voltage_factor = 0.0
        self.heatgain = 0.0
        self.cumulative_heatgain = 0.0
        self.heatgain_fraction = 1.0
        self.gas_fraction = 0.0
        self.curtailment_fraction = 1.0
        self.name = name
        self.t_last = TS_ZERO

ENDUSE_MEMBERS = (
    ("energy", "energy", "c"),
    ("total", "power", "c"),
    ("demand", "peak_demand", "c"),
    ("heatgain", "heatgain", "d"),
    ("cumulative_heatgain", "cumulative_heatgain", "d"),
    ("heatgain_fraction", "heatgain_fraction", "d"),
    ("current_fraction", "current_fraction", "d"),
    ("impedance_fraction", "impedance_fraction", "d"),
    ("power_fraction", "power_fraction", "d"),
    ("power_factor", "power_factor", "d"),
    ("power", "constant_power", "c"),
    ("current", "constant_current", "c"),
    ("admittance", "constant_admittance", "c"),
    ("voltage_factor", "voltage_factor", "d"),
    ("breaker_amps", "breaker_amps", "d"),
    ("config", "configuration", "i"),
)
"""Enduse members and the names `enduse_publish()` publishes them under"""

def enduse_map(member:str, prefix:str="") -> tuple[tuple[str,str,str],...]:
    """`Members.MAP` entries of an enduse member `member` published with
    `prefix` (`""` or `"panel"`)"""
    return tuple((f"{member}.{field}", f"{prefix}.{prop}" if prefix else prop, kind)
        for field, prop, kind in ENDUSE_MEMBERS)

def clip(x:float, lo:float, hi:float) -> float:
    """gridlabd `clip()`"""
    return lo if x < lo else (hi if x > hi else x)

def sqrt(x:float) -> float:
    """C `sqrt()`: `nan` for a negative argument"""
    return math.sqrt(x) if x >= 0 else math.nan

def exp(x:float) -> float:
    """C `exp()`: `inf` on overflow"""
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf

def fdiv(a:float, b:float) -> float:
    """C division of doubles: infinities and `nan` for a zero divisor"""
    try:
        return a / b
    except ZeroDivisionError:
        if a == 0 or math.isnan(a):
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)

def cdiv(a:complex, b:complex) -> complex:
    """Complex division with gridlabd's result for a zero divisor (the
    components divided by zero)"""
    try:
        return a / b
    except ZeroDivisionError:
        return complex(fdiv(a.real, 0.0), fdiv(a.imag, 0.0))
