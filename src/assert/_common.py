# pylint: disable=line-too-long
"""@private Helpers shared by the assert classes

Target property lookup, value conversion as gridlabd's `convert_to_*()`
functions do it, messages gated by object flags as `gld_object::error()`,
`warning()`, and `verbose()` do it, and the state that each assert object
keeps between its `init` and `commit` handlers.
"""

import re
import math
import cmath
import weakref
import datetime
from typing import Any

from arras.exceptions import ArrasException
from arras.model import HEADER
from arras.oclass import Class

MODULE = "assert"
"""Module name"""

TS_ZERO = 0
"""Timestamp printed as `INIT`"""

TS_NEVER = (1 << 63) - 1
"""Timestamp printed as `NEVER`"""

TS_INVALID = -1
"""Timestamp that reports a failure"""

OF_QUIET = 0x00010000
"""Object flag that disables error messages (gridlabd `OF_QUIET`)"""

OF_WARNING = 0x00020000
"""Object flag that disables warning messages (gridlabd `OF_WARNING`)"""

OF_DEBUG = 0x00040000
"""Object flag that enables debug messages (gridlabd `OF_DEBUG`)"""

OF_VERBOSE = 0x00080000
"""Object flag that enables verbose messages (gridlabd `OF_VERBOSE`)"""

MESSAGE_FLAGS = {"QUIET": OF_QUIET, "WARNING": OF_WARNING, "DEBUG": OF_DEBUG, "VERBOSE": OF_VERBOSE}
"""Keywords of the `assert::message_flags` global (gridlabd `INIT_MMF()`)"""

OBJECT_FLAGS = {"NONE": 0, "HASPLC": 0x1, "LOCKED": 0x2, "RERANKED": 0x4000, "RECALC": 0x8,
    "DELTAMODE": 0x40, **MESSAGE_FLAGS}
"""Keywords of the object `flags` header (gridlabd `oflags[]`)"""

class AssertError(ArrasException):
    """Assert module error"""

#
# Runner access and messages
#
def runner():
    """Runner of the calling thread

    Exceptions
    ----------
    - `AssertError`: no simulation is running in the calling thread
    """
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        raise AssertError("assert handlers run only during an arras.runner.Runner simulation")
    return current

def object_flags(model:Any, name:str) -> int:
    """Message flags of an object: its `flags` header and the
    `assert::message_flags` global (gridlabd ORs the global into the flags
    when it creates the object)"""
    flags = parse_flags(model.objects[name].get("flags"), OBJECT_FLAGS)
    var = model.globals.find(f"{MODULE}::message_flags")
    if var is not None:
        flags |= parse_flags(model.globals.get(f"{MODULE}::message_flags"), MESSAGE_FLAGS)
    return flags

def parse_flags(text:str|int|None, keywords:dict[str,int]) -> int:
    """Flag bits of a set value (`|`-separated keywords or an integer)"""
    if text is None or text == "":
        return 0
    if isinstance(text, int):
        return text
    text = str(text).strip()
    if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", text):
        return int(text, 0)
    bits = 0
    for key in text.split("|"):
        bits |= keywords.get(key.strip(), 0)
    return bits

def object_error(name:str, flags:int, message:str) -> None:
    """`gld_object::error()`: `NAME: message`, unless the object is `QUIET`"""
    if not flags & OF_QUIET:
        runner().error(f"{name}: {message}")

def object_warning(name:str, flags:int, message:str) -> None:
    """`gld_object::warning()`: `NAME: message`, unless the object has the
    `WARNING` flag"""
    if not flags & OF_WARNING:
        runner().warning(f"{name}: {message}")

def object_verbose(name:str, flags:int, message:str) -> None:
    """`gld_object::verbose()`: `NAME: message`, only for objects with the
    `VERBOSE` flag"""
    if flags & OF_VERBOSE:
        runner().verbose(f"{name}: {message}")

