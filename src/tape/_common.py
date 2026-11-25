# pylint: disable=line-too-long
"""@private Helpers shared by the tape classes

Runner access and messages (gridlabd `gl_error()`, `gl_warning()`, ...),
the state that each object keeps between its event handlers, C `printf`
formats, local time as the gridlabd core writes and reads it
(`gl_strtime()`, `gl_mktime()`), and `Prop`, a property of an object or a
global variable read and written as the core's `gl_get_value()` and
`gl_set_value()` do it.
"""

import re
import math
import cmath
import weakref
import datetime
import calendar
from typing import Any

from arras.exceptions import ArrasException
from arras.model import HEADER, ModelError
from arras.oclass import Class

MODULE = "tape"
"""Module name"""

TS_ZERO = 0
"""Timestamp printed as `INIT`"""

TS_NEVER = (1 << 63) - 1
"""Timestamp printed as `NEVER`"""

TS_INVALID = -1
"""Timestamp that reports a failure"""

TS_INIT, TS_OPEN, TS_DONE, TS_ERROR = range(4)
"""Tape status (gridlabd `TAPESTATUS`)"""

TRL_UNKNOWN, TRL_PRINCIPLE, TRL_CONCEPT, TRL_PROOF, TRL_STANDALONE, TRL_INTEGRATED, \
    TRL_DEMONSTRATED, TRL_PROTOTYPE, TRL_QUALIFIED, TRL_PROVEN = range(10)
"""Technology readiness levels (gridlabd `TECHNOLOGYREADINESSLEVEL`)"""

OF_DELTAMODE = 0x40
"""Object flag that asks for deltamode (gridlabd `OF_DELTAMODE`)"""

OBJECT_FLAGS = {"NONE": 0, "HASPLC": 0x1, "LOCKED": 0x2, "RERANKED": 0x4000, "RECALC": 0x8,
    "DELTAMODE": OF_DELTAMODE, "QUIET": 0x10000, "WARNING": 0x20000, "DEBUG": 0x40000,
    "VERBOSE": 0x80000}
"""Keywords of the object `flags` header (gridlabd `oflags[]`)"""

class TapeError(ArrasException):
    """Tape module error"""

#
# Runner access and messages
#
def runner():
    """Runner of the calling thread

    Exceptions
    ----------
    - `TapeError`: no simulation is running in the calling thread
    """
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is None:
        raise TapeError("tape handlers run only during an arras.runner.Runner simulation")
    return current

def gl_error(message:str) -> None:
    """`gl_error()`: an error line; the run goes on but ends with exit
    code `RUNERR`, as gridlabd's `output_error()` sets it"""
    from arras import exitcodes # pylint: disable=import-outside-toplevel
    current = runner()
    current.error(message)
    current.setexitcode(exitcodes.RUNERR)

def gl_warning(message:str) -> None:
    """`gl_warning()`: a warning line"""
    runner().warning(message)

def gl_verbose(message:str) -> None:
    """`gl_verbose()`: a verbose line"""
    runner().verbose(message)

def gl_output(message:str) -> None:
    """`gl_output()`: an output line"""
    runner().output(message)

def object_flags(model:Any, name:str) -> int:
    """Flag bits of an object's `flags` header"""
    text = model.objects[name].get("flags")
    if text in (None, ""):
        return 0
    text = str(text).strip()
    if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", text):
        return int(text, 0)
    bits = 0
    for key in text.split("|"):
        bits |= OBJECT_FLAGS.get(key.strip(), 0)
    return bits

def object_label(model:Any, name:str) -> str:
    """`obj->name` as C prints it with `obj->name?obj->name:"(unnamed)"`"""
    obj = model.objects[name]
    return "(unnamed)" if name == f"{obj.oclass.name}:{obj.id}" else name

def is_named(model:Any, name:str) -> bool:
    """`True` when the object has a `name` header (not `CLASS:ID`)"""
    obj = model.objects[name]
    return name != f"{obj.oclass.name}:{obj.id}"

def parent_of(model:Any, name:str) -> str|None:
    """Name of the object's parent, or `None`"""
    parent = model.objects[name].get("parent")
    return parent if parent else None

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

