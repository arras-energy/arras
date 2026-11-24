# pylint: disable=line-too-long
"""@private Property comparisons and parts

Reproduces the comparison that the `assert` class asks of the gridlabd core:
`property_compare_basic_str()` and `property_compare_basic()`
(`source/property.cpp`), the operators of `source/compare.cpp`, and the
`get_part` functions of the property types (`complex_get_part()`,
`timestamp_get_part()`, `object_get_part()`, `enduse_get_part()`,
`random_get_part()`).
"""

import math
import datetime
from typing import Any, Callable

from ._common import AssertError, Target, to_double, to_complex, to_timestamp, angle, atof, \
    TS_ZERO, TS_NEVER, runner

TCOP_EQ, TCOP_LE, TCOP_GE, TCOP_NE, TCOP_LT, TCOP_GT, TCOP_IN, TCOP_NI = range(8)
"""Comparison operators (gridlabd `PROPERTYCOMPAREOP`)"""

RELATIONS = {"==": TCOP_EQ, "<": TCOP_LT, "<=": TCOP_LE, ">": TCOP_GT, ">=": TCOP_GE,
    "!=": TCOP_NE, "inside": TCOP_IN, "outside": TCOP_NI}
"""Keywords of the `assert` `relation` property, in the order gridlabd
publishes them"""

def _float_op(op:int, x:float, a:float, b:float|None) -> bool:
    """`COMPAREOPF`: `==` and `!=` use `b` as a tolerance when it is given"""
    # pylint: disable=too-many-return-statements
    if op == TCOP_EQ:
        return x == a if b is None else abs(x-a) <= b
    if op == TCOP_NE:
        return x != a if b is None else abs(x-a) > b
    if op == TCOP_LE:
        return x <= a
    if op == TCOP_GE:
        return x >= a
    if op == TCOP_LT:
        return x < a
    if op == TCOP_GT:
        return x > a
    inside = a <= x and b is not None and x <= b
    return inside if op == TCOP_IN else not inside

def _ordered_op(op:int, x:Any, a:Any, b:Any) -> bool:
    """`COMPAREOPI` and `COMPAREOPS`: ordered comparison, `b` only bounds
    `inside` and `outside`"""
    # pylint: disable=too-many-return-statements
    if op == TCOP_EQ:
        return x == a
    if op == TCOP_NE:
        return x != a
    if op == TCOP_LE:
        return x <= a
    if op == TCOP_GE:
        return x >= a
    if op == TCOP_LT:
        return x < a
    if op == TCOP_GT:
        return x > a
    inside = a <= x and b is not None and x <= b
    return inside if op == TCOP_IN else not inside

def _int32(value:int) -> int:
    """C `(signed)` cast of an integer: its low 32 bits, signed"""
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value

def _uint16(value:int) -> int:
    """`(signed)*(uint16*)` of an `int16`: its low 16 bits, unsigned"""
    return value & 0xFFFF

def _scan_int(text:str, what:str) -> int:
    """C `sscanf("%d")`: the leading integer

    Exceptions
    ----------
    - `AssertError`: no integer is read (an empty text is a conversion
      error that gridlabd reports)
    """
    text = text.strip()
    digits = len(text) - len(text.lstrip("+-"))
    end = digits
    while end < len(text) and text[end].isdigit():
        end += 1
    if end == digits or digits > 1:
        raise AssertError(f"{what}: '{text}' is not an integer")
    return int(text[:end])

def _scan_char(text:str, size:int) -> str:
    """`convert_to_charN()`: up to `size` characters, to a closing quote
    when the text starts with one, else to a newline"""
    if text.startswith('"'):
        return text[1:].split('"', 1)[0][:size]
    return text.split("\n", 1)[0][:size]

def _keyword_value(target:Target, text:str, what:str) -> int:
    """`convert_to_enumeration()`: a keyword, a hex or decimal number"""
    text = text.strip()
    if text in target.keywords:
        return target.keywords[text]
    if text.startswith("0x"):
        return int(text[2:], 16)
    if text[:1].isdigit():
        return _scan_int(text, what)
    raise AssertError(f"keyword '{text}' is not valid for property {target.prop}")