#
# Object state kept between handler calls
#
_STATE: "weakref.WeakKeyDictionary[Any,dict[str,Any]]" = weakref.WeakKeyDictionary()

def get_state(model:Any, name:str) -> Any:
    """State saved by `set_state()` for an object of a model, or `None`"""
    return _STATE.get(model, {}).get(name)

def set_state(model:Any, name:str, state:Any) -> None:
    """Save the state of an object of a model (dropped with the model)"""
    _STATE.setdefault(model, {})[name] = state

#
# Values
#
_LG = r"[-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan(?:\([^)]*\))?)"
_SCAN_DOUBLE = re.compile(rf"\s*({_LG})", re.IGNORECASE)

def scan_double(text:str) -> tuple[float,str]|None:
    """C `sscanf(text,"%lg")`: the number and the rest of the text, or
    `None` when no number is read"""
    match = _SCAN_DOUBLE.match(text)
    if match is None:
        return None
    return float(match.group(1).split("(")[0]), text[match.end():]

def atof(text:str) -> float:
    """C `atof()`: the leading number of the text, else 0"""
    result = scan_double(text)
    return result[0] if result else 0.0

def convert_unit(value:float, unit:str, to:str|None, what:str) -> float:
    """Convert `value` from `unit` to `to` with the shared unit manager

    Exceptions
    ----------
    - `AssertError`: the property has no unit, or the units are not
      compatible
    """
    if to is None:
        raise AssertError(f"{what}: unit given to unitless property")
    if unit == to:
        return value
    try:
        return Class.get_units().convert(value, unit, to)
    except ArrasException as err:
        raise AssertError(f"{what}: unit conversion failed ({err})") from err

def to_double(text:str, unit:str|None=None, what:str="value") -> float:
    """Convert text to a double as `convert_to_double()` does: a number
    with an optional unit, converted to `unit`

    Exceptions
    ----------
    - `AssertError`: the text is empty or not a number, or the unit cannot
      be converted
    """
    text = text.strip()
    result = scan_double(text)
    if result is None:
        raise AssertError(f"{what}: '{text}' is not a number")
    value, rest = result
    rest = rest.strip().split()
    if rest:
        value = convert_unit(value, rest[0], unit, f"{what} '{text}'")
    return value

def to_complex(text:str, unit:str|None=None, what:str="value") -> complex:
    """Convert text to a complex number as `convert_to_complex()` does:
    `A`, `A+Bi`, `A+Bj` (rectangular), `A+Bd` (polar degrees), `A+Br`
    (polar radians), with an optional unit

    Exceptions
    ----------
    - `AssertError`: the text is not a complex number, or the unit cannot
      be converted
    """
    text = text.strip()
    if text == "":
        return complex(0, 0)
    body = text[1:] if text.startswith("(") else text
    first = scan_double(body)
    if first is None:
        raise AssertError(f"{what}: complex number '{text}' format is not valid")
    real, rest = first
    second = scan_double(rest) if rest[:1] in "+-" or rest[:1].isspace() else None
    if second is None:
        return complex(real, 0)
    imag, rest = second
    if not rest or rest[0] not in "ijdr":
        raise AssertError(f"{what}: complex number '{text}' format is not valid")
    notation, rest = rest[0], rest[1:].strip(" )")
    if notation == "d":
        value = cmath.rect(real, imag*math.pi/180)
    elif notation == "r":
        value = cmath.rect(real, imag)
    else:
        value = complex(real, imag)
    if rest and not text.startswith("("):
        scale = convert_unit(1.0, rest.split()[0], unit, f"{what} '{text}'")
        value *= scale
    return value