def all_states(model:Any) -> dict[str,Any]:
    """States of the objects of a model, keyed on object name"""
    return _STATE.get(model, {})

#
# C formats and conversions
#
def c_format(spec:str) -> str:
    """A C `printf` format as a Python `%` format (`%lg` is `%g`, `%lld`
    is `%d`, `%i` is `%d`)"""
    spec = re.sub(r"%([-+ #0-9.*]*)(?:ll|l|h|hh|L|z)?([diouxXeEfgGcs])", r"%\1\2", spec)
    return spec.replace("%i", "%d")

def hexfloat(value:float, precision:int|None=None, upper:bool=False, flags:str="") -> str: # pylint: disable=too-many-locals
    """C `printf("%a")` of a double: `[-]0xh.hhhp[+-]d`, rounded to
    `precision` hexadecimal digits (all needed digits when `None`)"""
    if math.isnan(value) or math.isinf(value):
        text = ("-" if value < 0 else "") + ("inf" if math.isinf(value) else "nan")
    else:
        sign = "-" if math.copysign(1.0, value) < 0 else ("+" if "+" in flags else (" " if " " in flags else ""))
        value = abs(value)
        if value == 0:
            lead, digits, exponent = 0, "", 0
        else:
            mantissa, exponent = math.frexp(value)
            fraction = int(mantissa*2*(1 << 52)) - (1 << 52)
            lead = 1
            exponent -= 1
            digits = f"{fraction:013x}"
            if precision is not None and precision < 13:
                scaled = fraction >> (4*(13 - precision))
                rest = fraction & ((1 << (4*(13 - precision))) - 1)
                half = 1 << (4*(13 - precision) - 1)
                if rest > half or (rest == half and scaled & 1):
                    scaled += 1
                if precision and scaled >> (4*precision):
                    lead, scaled = lead + 1, scaled & ((1 << (4*precision)) - 1)
                elif not precision and scaled:
                    lead, scaled = lead + 1, 0
                digits = f"{scaled:0{precision}x}" if precision else ""
            elif precision is None:
                digits = digits.rstrip("0")
        if precision is not None and len(digits) < precision:
            digits += "0"*(precision - len(digits))
        point = "." if digits or "#" in flags else ""
        text = f"{sign}0x{lead}{point}{digits}p{exponent:+d}"
    return text.upper() if upper else text

def cprintf(spec:str, *args:Any) -> str:
    """C `snprintf()` of a format and arguments"""
    text = c_format(spec)
    if re.search(r"%[-+ #0-9.]*[aA]", text):
        values = list(args)
        def hexa(match:re.Match) -> str:
            flags, prec, conv = match.group(1), match.group(2), match.group(3)
            return hexfloat(float(values.pop(0)), int(prec) if prec is not None else None, conv == "A", flags).replace("%", "%%")
        parts = re.split(r"(%[-+ #0-9.]*[a-zA-Z%])", text)
        out = []
        for part in parts:
            match = re.fullmatch(r"%([-+ #0]*)(?:\d*)(?:\.(\d+))?([aA])", part)
            if match:
                out.append(hexa(match))
            elif part.startswith("%") and part != "%%" and len(part) > 1:
                out.append(part % values.pop(0))
            else:
                out.append(part.replace("%%", "%"))
        return "".join(out)
    try:
        return text % args
    except (TypeError, ValueError) as err:
        raise TapeError(f"format '{spec}' is not valid for {args!r}") from err

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

def atoi(text:str) -> int:
    """C `atoi()`: the leading integer of the text, else 0"""
    match = re.match(r"\s*([-+]?\d+)", text)
    return int(match.group(1)) if match else 0

def strtok(text:str, delimiters:str) -> list[str]:
    """The tokens C `strtok()` returns: runs of characters not in
    `delimiters`"""
    return [x for x in re.split("[" + re.escape(delimiters) + "]+", text) if x]

def find_unit(name:str) -> Any:
    """The unit named `name` (gridlabd `gl_find_unit()`), or `None`"""
    try:
        return Class.get_units().find(name)
    except ArrasException:
        return None

