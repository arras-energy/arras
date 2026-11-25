# pylint: disable=line-too-long
"""@private Helpers shared by the climate classes

Runner access and messages (gridlabd `gl_error()`, `gl_warning()`,
`gld_object::error()`, ...), a C `sscanf()` and `strtok_r()` work-alike
used to read weather files as the C++ code reads them, local time
conversion as the gridlabd core's `local_datetime()` and `mkdatetime()`
do it, the interpolation functions of the core, property access, and the
state that each object keeps between its event handlers.
"""

import re
import math
import random
import weakref
import calendar
import datetime
from typing import Any

from arras.exceptions import ArrasException
from arras.oclass import Class

MODULE = "climate"
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
"""Keywords of the `climate::message_flags` global (gridlabd `INIT_MMF()`)"""

OBJECT_FLAGS = {"NONE": 0, "HASPLC": 0x1, "LOCKED": 0x2, "RERANKED": 0x4000, "RECALC": 0x8,
    "DELTAMODE": 0x40, **MESSAGE_FLAGS}
"""Keywords of the object `flags` header (gridlabd `oflags[]`)"""

TRL_CONCEPT = 2
"""Technology readiness level of class `weather` (gridlabd `TRL_CONCEPT`)"""

TRL_UNKNOWN = 0
"""Technology readiness level of the other classes (gridlabd `TRL_UNKNOWN`)"""

PI = math.pi
"""gridlabd `PI`"""

def rad(x:float) -> float:
    """gridlabd `RAD(x)`: degrees to radians"""
    return (x*PI)/180

class ClimateError(ArrasException):
    """Climate module error"""

#
# Runner access and messages
#
def runner():
    """Runner of the calling thread

    Exceptions
    ----------
    - `ClimateError`: no simulation is running in the calling thread
    """
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        raise ClimateError("climate handlers run only during an arras.runner.Runner simulation")
    return current

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

def object_flags(model:Any, name:str) -> int:
    """Message flags of an object: its `flags` header and the
    `climate::message_flags` global (gridlabd ORs the global into the flags
    when it creates the object)"""
    flags = parse_flags(model.objects[name].get("flags"), OBJECT_FLAGS)
    if model.globals.find(f"{MODULE}::message_flags") is not None:
        flags |= parse_flags(model.globals.get(f"{MODULE}::message_flags"), MESSAGE_FLAGS)
    return flags

def gl_error(message:str) -> None:
    """`gl_error()`: an error line"""
    runner().error(message)

def gl_warning(message:str) -> None:
    """`gl_warning()`: a warning line"""
    runner().warning(message)

def gl_verbose(message:str) -> None:
    """`gl_verbose()`: a verbose line"""
    runner().verbose(message)

def object_error(model:Any, name:str, message:str) -> None:
    """`gld_object::error()`: `NAME: message`, unless the object is `QUIET`"""
    if not object_flags(model, name) & OF_QUIET:
        runner().error(f"{name}: {message}")

def object_warning(model:Any, name:str, message:str) -> None:
    """`gld_object::warning()`: `NAME: message`, unless the object has the
    `WARNING` flag"""
    if not object_flags(model, name) & OF_WARNING:
        runner().warning(f"{name}: {message}")

def object_verbose(model:Any, name:str, message:str) -> None:
    """`gld_object::verbose()`: `NAME: message`, only for objects with the
    `VERBOSE` flag"""
    if object_flags(model, name) & OF_VERBOSE:
        runner().verbose(f"{name}: {message}")

def header_name(model:Any, name:str) -> str:
    """The object's `name` header as C prints `obj->name` with `%s`:
    `(null)` for an unnamed object"""
    obj = model.objects[name]
    return "(null)" if name == f"{obj.oclass.name}:{obj.id}" else name

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

def object_rng(model:Any, name:str) -> random.Random:
    """Random number generator of an object, seeded with the `randomseed`
    global and the object id, so runs are repeatable"""
    seed = int(model.globals.getvalue("randomseed") or 0)
    return random.Random(seed * 1000003 + model.objects[name].id)

#
# Property access
#
_NUMBER = re.compile(r"\s*([-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan))\s*(.*)$", re.IGNORECASE)

def fmt(value:float) -> str:
    """Text of a float as `arras.model` writes it (15 significant digits)"""
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return repr(value)
    return repr(float(f"{value:.15g}") + 0.0)