def _set_value(target:Target, text:str, what:str) -> int:
    """`convert_to_set()`: keywords separated by `|`, characters of a
    `CHARSET` set, or a number"""
    text = text.strip()
    if text.lower().startswith("0x"):
        return int(text[2:], 16)
    if text[:1].isdigit():
        return _scan_int(text, what)
    keys = list(text) if target.charset and "|" not in text else [x for x in text.split("|") if x]
    value = 0
    for key in keys:
        found = next((v for k, v in target.keywords.items() if (k[0] == key if target.charset and "|" not in text else k == key)), None)
        if found is None:
            raise AssertError(f"set member '{key}' is not a keyword of property {target.prop}")
        value |= found
    return value

def _bool_value(text:str, what:str) -> bool:
    """`convert_to_boolean()`"""
    text = text.strip()
    word = ""
    for char in text:
        if not char.isalpha():
            break
        word += char
    if word:
        if word.upper() in ("TRUE", "FALSE"):
            return word.upper() == "TRUE"
        raise AssertError(f"{what}: '{text}' is not a boolean")
    return _scan_int(text, what) != 0

def _object_value(model:Any, text:str) -> str|None:
    """`convert_to_object()`: the object named, else `None` (`"0"` and
    names not found give `None`, as in gridlabd)"""
    text = text.strip()
    if text == "0":
        return None
    if text.startswith('"'):
        text = text[1:].split('"', 1)[0]
    elif ":" in text:
        cname, _, oid = text.partition(":")
        for name, obj in model.objects.items():
            if str(obj.id) == oid and obj.oclass.name == cname:
                return name
        return None
    return text if text in model.objects else None

def _timestamp_value(model:Any, text:str) -> int:
    """`convert_to_timestamp()`"""
    return to_timestamp(model, text)

#
# Converters: (kind, value of the target, value of a comparison string)
#
def _converters(target:Target) -> tuple[str,Callable[[],Any],Callable[[str],Any]]|None:
    """Comparison kind and converters for the target's type, or `None` when
    the type has no `string_to_compare` function"""
    # pylint: disable=too-many-return-statements
    model, ptype, what = target.model, target.ptype, f"{target.owner}.{target.prop}"
    if ptype == "double":
        return "F", target.double, lambda s: to_double(s, target.unit, what)
    if ptype == "complex":
        return "F", lambda: target.complex().real, lambda s: to_complex(s, target.unit, what).real
    if ptype in ("enduse", "randomvar", "loadshape"):
        return "F", lambda: _structure(target)["value"], lambda s: to_double(s, None, what)
    if ptype == "int16":
        return "I", lambda: _uint16(target.integer()), lambda s: _uint16(_scan_int(s, what))
    if ptype in ("int32", "int64"):
        return "I", lambda: _int32(target.integer()), lambda s: _int32(_scan_int(s, what))
    if ptype == "enumeration":
        return "I", lambda: _int32(target.enumeration()), lambda s: _int32(_keyword_value(target, s, what))
    if ptype == "set":
        return "I", lambda: _int32(_set_value(target, target.text(), what) if target.text() else 0), \
            lambda s: _int32(_set_value(target, s, what))
    if ptype == "timestamp":
        return "I", lambda: _int32(_timestamp_value(model, target.text() or "0")), \
            lambda s: _int32(_timestamp_value(model, s))
    if ptype in ("char8", "char32", "char256", "char1024"):
        size = int(ptype[4:])
        return "S", lambda: target.text().encode(), lambda s: _scan_char(s, size).encode()
    if ptype == "string":
        return "S", lambda: target.text().encode(), lambda s: s.encode()
    if ptype == "bool":
        return "B", lambda: _bool_value(target.text() or "FALSE", what), lambda s: _bool_value(s, what)
    if ptype == "object":
        return "O", lambda: _object_value(model, target.text() or "0"), lambda s: _object_value(model, s)
    return None