def to_timestamp(model:Any, text:str) -> int:
    """Convert text to a timestamp with the model's globals
    (`arras.globals.Globals.timestamp_from_string()`), also accepting a
    trailing time zone abbreviation of the model's time zone (`PST`,
    `PDT`, ...), which `arras` writes in object `clock` values

    Exceptions
    ----------
    - `AssertError`: the text is not a valid timestamp
    """
    globs = model.globals
    text = text.strip().strip("'\"").strip()
    try:
        return globs.timestamp_from_string(text)
    except ArrasException as err:
        error = err
    stripped, _, abbreviation = text.rpartition(" ")
    if stripped and abbreviation.isalpha():
        try:
            base = globs.timestamp_from_string(stripped)
        except ArrasException:
            base = None
        if base is not None:
            zone = globs.timezone()
            for ts in (base, base - 3600, base + 3600):
                local = datetime.datetime.fromtimestamp(ts, zone)
                if local.tzname() == abbreviation and local.replace(tzinfo=None) == \
                        datetime.datetime.fromtimestamp(base, zone).replace(tzinfo=None):
                    return ts
            for ts in (base, base - 3600, base + 3600):
                if datetime.datetime.fromtimestamp(ts, zone).tzname() == abbreviation:
                    return ts
    raise AssertError(f"'{text}' is not a valid timestamp") from error

def angle(value:complex) -> float:
    """Angle in radians (gridlabd `complex::Arg()`)"""
    return math.atan2(value.imag, value.real)

#
# Target properties
#
class Target:
    """A property of an object, or a global variable when `name` is `None`
    (gridlabd `gld_property`)

    Attributes
    ----------
    - `model`: the model
    - `name`: object name, or `None` for a global variable
    - `prop`: property name
    - `ptype`: property type, or `None` when the property is not found
    - `unit`: unit name, or `None`
    - `keywords`: keyword values of an `enumeration` or `set`
    - `charset`: the `set` property has single-character keywords
    """

    def __init__(self, model:Any, name:str|None, prop:str):
        self.model = model
        self.name = name
        self.prop = prop
        self.ptype: str|None = None
        self.unit: str|None = None
        self.keywords: dict[str,int] = {}
        self.charset = False
        if name is None:
            var = model.globals.find(prop)
            if var is not None:
                self.ptype = var.ptype
                self.unit = getattr(var, "unit", None)
                self.keywords = dict(getattr(var, "keywords", None) or {})
            return
        obj = model.objects.get(name)
        if obj is None:
            return
        if prop in HEADER and prop not in ("class", "name"):
            self.ptype = HEADER[prop]
            return
        spec = obj.oclass.find_property(prop)
        if spec is not None:
            self.ptype = spec.ptype
            self.unit = spec.unit
            self.keywords = dict(spec.keywords)
            self.charset = spec.has_flag("CHARSET")

    @property
    def is_valid(self) -> bool:
        """`True` when the property exists"""
        return self.ptype is not None

    @property
    def owner(self) -> str:
        """Object name, or `global variable`"""
        return self.name if self.name is not None else "global variable"

    def text(self) -> str:
        """Value as text, as gridlabd prints it (`gld_property::to_string()`)"""
        if self.name is None:
            value = self.model.globals.get(self.prop)
        elif self.prop == "id":
            value = str(self.model.objects[self.name].id)
        else:
            value = self.model.get_property(self.name, self.prop)
        return "" if value is None else str(value)

    def double(self) -> float:
        """Value of a `double` property in its unit"""
        text = self.text()
        if text == "":
            return 0.0
        return to_double(text, self.unit, f"{self.owner}.{self.prop}")

    def complex(self) -> complex:
        """Value of a `complex` property in its unit"""
        return to_complex(self.text(), self.unit, f"{self.owner}.{self.prop}")

    def integer(self) -> int:
        """Value of an integer property"""
        text = self.text().strip()
        if text == "":
            return 0
        return int(text, 0)

    def enumeration(self) -> int:
        """Value of an `enumeration` property"""
        text = self.text().strip()
        if text in self.keywords:
            return self.keywords[text]
        if text == "":
            return 0
        return int(text, 0)