def convert(value:float, from_unit:str, to_unit:str) -> float|None:
    """`value` converted from one unit to another (gridlabd
    `gl_convert_ex()`), or `None` when the units are not compatible"""
    if from_unit == to_unit:
        return value
    try:
        return Class.get_units().convert(value, from_unit, to_unit)
    except ArrasException:
        return None

def unit_scale(from_unit:str, to_unit:str) -> float|None:
    """Factor that converts `from_unit` to `to_unit`, or `None`"""
    zero = convert(0.0, from_unit, to_unit)
    one = convert(1.0, from_unit, to_unit)
    if zero is None or one is None:
        return None
    return one - zero

#
# Time
#
def timezone(model:Any) -> datetime.tzinfo:
    """Time zone of the model"""
    return model.globals.timezone()

def strtime(model:Any, ts:int, nanoseconds:int=0) -> str:
    """Local date and time of `ts` as the core's `gl_localtime()` and
    `gl_strtime()` write it, following the `dateformat` global"""
    local = datetime.datetime.fromtimestamp(ts, timezone(model))
    tzname = local.strftime("%Z")
    style = model.globals.getvalue("dateformat")
    if style == "ISO8601":
        offset = int(local.utcoffset().total_seconds())
        sign = "+" if offset >= 0 else "-"
        frac = f".{nanoseconds//1000:06d}" if nanoseconds else ""
        return local.strftime("%Y-%m-%dT%H:%M:%S") + f"{frac}{sign}{abs(offset)//3600:02d}:{abs(offset)//60%60:02d}"
    frac = f".{nanoseconds:09d}" if nanoseconds else ""
    if style == "US":
        return local.strftime("%m-%d-%Y %H:%M:%S") + f"{frac} {tzname}"
    if style == "EURO":
        return local.strftime("%d-%m-%Y %H:%M:%S") + f"{frac} {tzname}"
    return local.strftime("%Y-%m-%d %H:%M:%S") + f"{frac} {tzname}"

_ZONES = {"UTC": 0, "GMT": 0, "Z": 0}

def mktime(model:Any, fields:tuple[int,int,int,int,int,int], tz:str="") -> int:
    """Timestamp of a date and time (gridlabd `gl_mktime()`): in the time
    zone named by the abbreviation `tz` when it is `UTC`, `GMT`, or the
    standard or daylight saving abbreviation of the model's time zone,
    else in the model's local time; `TS_INVALID` when a field is out of
    range"""
    year, month, day, hour, minute, second = fields
    try:
        naive = datetime.datetime(year, month, day, hour, minute, second)
    except (ValueError, OverflowError):
        return TS_INVALID
    if tz in _ZONES:
        return calendar.timegm(naive.timetuple())
    zone = timezone(model)
    if tz:
        for fold in (0, 1):
            local = naive.replace(tzinfo=zone, fold=fold)
            if local.tzname() == tz:
                return int(local.timestamp())
        for month_ in (1, 7):
            other = datetime.datetime(year, month_, 1, tzinfo=zone)
            if other.tzname() == tz:
                offset = other.utcoffset()
                return calendar.timegm(naive.timetuple()) - int(offset.total_seconds())
    return int(naive.replace(tzinfo=zone).timestamp())

def localtime(model:Any, ts:int) -> datetime.datetime:
    """Local date and time of `ts` in the model's time zone"""
    return datetime.datetime.fromtimestamp(ts, timezone(model))

def to_timestamp(model:Any, text:str) -> int:
    """A timestamp property value in seconds (also with a trailing time
    zone abbreviation, as `arras` writes object `clock` values)

    Exceptions
    ----------
    - `TapeError`: the text is not a valid timestamp
    """
    text = str(text).strip().strip("'\"").strip()
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d{1,2})(?:\.\d*)?\s*([A-Za-z]{1,5})?", text)
    if match:
        fields = tuple(int(x) for x in match.groups()[:6])
        result = mktime(model, fields, match.group(7) or "") # type: ignore[arg-type]
        if result != TS_INVALID:
            return result
    try:
        return model.globals.timestamp_from_string(text)
    except ArrasException as err:
        raise TapeError(f"'{text}' is not a valid timestamp") from err

def clock(model:Any) -> int:
    """The clock of the run (the start time during initialization)"""
    now = runner().clock
    if now is None:
        now = model.globals.getvalue("clock")
    return int(now or 0)