def to_double(text:str|None, unit:str|None=None, what:str="value") -> float:
    """Convert text to a double: a number with an optional unit, converted
    to `unit` with the shared unit manager

    Exceptions
    ----------
    - `ClimateError`: the text is not a number, or the unit cannot be
      converted
    """
    if text is None or str(text).strip() == "":
        return 0.0
    match = _NUMBER.match(str(text))
    if match is None:
        raise ClimateError(f"{what}: '{text}' is not a number")
    value = float(match.group(1))
    rest = match.group(2).strip()
    if rest:
        if unit is None:
            raise ClimateError(f"{what}: unit '{rest}' given to unitless property")
        if rest != unit:
            try:
                value = Class.get_units().convert(value, rest, unit)
            except ArrasException as err:
                raise ClimateError(f"{what}: unit conversion failed ({err})") from err
    return value

def get_double(model:Any, name:str, prop:str) -> float:
    """Value of a `double` property (or header) in the property's unit;
    `NaN` for a header `latitude` or `longitude` that is not set"""
    text = model.get_property(name, prop)
    if prop in ("latitude", "longitude"):
        if text in (None, ""):
            return math.nan
        try:
            return float(text)
        except ValueError:
            return _latlon(text)
    spec = model.objects[name].oclass.find_property(prop)
    return to_double(text, spec.unit if spec is not None else None, f"{name}.{prop}")

def _latlon(text:str) -> float:
    """A latitude or longitude written as `DDdMM:SS` (gridlabd
    `convert_to_latitude()`)"""
    match = re.fullmatch(r"\s*(\d+)([NSEWnsew])(\d+)(?::(\d+(?:\.\d*)?))?\s*", str(text))
    if match is None:
        raise ClimateError(f"'{text}' is not a valid latitude or longitude")
    deg, hem, mins, secs = match.groups()
    value = int(deg) + int(mins)/60 + (float(secs) if secs else 0.0)/3600
    return -value if hem in "SsWw" else value

def get_text(model:Any, name:str, prop:str) -> str:
    """Value of a property as text (`""` when it has none)"""
    value = model.get_property(name, prop)
    return "" if value is None else str(value)

def get_keyword(model:Any, name:str, prop:str) -> int:
    """Value of an `enumeration` property"""
    spec = model.objects[name].oclass.find_property(prop)
    text = get_text(model, name, prop).strip() or "0"
    if text in spec.keywords:
        return spec.keywords[text]
    return int(text, 0)

def store(model:Any, name:str, values:dict[str,Any]) -> None:
    """Write property values computed by the module (as C++ members are
    written): floats as `arras.model` writes them, others as text"""
    obj = model.objects[name]
    for key, value in values.items():
        if isinstance(value, float):
            obj[key] = fmt(value)
        else:
            obj[key] = str(value)

#
# Time
#
DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
"""Days in each month of a non-leap year"""

def isleapyear(year:int) -> bool:
    """gridlabd `ISLEAPYEAR()`"""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)

