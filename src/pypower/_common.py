# pylint: disable=line-too-long
"""@private Helpers shared by the pypower classes

Constants, runner access and messages (gridlabd `gl_error()`,
`gld_object::error()`, ...), the state that the module and each object
keep between handler calls, and property values read and written as
numbers.
"""

import re
import math
import functools
import cmath
import weakref
from typing import Any

from arras.exceptions import ArrasException
from arras import exitcodes

MODULE = "pypower"
"""Module name"""

TS_NEVER = (1 << 63) - 1
"""Timestamp that means no event"""

TS_INVALID = -1
"""Timestamp that reports a failure"""

TRL_PROTOTYPE = 7
"""Technology readiness level `TRL_PROTOTYPE`"""

TRL_PROVEN = 9
"""Technology readiness level `TRL_PROVEN`"""

OF_QUIET = 0x00010000
OF_WARNING = 0x00020000
OF_DEBUG = 0x00040000
OF_VERBOSE = 0x00080000

MESSAGE_FLAGS = {"QUIET": OF_QUIET, "WARNING": OF_WARNING, "DEBUG": OF_DEBUG, "VERBOSE": OF_VERBOSE}
"""Keywords of the `pypower::message_flags` global (gridlabd `INIT_MMF()`)"""

OBJECT_FLAGS = {"NONE": 0, "HASPLC": 0x1, "LOCKED": 0x2, "RERANKED": 0x4000, "RECALC": 0x8,
    "DELTAMODE": 0x40, **MESSAGE_FLAGS}
"""Keywords of the object `flags` header (gridlabd `oflags[]`)"""

class PypowerError(ArrasException):
    """Pypower module error"""

#
# Runner and messages
#
def runner() -> Any:
    """Runner of the calling thread

    Exceptions
    ----------
    - `PypowerError`: no simulation is running in the calling thread
    """
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        raise PypowerError("pypower handlers run only during an arras.runner.Runner simulation")
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

def gl_debug(message:str) -> None:
    """`gl_debug()`: a debug line (when the `debug` global is true)"""
    current = runner()
    current._debug(message) # pylint: disable=protected-access

def python_error(err:BaseException) -> None:
    """`PyErr_Print()` of an exception raised by user Python code (a
    controller): one error line, without changing the exit code"""
    runner().error(f"{type(err).__name__}: {err}")

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
    `pypower::message_flags` global (gridlabd ORs the module's message
    flags into the flags of the objects it creates)"""
    flags = _parse_flags(model.objects[name].get("flags"), OBJECT_FLAGS)
    if model.globals.isdefined(f"{MODULE}::message_flags"):
        flags |= _parse_flags(model.globals.get(f"{MODULE}::message_flags"), MESSAGE_FLAGS)
    return flags

class Messages:
    """`gld_object` messages of one object: `error()`, `warning()`,
    `verbose()`, `debug()` write `NAME: message` as gridlabd does, following
    the object's flags; `exception()` raises"""

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

    def debug(self, message:str) -> None:
        """`gld_object::debug()`: only for `DEBUG` objects"""
        if object_flags(self.model, self.name) & OF_DEBUG:
            gl_debug(f"{self.name}: {message}")

    def exception(self, message:str) -> None:
        """`gld_object::exception()`: raise `PypowerError` (the handler
        fails and the run stops)"""
        raise PypowerError(f"{self.name}: {message}")

#
# Module and object state
#
_STATE: "weakref.WeakKeyDictionary[Any,Any]" = weakref.WeakKeyDictionary()

def module_state(model:Any) -> Any:
    """State of the module for a model (`pypower._module.ModuleState`),
    created on first use and dropped with the model"""
    state = _STATE.get(model)
    if state is None:
        from ._module import ModuleState # pylint: disable=import-outside-toplevel
        state = ModuleState(model)
        _STATE[model] = state
    return state

def object_state(model:Any, name:str, factory:Any=dict) -> Any:
    """State of an object, created with `factory()` on first use"""
    objects = module_state(model).objects
    if name not in objects:
        objects[name] = factory()
    return objects[name]

#
# Classes and objects
#
def isa(model:Any, name:str|None, cname:str) -> bool:
    """`True` when the object's class is the pypower class `cname` or
    inherits from it (gridlabd `gld_object::isa(cname, "pypower")`)"""
    if name is None or name not in model.objects:
        return False
    oclass = model.objects[name].oclass
    while oclass is not None:
        if oclass.name == cname and oclass.module == MODULE:
            return True
        oclass = getattr(oclass, "parent", None)
    return False

def parent_of(model:Any, name:str) -> str|None:
    """Name of the object's parent, or `None`"""
    parent = model.objects[name].get("parent")
    return parent if parent else None