#
# Values
#
def to_double(text:str, unit:str|None=None, what:str="value") -> float:
    """Convert text to a double as `convert_to_double()` does: a number
    with an optional unit, converted to `unit`

    Exceptions
    ----------
    - `TapeError`: the text is not a number, or the unit cannot be
      converted
    """
    text = str(text).strip()
    if text == "":
        return 0.0
    if re.match(r"[-+]?nan", text, re.IGNORECASE):
        return math.nan
    result = scan_double(text)
    if result is None:
        raise TapeError(f"{what}: '{text}' is not a number")
    value, rest = result
    rest = rest.strip().split()
    if rest and rest[0] != unit:
        if unit is None:
            raise TapeError(f"{what}: unit given to unitless property")
        converted = convert(value, rest[0], unit)
        if converted is None:
            raise TapeError(f"{what}: unit conversion failed")
        value = converted
    return value

def to_complex(text:str, unit:str|None=None, what:str="value") -> tuple[complex,str]:
    """Convert text to a complex number and its notation (`i`, `j`, `d`,
    `r`) as `convert_to_complex()` does, with an optional unit

    Exceptions
    ----------
    - `TapeError`: the text is not a complex number, or the unit cannot
      be converted
    """
    text = str(text).strip()
    if text == "":
        return complex(0, 0), "i"
    first = scan_double(text)
    if first is None:
        raise TapeError(f"{what}: complex number '{text}' format is not valid")
    real, rest = first
    second = scan_double(rest) if rest[:1] in "+-" else None
    notation = "i"
    value = complex(real, 0)
    if second is not None:
        imag, rest = second
        if not rest or rest[0] not in "ijdr":
            raise TapeError(f"{what}: complex number '{text}' format is not valid")
        notation, rest = rest[0], rest[1:]
        if notation == "d":
            value = cmath.rect(real, imag*math.pi/180)
        elif notation == "r":
            value = cmath.rect(real, imag)
        else:
            value = complex(real, imag)
    rest = rest.strip().split()
    if rest and rest[0] != unit:
        if unit is None:
            raise TapeError(f"{what}: unit given to unitless property")
        scale = unit_scale(rest[0], unit)
        if scale is None:
            raise TapeError(f"{what}: unit conversion failed")
        value *= scale
    return value, notation

def angle(value:complex) -> float:
    """gridlabd `complex::Arg()`: angle in radians"""
    return math.atan2(value.imag, value.real)

def fmt(value:float) -> str:
    """Text of a float as `arras.model` writes it (15 significant digits)"""
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return repr(value)
    return repr(float(f"{value:.15g}") + 0.0)

INTEGER_TYPES = ("int16", "int32", "int64")
"""Integer property types"""

DOUBLE_TYPES = ("double", "real", "float", "randomvar", "loadshape")
"""Property types read as a `double`"""

COMPLEX_TYPES = ("complex", "enduse")
"""Property types read as a `complex`"""