class DateTime: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Local date and time of a timestamp (gridlabd `DATETIME`)

    Attributes
    ----------
    - `year`, `month`, `day`, `hour`, `minute`, `second`: local time
    - `yearday`: day of the year from 0
    - `weekday`: day of the week (Sunday is 0)
    - `is_dst`: daylight saving time is in effect
    """

    def __init__(self, local:datetime.datetime):
        self.year = local.year
        self.month = local.month
        self.day = local.day
        self.hour = local.hour
        self.minute = local.minute
        self.second = local.second
        self.yearday = local.timetuple().tm_yday - 1
        self.weekday = (local.weekday() + 1) % 7
        self.is_dst = bool(local.dst())

def local_datetime(model:Any, ts:int) -> DateTime|None:
    """Local date and time of `ts` in the model's time zone (gridlabd
    `local_datetime()`), or `None` for `INIT`, `NEVER`, and times out of
    range"""
    if ts in (TS_ZERO, TS_NEVER) or ts < 0:
        return None
    try:
        local = datetime.datetime.fromtimestamp(ts, model.globals.timezone())
    except (OverflowError, OSError, ValueError):
        return None
    return DateTime(local)

def mkdatetime(model:Any, fields:tuple[int,int,int,int,int,int], is_dst:bool) -> int:
    """Timestamp of a local date and time (gridlabd `mkdatetime()`), with
    the time zone named by the standard (`is_dst` false) or daylight saving
    (`is_dst` true) abbreviation of the model's time zone, as the C++ code
    passes the abbreviation of another time

    Returns `TS_INVALID` for a month or day out of range, after an error
    line, as gridlabd's `output_fatal()` writes one.
    """
    year, month, day, hour, minute, second = fields
    if month < 1 or month > 12:
        gl_error("Invalid month provided in datetime")
        return TS_INVALID
    if day < 1 or day > DAYS_IN_MONTH[month-1]:
        if not (isleapyear(year) and month == 2 and day == 29):
            gl_error("Invalid day provided in datetime")
            return TS_INVALID
    ts = calendar.timegm((year, month, 1, 0, 0, 0)) + (day-1)*86400
    if hour < 0 or hour > 23 or minute < 0 or minute > 60 or second < 0 or second > 62:
        gl_error("Invalid time of day provided in datetime")
        return ts
    ts += hour*3600 + minute*60 + second
    zone = model.globals.timezone()
    try:
        local = datetime.datetime(year, month, day, hour, min(minute, 59), min(second, 59), tzinfo=zone)
        std = local.utcoffset() - local.dst()
        offset = -int(std.total_seconds())
    except (ValueError, TypeError, OverflowError):
        offset = 0
    if offset == 0 and not _has_dst(zone, year):
        return ts
    return ts + offset - (3600 if is_dst else 0)

def _has_dst(zone:datetime.tzinfo, year:int) -> bool:
    for month in (1, 7):
        if datetime.datetime(year, month, 1, tzinfo=zone).dst():
            return True
    return False

#
# Interpolation (gridlabd source/interpolate.cpp)
#
def lerp(t:float, x0:float, y0:float, x1:float, y1:float) -> float:
    """gridlabd `interpolate_linear()`"""
    return y0 + (t - x0) * (y1 - y0) / (x1 - x0)

def qerp(t:float, x0:float, y0:float, x1:float, y1:float, x2:float, y2:float) -> float: # pylint: disable=too-many-arguments,too-many-positional-arguments
    """gridlabd `interpolate_quadratic()`, including its `/2*h*h`"""
    if x1-x0 != x2-x1:
        gl_error("interpolate_quadratic: this only works given three equally spaced points")
        return 0.0
    h = x1 - x0
    c = y0
    b = (y1 - y0)/h
    a = (y2 - 2*y1 + y0) / 2*h*h
    return a * (t - x0) * (t - x1) + b * (t - x0) + c

#
# C library work-alikes
#
_FLOAT = re.compile(r"[-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan(?:\([^)]*\))?)", re.IGNORECASE)
_DIRECTIVE = re.compile(r"%(\*?)(\d*)(hh|h|ll|l|L)?([diuoxXsScfgeEaG%]|\[\^?\]?[^\]]*\])")
_SPACE = re.compile(r"\s*")
_INTEGERS = {"d": r"[-+]?\d+", "i": r"[-+]?\d+", "u": r"[-+]?\d+", "o": r"[-+]?[0-7]+",
    "x": r"[-+]?(?:0[xX])?[0-9a-fA-F]+", "X": r"[-+]?(?:0[xX])?[0-9a-fA-F]+"}
_BASES = {"d": 10, "i": 10, "u": 10, "o": 8, "x": 16, "X": 16}
_FORMATS: dict[str,list[tuple]] = {}

def _compile(fmt_:str) -> list[tuple]:
    """Operations of a `sscanf()` format: `("space",)`, `("char", c)`, or
    `("conv", kind, skip, width, pattern)`"""
    ops: list[tuple] = []
    i = 0
    while i < len(fmt_):
        ch = fmt_[i]
        if ch.isspace():
            ops.append(("space",))
            i += 1
            continue
        if ch != "%":
            ops.append(("char", ch))
            i += 1
            continue
        match = _DIRECTIVE.match(fmt_, i)
        if match is None:
            ops.append(("stop",))
            break
        i = match.end()
        skip, width, _, conv = match.groups()
        width_ = int(width) if width else None
        limit = "" if width_ is None else f"{{1,{width_}}}"
        if conv == "%":
            ops.append(("percent",))
        elif conv.startswith("["):
            body = conv[1:-1]
            negate = body.startswith("^")
            if negate:
                body = body[1:]
            chars = "".join("\\" + c if c in "\\]^[" else c for c in body)
            pattern = re.compile(f"[{'^' if negate else ''}{chars}]{limit or '+'}")
            ops.append(("conv", "set", bool(skip), width_, pattern))
        elif conv == "c":
            ops.append(("conv", "c", bool(skip), width_ or 1, None))
        elif conv in ("s", "S"):
            ops.append(("conv", "s", bool(skip), width_, re.compile(r"\S" + (limit or "+"))))
        elif conv in _INTEGERS:
            ops.append(("conv", conv, bool(skip), width_, re.compile(_INTEGERS[conv])))
        else:
            ops.append(("conv", "f", bool(skip), width_, _FLOAT))
    return ops

def sscanf(text:str, fmt_:str) -> tuple[int,list[Any]]: # pylint: disable=too-many-branches
    """C `sscanf()`: the number of values assigned (-1 when the input ends
    before the first conversion) and the values (`int`, `float`, or `str`)

    Supports whitespace, literal characters, and `%[*][width][h|l]` with
    `d`, `i`, `u`, `o`, `x`, `s`, `c`, `f`, `g`, `e`, and `[...]` sets.
    """
    ops = _FORMATS.get(fmt_)
    if ops is None:
        ops = _FORMATS[fmt_] = _compile(fmt_)
    pos = 0
    count = 0
    values: list[Any] = []
    n = len(text)
    def ended() -> tuple[int,list[Any]]:
        return (-1 if count == 0 else count), values
    for op in ops:
        kind = op[0]
        if kind == "space":
            pos = _SPACE.match(text, pos).end()
            continue
        if kind == "char":
            if pos >= n:
                return ended()
            if text[pos] != op[1]:
                return count, values
            pos += 1
            continue
        if kind == "stop":
            return count, values
        if kind == "percent":
            pos = _SPACE.match(text, pos).end()
            if pos < n and text[pos] == "%":
                pos += 1
                continue
            return count, values
        _, conv, skip, width, pattern = op
        if conv not in ("set", "c"):
            pos = _SPACE.match(text, pos).end()
        if pos >= n:
            return ended()
        if conv == "c":
            if pos + width > n:
                return ended()
            value: Any = text[pos:pos+width]
            pos += width
        else:
            end = n if width is None else min(n, pos+width)
            found = pattern.match(text, pos, end)
            if found is None:
                return count, values
            token = found.group(0)
            pos = found.end()
            if conv in ("set", "s"):
                value = token
            elif conv == "f":
                value = float(token.split("(")[0])
            else:
                value = int(token, _BASES[conv]) if conv in "oxX" else int(token)
        if not skip:
            values.append(value)
            count += 1
    return count, values

def atoi(text:str) -> int:
    """C `atoi()`: the leading integer of the text, else 0"""
    match = re.match(r"\s*([-+]?\d+)", text)
    return int(match.group(1)) if match else 0

def atof(text:str) -> float:
    """C `atof()`: the leading number of the text, else 0"""
    match = re.match(r"\s*(" + _FLOAT.pattern + ")", text, re.IGNORECASE)
    return float(match.group(1).split("(")[0]) if match else 0.0

class Tokenizer: # pylint: disable=too-few-public-methods
    """C `strtok_r()` over one string; each call may use other delimiters"""

    def __init__(self, text:str):
        self.text = text
        self.pos = 0

    def next(self, delimiters:str) -> str|None:
        """Next token, or `None`"""
        text, pos = self.text, self.pos
        while pos < len(text) and text[pos] in delimiters:
            pos += 1
        if pos >= len(text):
            self.pos = pos
            return None
        end = pos
        while end < len(text) and text[end] not in delimiters:
            end += 1
        self.pos = end + 1 if end < len(text) else end
        return text[pos:end]

def int16(value:int) -> int:
    """A value stored in a C `short`"""
    return (value + 0x8000) % 0x10000 - 0x8000

def float32(value:float) -> float:
    """A value stored in a C `float`"""
    import struct # pylint: disable=import-outside-toplevel
    return struct.unpack("f", struct.pack("f", value))[0]

def c_round(value:float) -> float:
    """C `round()`: halves away from zero"""
    return math.floor(abs(value) + 0.5) * (1 if value >= 0 else -1)

#
# Files
#
def read_lines(path:str, size:int) -> list[str]:
    """Lines of a file as C `fgets(buffer, size, fp)` reads them: lines
    longer than `size-1` characters come in parts"""
    with open(path, "r", encoding="latin-1", newline="") as fh:
        text = fh.read()
    lines = []
    for line in text.splitlines(keepends=True):
        while len(line) > size - 1:
            lines.append(line[:size-1])
            line = line[size-1:]
        if line:
            lines.append(line)
    return lines

def to_timestamp(model:Any, text:str) -> int:
    """Convert a timestamp written by `arras` (also with a trailing time
    zone abbreviation of the model's time zone, as object `clock` values
    are written) to seconds

    Exceptions
    ----------
    - `ClimateError`: the text is not a valid timestamp
    """
    globs = model.globals
    text = str(text).strip().strip("'\"").strip()
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
    raise ClimateError(f"'{text}' is not a valid timestamp") from error