def ref(model:Any, name:str, prop:str) -> str|None:
    """Name of the object an `object` property refers to, or `None`"""
    value = model.get_property(name, prop)
    if value in (None, "", "NULL"):
        return None
    value = str(value).strip().strip('"')
    return value if value in model.objects else None

def objects_of(model:Any, cname:str) -> list[str]:
    """Names of the objects of a pypower class (or classes that inherit
    from it), in creation order"""
    return [name for name in model.objects if isa(model, name, cname)]

#
# C arithmetic
#
def fdiv(a:float, b:float) -> float:
    """C division of doubles: an infinity or `nan` when `b` is 0"""
    if b == 0:
        if a == 0 or math.isnan(a):
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b

def csqrt(a:float) -> float:
    """C `sqrt()`: `nan` for a negative value"""
    return math.sqrt(a) if a >= 0 else math.nan

#
# Values
#
_LG = r"[-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan)"
_DOUBLE = re.compile(rf"\s*({_LG})\s*(\S*)", re.IGNORECASE)
_COMPLEX = re.compile(rf"\s*\(?\s*({_LG})(?:\s*({_LG})\s*([ijdr]))?\s*\)?\s*(\S*)", re.IGNORECASE)

def _units() -> Any:
    from arras.oclass import Class # pylint: disable=import-outside-toplevel
    return Class.get_units()

_UNITS: dict[tuple[int,str],tuple[Any,str|None]] = {}

def _unit_of(model:Any, name:str, prop:str) -> str|None:
    """Unit of an object's property (cached by class)"""
    oclass = model.objects[name].oclass
    key = (id(oclass), prop)
    cached = _UNITS.get(key)
    if cached is None or cached[0] is not oclass:
        spec = oclass.find_property(prop)
        cached = (oclass, spec.unit if spec is not None else None)
        _UNITS[key] = cached
    return cached[1]

def text_to_double(text:Any, unit:str|None=None) -> float:
    """A double from property text (a number, optionally with a unit that
    is converted to `unit`)"""
    if text in (None, ""):
        return 0.0
    return _text_to_double(str(text), unit)

@functools.lru_cache(maxsize=65536)
def _text_to_double(text:str, unit:str|None) -> float:
    match = _DOUBLE.match(text)
    if match is None:
        return 0.0
    value = float(match.group(1))
    if match.group(2) and unit and match.group(2) != unit:
        value = _units().convert(value, match.group(2), unit)
    return value

def text_to_complex(text:Any, unit:str|None=None) -> complex:
    """A complex number from property text (`a+bj`, `a+bd`, `a+br`, `a`,
    Python's `(a+bj)`, optionally with a unit converted to `unit`)"""
    if text in (None, ""):
        return complex(0, 0)
    match = _COMPLEX.match(str(text))
    if match is None:
        return complex(0, 0)
    real = float(match.group(1))
    if match.group(2) is None:
        value = complex(real, 0)
    elif match.group(3).lower() == "d":
        value = cmath.rect(real, float(match.group(2))*math.pi/180)
    elif match.group(3).lower() == "r":
        value = cmath.rect(real, float(match.group(2)))
    else:
        value = complex(real, float(match.group(2)))
    unit_text = match.group(4)
    if unit_text and unit and unit_text != unit:
        units = _units()
        scale = units.convert(1.0, unit_text, unit) - units.convert(0.0, unit_text, unit)
        value *= scale
    return value

def get_double(model:Any, name:str, prop:str) -> float:
    """Value of a `double` property in its own unit"""
    return text_to_double(model.get_property(name, prop), _unit_of(model, name, prop))

def get_complex(model:Any, name:str, prop:str) -> complex:
    """Value of a `complex` property in its own unit"""
    return text_to_complex(model.get_property(name, prop), _unit_of(model, name, prop))

def get_int(model:Any, name:str, prop:str) -> int: # pylint: disable=too-many-return-statements
    """Value of an integer, `bool`, `enumeration`, or `set` property"""
    text = model.get_property(name, prop)
    if text in (None, ""):
        return 0
    text = str(text).strip()
    try:
        return int(text, 0)
    except ValueError:
        pass
    spec = model.objects[name].oclass.find_property(prop)
    if spec is not None and spec.ptype == "bool":
        return 1 if text.upper() == "TRUE" else 0
    keywords = spec.keywords if spec is not None else {}
    if text in keywords:
        return keywords[text]
    if spec is not None and spec.ptype == "set":
        return sum(keywords.get(x.strip(), 0) for x in text.split("|"))
    try:
        return int(float(text))
    except ValueError:
        return 0