class Prop: # pylint: disable=too-many-instance-attributes
    """A property of an object, or a global variable when `name` is `None`
    (gridlabd `PROPERTY` and `gl_get_value()`/`gl_set_value()`)

    Attributes
    ----------
    - `model`: the model
    - `name`: object name, or `None` for a global variable
    - `prop`: property name
    - `part`: `real` or `imag` for a part of a complex property, else `None`
    - `ptype`: property type (`double` for a complex part), or `None` when
      the property is not found
    - `native`: the property's own unit, or `None`
    - `unit`: the unit used to read and write values (the property's unit
      unless another is given)
    - `keywords`: keyword values of an `enumeration` or `set`
    - `charset`: the `set` property has single-character keywords
    """

    def __init__(self, model:Any, name:str|None, prop:str, part:str|None=None, unit:Any="native"):
        self.model = model
        self.name = name
        self.prop = prop
        self.part = part
        self.ptype: str|None = None
        self.native: str|None = None
        self.keywords: dict[str,int] = {}
        self.charset = False
        if name is None:
            var = model.globals.find(prop)
            if var is not None:
                self.ptype = var.ptype
                self.native = getattr(var, "unit", None)
                self.keywords = dict(getattr(var, "keywords", None) or {})
        elif name in model.objects:
            if prop in HEADER and prop != "class":
                self.ptype = {"name": "char1024", "flags": "set", "guid": "char1024"}.get(prop, HEADER[prop])
                if prop == "flags":
                    self.keywords = dict(OBJECT_FLAGS)
            elif prop == "id":
                self.ptype = "int64"
            else:
                spec = model.objects[name].oclass.find_property(prop)
                if spec is not None:
                    self.ptype = spec.ptype
                    self.native = spec.unit
                    self.keywords = dict(spec.keywords)
                    self.charset = spec.has_flag("CHARSET")
        if part is not None and self.ptype is not None:
            self.ptype = "double"
        self.unit = self.native if unit == "native" else unit

    @property
    def is_valid(self) -> bool:
        """`True` when the property exists"""
        return self.ptype is not None

    @property
    def label(self) -> str:
        """Property name with its part"""
        return f"{self.prop}.{self.part}" if self.part else self.prop

    def text(self) -> str:
        """Value as stored in the model (text)"""
        if self.name is None:
            value = self.model.globals.get(self.prop)
        elif self.prop == "id":
            value = str(self.model.objects[self.name].id)
        elif self.prop == "name":
            value = self.name
        else:
            value = self.model.get_property(self.name, self.prop)
        return "" if value is None else str(value)

    def complex_value(self) -> tuple[complex,str]:
        """Value of a complex property in its own unit, with its notation"""
        what = f"{self.name or 'global'}.{self.prop}"
        if self.name is None and self.prop == "clock":
            return complex(0, 0), "i"
        return to_complex(self.text(), self.native, what)

    def double(self) -> float:
        """Value as a double in the property's own unit (the part of a
        complex property; the number of an integer, enumeration, set,
        bool, or timestamp property)"""
        # pylint: disable=too-many-return-statements
        what = f"{self.name or 'global'}.{self.prop}"
        if self.part is not None:
            value, _ = self.complex_value()
            return value.real if self.part == "real" else value.imag
        if self.ptype in DOUBLE_TYPES:
            text = self.text()
            try:
                return to_double(text, self.native, what)
            except TapeError:
                return self._dynamic(text)
        if self.ptype in COMPLEX_TYPES:
            return abs(self.complex_value()[0])
        return float(self.integer())

    def _dynamic(self, text:str) -> float:
        """Value of a double whose text is not a number (a `randomvar`
        specification or a transform): its `value` if it has one, else 0"""
        match = re.search(r"\bvalue\s*:\s*(" + _LG + ")", text)
        return float(match.group(1)) if match else 0.0

    def integer(self) -> int: # pylint: disable=too-many-return-statements
        """Value of an integer, enumeration, set, bool, or timestamp
        property"""
        text = self.text().strip()
        if self.ptype == "bool":
            return 1 if text.upper() == "TRUE" or (text.lstrip("-").isdigit() and int(text) != 0) else 0
        if self.ptype == "timestamp":
            if text in ("", "INIT"):
                return 0
            if text == "NEVER":
                return TS_NEVER
            return to_timestamp(self.model, text)
        if self.ptype in ("enumeration", "set") and self.keywords:
            if text in self.keywords:
                return self.keywords[text]
            if self.ptype == "set" and text and not re.fullmatch(r"[-+]?(0[xX][0-9a-fA-F]+|\d+)", text):
                parts = text.split("|") if "|" in text else (list(text) if self.charset and text not in self.keywords else [text])
                return sum(self.keywords.get(x, 0) for x in parts)
        if text == "":
            return 0
        try:
            return int(text, 0)
        except ValueError:
            return int(atof(text))

    def to_string(self, line_unit:str|None="native") -> str: # pylint: disable=too-many-branches
        """Value as `gl_get_value()` writes it (`class_property_to_string()`):
        a `double` with the `double_format` global and its unit, converted
        to `line_unit` (the read unit by default), a `complex` with the
        `complex_format` global, others as the core converts them

        Exceptions
        ----------
        - `TapeError`: the value cannot be converted
        """
        # pylint: disable=too-many-return-statements
        globs = self.model.globals
        unit = self.unit if line_unit == "native" else line_unit
        if self.ptype in DOUBLE_TYPES:
            value = self.double()
            if math.isnan(value):
                return "NAN"
            if unit is not None and self.native is not None and unit != self.native:
                converted = convert(value, self.native, unit)
                if converted is None:
                    raise TapeError(f"unable to convert unit '{self.native}' to '{unit}' for property '{self.prop}'")
                value = converted
            text = cprintf(globs.get("double_format") or "%+lg", value)
            return text + (f" {unit}" if unit else "")
        if self.ptype in COMPLEX_TYPES:
            value, notation = self.complex_value()
            scale = 1.0
            if unit is not None and self.native is not None and unit != self.native:
                scale = unit_scale(self.native, unit) or 1.0
            cfmt_ = globs.get("complex_format") or "%+lg%+lg%c"
            mode = globs.get("complex_output_format") or "DEFAULT"
            if mode == "RECT":
                notation = "j"
            elif mode == "POLAR_DEG":
                notation = "d"
            elif mode == "POLAR_RAD":
                notation = "r"
            if notation in "dr":
                arg = angle(value)
                text = cprintf(cfmt_, abs(value)*scale, arg*180/math.pi if notation == "d" else arg, notation)
            else:
                text = cprintf(cfmt_, value.real*scale, value.imag*scale, notation)
            return text + (f" {unit}" if unit else "")
        if self.ptype in INTEGER_TYPES:
            return str(self.integer())
        if self.ptype == "bool":
            return "TRUE" if self.integer() else "FALSE"
        if self.ptype == "timestamp":
            if self.name is None and self.prop == "clock":
                return globs.timestamp_to_string(clock(self.model))
            return globs.timestamp_to_string(self.integer())
        if self.ptype == "enumeration":
            value = self.integer()
            for key, item in self.keywords.items():
                if item == value:
                    return key
            return str(value)
        if self.ptype == "set":
            return self._set_string(self.integer())
        return self.text()

    def _set_string(self, value:int) -> str:
        """`convert_from_set()`"""
        words = []
        for key, item in self.keywords.items():
            if (value != 0 and item != 0 and item & value == item) or (item == 0 and value == 0):
                value &= ~item
                words.append(key)
        return ("" if self.charset else "|").join(words)

    def set(self, text:str) -> bool:
        """Set the value from text as `gl_set_value()` does, converting a
        value with a unit to the property's unit and a value without a
        unit from the write unit (`unit`); `False` (with an error line)
        when the value is not valid"""
        what = f"{self.name}.{self.label}"
        try:
            if self.part is not None:
                value, notation = self.complex_value()
                number = to_double(text, self.native, what) if self.unit == self.native else self._from_unit(text)
                value = complex(number, value.imag) if self.part == "real" else complex(value.real, number)
                self.model.set_property(self.name, self.prop, f"{fmt(value.real)}{fmt(value.imag) if value.imag < 0 else '+' + fmt(value.imag)}{notation if notation in 'ij' else 'j'}")
                return True
            if self.ptype in DOUBLE_TYPES and self.unit != self.native and self.native is not None:
                self.model.set_property(self.name, self.prop, f"{fmt(self._from_unit(text))} {self.native}")
                return True
            if self.ptype in COMPLEX_TYPES and self.unit != self.native and self.native is not None:
                rest = text.strip()
                if not re.search(r"[ijdr]\s+\S+$|^\S*\d\s+[A-Za-z]", rest):
                    text = f"{rest} {self.unit}"
            self.model.set_property(self.name, self.prop, text.strip())
            return True
        except (ModelError, TapeError) as err:
            gl_error(f"unable to set {what} to '{text.strip()}': {err}")
            return False

    def _from_unit(self, text:str) -> float:
        """A double read from text, converted from the write unit (or the
        unit given in the text) to the property's unit"""
        result = scan_double(text.strip())
        if result is None:
            raise TapeError(f"'{text.strip()}' is not a number")
        value, rest = result
        rest = rest.strip().split()
        source = rest[0] if rest else self.unit
        if source is None or self.native is None or source == self.native:
            return value
        converted = convert(value, source, self.native)
        if converted is None:
            raise TapeError(f"unable to convert '{source}' to '{self.native}'")
        return converted