def compare_with_string(target:Target, op:int, a:str, b:str|None) -> bool:
    """Compare a property with values given as text (gridlabd
    `property_compare_basic_str()` with no part)

    Arguments
    ---------
    - `target`: the property
    - `op`: the operator (`TCOP_*`)
    - `a`: the value
    - `b`: the second value (the tolerance of `==` and `!=` for real
      numbers, the upper bound of `inside` and `outside`), or `None`

    Returns
    -------
    - `bool`: the result; `False` when the type cannot be compared or a
      value cannot be converted (a warning is written)
    """
    spec = _converters(target)
    if spec is None:
        return False
    kind, value, convert = spec
    try:
        xa = convert(a)
    except AssertError as err:
        runner().warning(f"property type '{target.ptype}' cannot compare to value '{a}' ({err})")
        return False
    try:
        xb = convert(b) if b is not None else None
    except AssertError as err:
        runner().warning(f"property type '{target.ptype}' cannot compare to value '{b}' ({err})")
        return False
    if kind in ("B", "O") and op not in (TCOP_EQ, TCOP_NE):
        runner().warning(f"property type '{target.ptype}' does not support comparison operations or parts")
        return False
    x = value()
    if kind == "F":
        return _float_op(op, x, xa, xb)
    return _ordered_op(op, x, xa, xb)

def compare_part(target:Target, op:int, a:str, b:str|None, part:str) -> bool:
    """Compare a part of a property with values given as text (gridlabd
    `gld_property::compare()` with a part): the values are read with
    `atof()` and compared as real numbers

    Returns
    -------
    - `bool`: the result; `False` when the type has no parts (a warning is
      written) or the part is not defined (an error is written)
    """
    x, y = atof(a), atof(b) if b is not None else None
    getter = PARTS.get(target.ptype)
    if getter is None:
        runner().warning(f"property type '{target.ptype}' does not support comparison operations or parts")
        return False
    value = getter(target, part)
    if not math.isfinite(value):
        runner().error(f"part {part} is not defined for type {target.ptype}")
        return False
    return _float_op(op, value, x, y)

#
# Parts
#
def _complex_part(value:complex, name:str) -> float:
    return {
        "real": lambda: value.real,
        "imag": lambda: value.imag,
        "mag": lambda: abs(value),
        "arg": lambda: angle(value),
        "ang": lambda: angle(value)*180/math.pi,
    }.get(name, lambda: math.nan)()

def _local(model:Any, ts:int) -> datetime.datetime|None:
    if ts in (TS_ZERO, TS_NEVER) or ts < 0:
        return None
    return datetime.datetime.fromtimestamp(ts, model.globals.timezone())

def timestamp_part(model:Any, ts:int, name:str) -> float:
    """`timestamp_get_part()`"""
    # pylint: disable=too-many-return-statements
    scale = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}.get(name)
    if scale is not None:
        return ts / scale
    dt = _local(model, ts)
    if dt is None:
        return math.nan
    offset = dt.utcoffset() or datetime.timedelta(0)
    dst = dt.dst() or datetime.timedelta(0)
    return float({
        "second": dt.second,
        "minute": dt.minute,
        "hour": dt.hour,
        "day": dt.day,
        "month": dt.month,
        "year": dt.year,
        "weekday": (dt.weekday()+1) % 7,
        "yearday": dt.timetuple().tm_yday - 1,
        "isdst": int(bool(dst)),
        "nanosecond": 0,
        "tzoffset": -int(offset.total_seconds()),
    }.get(name, math.nan))

def _timestamp_get_part(target:Target, name:str) -> float:
    return timestamp_part(target.model, _timestamp_value(target.model, target.text() or "0"), name)