def get_text(model:Any, name:str, prop:str) -> str:
    """Value of a property as text (strings without quotes)"""
    text = model.get_property(name, prop)
    if text is None:
        return ""
    text = str(text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text

def fmt(value:float) -> str:
    """Text of a float with 17 significant digits (exact for doubles)"""
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return repr(value + 0.0)

def fmt_complex(value:complex, form:str="j") -> str:
    """Text of a complex value in a notation: `i` or `j` (rectangular), `d`
    (polar, degrees), `r` (polar, radians)"""
    if form in "dr":
        mag, arg = abs(value), cmath.phase(value)
        real, imag = fmt(mag), fmt(math.degrees(arg) if form == "d" else arg)
    else:
        real, imag = fmt(value.real), fmt(value.imag)
    return f"{real}{imag if imag.startswith('-') else '+' + imag}{form}"

_NOTATION = re.compile(rf"\s*\(?\s*{_LG}\s*{_LG}\s*([ijdr])", re.IGNORECASE)

def notation(model:Any, name:str, prop:str) -> str:
    """Notation of a complex property's value (gridlabd keeps one per
    value): the letter of its text, else `i` (the notation of a value that
    was never given one, which gridlabd prints as `i`)"""
    match = _NOTATION.match(str(model.get_property(name, prop) or ""))
    return match.group(1).lower() if match else "i"

def set_double(model:Any, name:str, prop:str, value:float) -> None:
    """Set a `double` property (in its own unit)"""
    model.objects[name][prop] = fmt(value)

def set_complex(model:Any, name:str, prop:str, value:complex, notation_:str="j") -> None:
    """Set a `complex` property (in its own unit); the notation defaults to
    gridlabd's `CNOTATION_DEFAULT` (`j`), the notation of a new `complex`;
    gridlabd's arithmetic keeps the notation of the left operand, and
    `SetPolar()` gives `d`"""
    model.objects[name][prop] = fmt_complex(complex(value), notation_)

def set_int(model:Any, name:str, prop:str, value:int) -> None:
    """Set an integer or `enumeration` property; an enumeration value is
    written as the first keyword gridlabd finds for it"""
    spec = model.objects[name].oclass.find_property(prop)
    if spec is not None and spec.ptype == "enumeration":
        for key, item in spec.keywords.items():
            if item == value:
                model.objects[name][prop] = key
                return
    if spec is not None and spec.ptype == "bool":
        model.objects[name][prop] = "TRUE" if value else "FALSE"
        return
    model.objects[name][prop] = str(int(value))

def set_text(model:Any, name:str, prop:str, value:str) -> None:
    """Set a text property"""
    model.objects[name][prop] = value

def global_value(model:Any, name:str) -> Any:
    """Value of a global variable: numbers for `double`, `int`, `bool`, and
    `enumeration` (the keyword's value), text for the others"""
    var = model.globals.find(name)
    if var is None:
        return None
    value = model.globals.getvalue(name)
    keywords = getattr(var, "keywords", None) or {}
    if var.ptype == "enumeration" and isinstance(value, str):
        return keywords.get(value, 0)
    if var.ptype == "set" and isinstance(value, (set, frozenset)):
        return sum(keywords.get(x, 0) for x in value)
    return value

def set_global(model:Any, name:str, value:Any) -> None:
    """Set a global variable"""
    model.globals.set(name, value)

#
# Values from Python (controller results)
#
def python_text(value:Any) -> str:
    """Text of a Python value as gridlabd's `PyObject_Str()` gives it"""
    return str(value)

def from_string(model:Any, name:str, prop:str, text:str) -> bool:
    """Set a property from text as gridlabd's `gld_property::from_string()`
    does; `False` when the text is not accepted. A `complex` property
    also accepts Python's notation `(a+bj)`, and a number followed only by
    a notation letter is its real part (`5j` is 5, as gridlabd's `sscanf()`
    reads it)"""
    spec = model.objects[name].oclass.find_property(prop)
    try:
        if spec is not None and spec.ptype == "complex":
            match = re.fullmatch(rf"\s*\(\s*({_LG})({_LG})([ijdr])\s*\)\s*", text, re.IGNORECASE)
            if match:
                text = f"{match.group(1)}{match.group(2)}{match.group(3)}"
            else:
                match = re.fullmatch(rf"\s*({_LG})\s*[ijdr]?\s*", text, re.IGNORECASE)
                if match and not re.fullmatch(rf"\s*({_LG})({_LG})[ijdr].*", text, re.IGNORECASE):
                    text = match.group(1)
        model.set_property(name, prop, text)
        return True
    except ArrasException:
        return False