def _object_get_part(target:Target, name:str) -> float:
    """`object_get_part()` of the object referred to (gridlabd reads the
    header of the reference itself; see the package Differences)"""
    model = target.model
    ref = _object_value(model, target.text() or "0")
    if ref is None:
        return math.nan
    obj = model.objects[ref]
    if name == "id":
        return float(obj.id)
    if name in ("rng_state", "latitude", "longitude", "schedule_skew"):
        text = model.get_property(ref, name)
        return atof(text) if text not in (None, "") else (math.nan if name in ("latitude", "longitude") else 0.0)
    root, _, part = name.partition(".")
    if part and root in ("clock", "valid_to", "in_svc", "out_svc", "heartbeat"):
        text = model.get_property(ref, root)
        default = {"in_svc": "INIT", "out_svc": "NEVER"}.get(root, "0")
        return timestamp_part(model, _timestamp_value(model, text or default), part)
    return math.nan

ENDUSE_COMPLEX = ("total", "energy", "demand", "admittance", "current", "power") + \
    tuple(f"motor{x}.{y}" for x in "ABCD" for y in ("power", "impedance")) + \
    tuple(f"electronic{x}.power" for x in "AB")
"""Complex members of an `enduse` (gridlabd `enduse_get_part()`)"""

ENDUSE_DOUBLE = ("breaker_amps", "impedance_fraction", "current_fraction", "power_fraction",
    "power_factor", "voltage_factor", "heatgain", "heatgain_fraction") + \
    tuple(f"motor{x}.{y}" for x in "ABCD" for y in ("inertia", "v_stall", "v_start", "v_trip", "t_trip")) + \
    tuple(f"electronic{x}.{y}" for x in "AB" for y in ("inertia", "v_trip", "v_start"))
"""Real members of an `enduse` (gridlabd `enduse_get_part()`)"""

def _tuples(text:str) -> dict[str,str]:
    """`name:value;` tuples of an `enduse` or `randomvar` value"""
    result = {}
    for token in text.split(";"):
        if not token.strip():
            continue
        name, sep, value = token.partition(":")
        result[name.strip()] = value.strip() if sep else "1"
    return result

def _structure(target:Target) -> dict[str,Any]:
    """Members of an `enduse`, `randomvar`, or `loadshape` value; `value`
    is the member that the core compares (the first member)"""
    text = target.text().strip()
    number = None
    try:
        number = to_double(text) if text else None
    except AssertError:
        pass
    if target.ptype == "enduse":
        members:dict[str,Any] = {name: complex(0, 0) for name in ENDUSE_COMPLEX}
        members.update({name: 0.0 for name in ENDUSE_DOUBLE})
        if number is None:
            for name, value in _tuples(text).items():
                if name in ("power.real", "power.imag"):
                    power = members["power"]
                    members["power"] = complex(atof(value), power.imag) if name.endswith("real") else complex(power.real, atof(value))
                elif name in ENDUSE_DOUBLE:
                    members[name] = atof(value)
        members["value"] = members["total"].real if number is None else number
        return members
    if target.ptype == "randomvar":
        members = {"a": 0.0, "b": 0.0, "low": 0.0, "high": 0.0, "value": number or 0.0}
        if number is None:
            for name, value in _tuples(text).items():
                if name == "type" and "(" in value:
                    args = value.split("(", 1)[1].rstrip(")").split(",")
                    members["a"] = atof(args[0])
                    members["b"] = atof(args[1]) if len(args) > 1 else 0.0
                elif name in ("min", "max"):
                    members["low" if name == "min" else "high"] = atof(value)
        return members
    return {"value": number or 0.0}

def _enduse_get_part(target:Target, name:str) -> float:
    members = _structure(target)
    if name in ENDUSE_DOUBLE:
        return members[name]
    base, _, part = name.rpartition(".")
    if base in ENDUSE_COMPLEX:
        return _complex_part(members[base], part)
    return math.nan

def _random_get_part(target:Target, name:str) -> float:
    return _structure(target).get(name, math.nan) if name in ("a", "b", "low", "high") else math.nan

PARTS: dict[str,Callable[[Target,str],float]] = {
    "complex": lambda target, name: _complex_part(target.complex(), name),
    "object": _object_get_part,
    "timestamp": _timestamp_get_part,
    "enduse": _enduse_get_part,
    "randomvar": _random_get_part,
}
"""Part functions of the property types that have parts"""
