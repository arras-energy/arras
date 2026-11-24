"""Arras unit manager

The `Units` class converts values from one unit to another the way the
gridlabd core unit manager (`source/unit.cpp`) does. It reads the same unit
definition file, `unitfile.txt`, and derives compound units such as `m/s`
or `kW*h` as they are requested.

Syntax
------

    from arras.units import Units
    units = Units([file])

Arguments
---------
- `file`: path of the unit definition file (default searches as described
  below)

Description
-----------

Given no arguments, `Units()` loads the first `unitfile.txt` found in

1. the current working folder (project files),
2. the `share` folder of the user folder (files shared by all models,
   see `arras.folders`), and
3. the `arras` package folder, which holds the copy of gridlabd's
   `runtime/unitfile.txt` that ships with `arras`,

and returns an object that is expected to satisfy:

1. Every constant (`#c=...`), scalar prefix (`*k=3`), primary unit
   (`name=c,e,h,k,m,s,a,b,prec`), and derived unit (`name=derivation`) in
   the file is defined with the parameters that `unit_init()` computes for
   it.
2. `find(name)` returns the same unit parameters that `unit_find()` does,
   including units with a scalar prefix (`kW`, `mm`) and compound units
   derived on request (`m/s`, `ft^3/min`, `pu.V`), and raises `UnitsError`
   where `unit_find()` returns `NULL`.
3. `convert(value,from_unit,to_unit)` returns the value that
   `unit_convert()` stores, i.e. `(value-from.b)*(from.a/to.a)+to.b`, and
   raises `UnitsError` where `unit_convert()` returns `0` (unknown unit or
   mismatched dimensions). Complex values are converted as
   `unit_convert_complex()` does.
4. `test()` runs the conversions of gridlabd's `unit_test()`
   (`gridlabd --unitstest`) and returns the number that fail.

Theory of operation
-------------------

Each unit is described by eight numbers. The exponents `c`, `e`, `h`, `k`,
`m`, and `s` of the speed of light, the electron charge, Planck's constant,
Boltzmann's constant, the electron rest mass, and the 1990 price of gold
give the dimensions of the unit; `a` is its scale and `b` its offset, so

$$ quantity = (value - b) \\times a \\times c^{k_c} e^{k_e} h^{k_h} k^{k_k} m^{k_m} s^{k_s} $$

Two units can be converted only if their six exponents are equal.
Multiplying units adds their exponents and multiplies their scales;
dividing subtracts and divides. `prec` records the number of significant
digits of the definition.

Unit file syntax
----------------

| Line | Meaning |
| ---- | ------- |
| `; text` | comment (also after a definition) |
| `#X=VALUE` | constant `X`, one of `c`, `e`, `h`, `k`, `m`, `s` |
| `*P=N` | scalar prefix `P` (at most 2 characters) for $10^N$ |
| `NAME=c,e,h,k,m,s,a,b,prec` | primary unit |
| `NAME=[SCALE ]TERM[OP TERM ...]` | derived unit, OP in `* / ^ + -` |

In a derivation, a term is a unit name or a number. A number after `*` or
`/` scales the unit; a number after `+` or `-` offsets it (e.g.
`degC=K-273.14`). `^N` repeats the preceding `*` or `/` term, with N at
least 2. A `.` that is not between digits ends the derivation, so `pu.V`
is derived as `pu`. Lines that start with white space are ignored.

Examples
--------

    >>> from arras.units import Units
    >>> units = Units()
    >>> round(units.convert(212,"degF","degC"),3)
    99.999
    >>> round(units.convert(1,"mile/h","m/s"),6)
    0.44704
    >>> round(units.convert(1,"kWh","Btu"),3)
    3412.969
    >>> round(units.convert(1,"N","lb*ft/s^2"),4)
    7.233
    >>> units.convert(12+1j,"kV","V")
    (12000+1000j)
    >>> units.find("kW")
    <Unit kW=4,0,-1,0,2,0,988524.5911292856,0,7>
    >>> units.find("ft^3/min").dimensions == units.find("m^3/s").dimensions
    True
    >>> units.convert(1,"m","kg")
    Traceback (most recent call last):
    ...
    arras.units.UnitsError: could not convert units from m to kg, mismatched units
    >>> units.test()
    0

Caveats
-------

- `Units` is an independent Python model of gridlabd's unit manager. It
  does not read from or write to a running `gridlabd` process.
- `GLPATH` is not read; a unit file shared by all models goes in the
  `share` folder of the user folder (`arras.folders.userdir("share")`).
- Each `Units` object has its own unit list. Units derived by `find()` are
  added to it, as `unit_find()` adds them to gridlabd's list.
- Constants are read and checked but, as in gridlabd, not used in any
  conversion; the scales of the primary units already include them.
- `convert()` returns the value unchanged when both unit names are the
  same string, even if the unit is not defined, as `unit_convert()` does.
- The following behaviors of gridlabd's unit manager are reproduced so that
  conversions give the same numbers:
  1. A number at the start of a derivation is read as a scale even when no
     space follows it, and is then read again as the first term. For
     example `pi=3.1415926536` defines `pi` with scale $\\pi^2$, and a
     compound such as `1990$/kg` is scaled by 1990.
  2. Derivations may only contain `-+/*^0-9. %A-Za-z`, so `$` ends a
     derivation. In the gridlabd unit file this makes `1975$`, `1980$`,
     `1985$`, `1995$`, `1996$`, and `$` dimensionless, and `CA$` a unit
     with scale 0 (converting to it divides by zero).
  3. Scalar prefixes are tried in reverse file order and only the first
     match is used, so `d` is tried before `da` and `daN` is not found.
  4. A term after `^` is not looked up, so a second `^` (e.g. `m^2^2`) is
     ignored.
  5. `unit_convert_complex()` applies the offset `b` to both the real and
     the imaginary part.

References
----------

- `source/unit.cpp`, `source/unit.h`, and `runtime/unitfile.txt` in
  [arras-energy/gridlabd](https://github.com/arras-energy/gridlabd)
  (as of gridlabd master 076e78a, 2026-08-16)
- [`gridlabd --unitstest`](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Command/Unitstest.md)
"""

# pylint: disable=line-too-long
# (the markdown tables above and the gridlabd test table are kept one row per line)

import os
import re
import math
import logging
from dataclasses import dataclass
from typing import Callable, Iterator

from arras import folders
from arras.exceptions import ArrasException

_logger = logging.getLogger(__file__)

UNITFILE = "unitfile.txt"
"""Name of the unit definition file"""

DEFAULT_UNITFILE = os.path.join(os.path.dirname(__file__), UNITFILE)
"""Copy of gridlabd's `runtime/unitfile.txt` that ships with `arras`"""

DEFAULT_CONSTANTS = {
    "c": 2.997925e8,
    "e": 1.602189246e-19,
    "h": 6.62617636e-34,
    "k": 1.38066244e-23,
    "m": 0.910953447e-30,
    "s": 1.233270e4,
    }
"""Default values of the constants (`source/unit.cpp`)"""

_FLOAT = re.compile(r"\s*([+-]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|inf(?:inity)?|nan))",re.IGNORECASE)
_INT = re.compile(r"\s*([+-]?\d+)")
_TERM = re.compile(r"[^-*/^+]+")
_DERIVATION = re.compile(r"[-+/*^0-9. %A-Za-z]+")
_DIGITS = "0123456789"

class UnitsError(ArrasException):
    """Unit manager exception"""

@dataclass(frozen=True)
class Unit: # pylint: disable=too-many-instance-attributes
    """Unit definition

    Attributes
    ----------
    - `name`: name of the unit
    - `c`, `e`, `h`, `k`, `m`, `s`: exponents of the constants
    - `a`: scale
    - `b`: offset
    - `prec`: number of significant digits of the definition
    """
    name: str
    c: float
    e: float
    h: float
    k: float
    m: float
    s: float
    a: float
    b: float
    prec: int

    @property
    def dimensions(self) -> tuple:
        """Exponents `(c,e,h,k,m,s)` of the constants"""
        return (self.c,self.e,self.h,self.k,self.m,self.s)

    @property
    def parameters(self) -> tuple:
        """All unit parameters `(c,e,h,k,m,s,a,b,prec)`"""
        return self.dimensions + (self.a,self.b,self.prec)

    def compatible(self,other:"Unit") -> bool:
        """Check whether values can be converted to another unit

        Arguments
        ---------
        - `other`: the other unit

        Returns
        -------
        - `bool`: `True` if both units have the same dimensions
        """
        return self.dimensions == other.dimensions

    def __repr__(self) -> str:
        values = ",".join(f"{x:g}" if isinstance(x,float) and x == int(x) and abs(x) < 1e15 else repr(x) for x in self.parameters)
        return f"<Unit {self.name}={values}>"

def _scan_float(text:str) -> tuple:
    """@private Read a leading number as `sscanf("%lf")` does

    Returns `(value,length)` or `(None,0)`
    """
    match = _FLOAT.match(text)
    if match is None:
        return None,0
    return float(match.group(1)),match.end()

def _scan_int(text:str) -> int|None:
    """@private Read a leading integer as `sscanf("%d")` does"""
    match = _INT.match(text)
    return int(match.group(1)) if match else None

def _precision(term:str) -> int:
    """@private Number of significant digits of a number (`unit_precision()`)"""
    mantissa = re.split("[eE]",term,maxsplit=1)[0]
    return len(mantissa) - (1 if "." in mantissa else 0)

class Units:
    """Unit manager

    See the `arras.units` module documentation.
    """

    def __init__(self,file:str|None=None):
        """Load a unit definition file

        Arguments
        ---------
        - `file`: path of the unit definition file (default searches the
          working folder, the user `share` folder, then the `arras`
          package folder)

        Exceptions
        ----------
        - `UnitsError`: the file is not found or a definition is not valid
        """
        self.constants = dict(DEFAULT_CONSTANTS)
        """Constants by name"""
        self.scalars = {}
        """Scalar prefix exponents by prefix, in file order"""
        self.file = file if file else self.locate()
        """Path of the unit definition file"""
        self._units = {}
        self._linenum = 0
        self._load()

    @staticmethod
    def locate() -> str:
        """Find the unit definition file

        Returns
        -------
        - `str`: path of the first `unitfile.txt` found in the working
          folder or the user `share` folder, else `DEFAULT_UNITFILE`
        """
        for folder in folders.search_path(".")[:-1]:
            path = os.path.join(folder,UNITFILE)
            if os.path.isfile(path):
                return path
        return DEFAULT_UNITFILE

    #
    # Container protocol
    #
    def __contains__(self,name:str) -> bool:
        return name in self._units

    def __getitem__(self,name:str) -> Unit:
        return self.find(name)

    def __iter__(self) -> Iterator[str]:
        return iter(self._units)

    def __len__(self) -> int:
        return len(self._units)

    def __repr__(self) -> str:
        return f"<Units file='{self.file}' units={len(self)}>"

    #
    # Definitions
    #
    def _error(self,msg:str) -> UnitsError:
        return UnitsError(f"{self.file}({self._linenum}): {msg}")

    def _find_raw(self,name:str) -> Unit|None:
        return self._units.get(name)

    def _find_underived(self,name:str) -> Unit|None:
        """@private Find a unit, or a unit with a scalar prefix (`unit_find_underived()`)"""
        unit = self._find_raw(name)
        if unit is not None:
            return unit
        for prefix in reversed(self.scalars):
            if name.startswith(prefix):
                break
        else:
            return None
        base = self._find_raw(name[len(prefix):])
        if base is None:
            _logger.debug("compound unit '%s' could not be correctly identified",name)
            return None
        return self.primary(name,base.c,base.e,base.h,base.k,base.m,base.s,
            base.a*math.pow(10,self.scalars[prefix]),base.b,base.prec)

    def constant(self,name:str,value:float) -> None:
        """Define a constant (`unit_constant()`)

        Arguments
        ---------
        - `name`: one of `c`, `e`, `h`, `k`, `m`, `s`
        - `value`: value of the constant

        Exceptions
        ----------
        - `UnitsError`: the name is a unit or not a valid constant
        """
        if self._find_underived(name) is not None:
            raise self._error(f"constant definition of '{name}' failed; unit already defined")
        if name not in DEFAULT_CONSTANTS:
            raise self._error(f"constant '{name}' is not valid")
        self.constants[name] = float(value)

    def scalar(self,name:str,exponent:int) -> None:
        """Define a scalar prefix (`unit_scalar()`)

        Arguments
        ---------
        - `name`: prefix (only the first 2 characters are used)
        - `exponent`: power of 10 of the prefix
        """
        name = name[:2]
        self.scalars.pop(name,None)
        self.scalars[name] = int(exponent)

    def primary(self,name:str,c:float,e:float,h:float,k:float,m:float,s:float,a:float,b:float,prec:int) -> Unit: # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Define a primary unit (`unit_primary()`)

        Arguments
        ---------
        - `name`: name of the unit
        - `c`, `e`, `h`, `k`, `m`, `s`: exponents of the constants
        - `a`: scale
        - `b`: offset
        - `prec`: number of significant digits

        Returns
        -------
        - `Unit`: the unit

        Exceptions
        ----------
        - `UnitsError`: the unit is already defined with other parameters
        """
        unit = Unit(name,float(c),float(e),float(h),float(k),float(m),float(s),float(a),float(b),int(prec))
        old = self._find_raw(name)
        if old is not None and old.parameters != unit.parameters:
            raise self._error(f"primary definition of '{name}' failed; unit already defined with a different parameter set")
        self._units[name] = unit
        return unit

    def derive(self,name:str,derivation:str) -> Unit: # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """Define a derived unit (`unit_derived()`)

        Arguments
        ---------
        - `name`: name of the unit
        - `derivation`: derivation, e.g., `1 m*kg/s^2` or `K-273.14`

        Returns
        -------
        - `Unit`: the unit

        Exceptions
        ----------
        - `UnitsError`: the unit is already defined or the derivation is not
          valid
        """
        # a '.' not between digits ends the derivation, e.g., "pu.V"
        for n in range(1,len(derivation)):
            if derivation[n] == "." and derivation[n-1] not in _DIGITS \
                    and (n+1 == len(derivation) or derivation[n+1] not in _DIGITS):
                derivation = derivation[:n]
                break

        if self._find_raw(name) is not None:
            raise self._error(f"derived definition of '{name}' failed; unit already defined")

        # leading scalar
        text = derivation
        scalar,size = _scan_float(text)
        if scalar is None:
            scalar = 1.0
        elif " " in text:
            text = text[text.index(" ")+1:]

        c = e = h = k = m = s = a = b = 0.0
        prec = 0
        last_op = next_op = ""
        last_unit = None
        while text:
            match = _TERM.match(text)
            if match is None:
                raise self._error(f"unable to read unit '{text}'")
            term = match.group(0)
            unit = None
            if next_op != "^":
                unit = self._find_underived(term)
                if unit is None:
                    value,size = _scan_float(term)
                    if size == 0:
                        raise self._error(f"unable to find or derive unit '{text}'")
                    if next_op in "+-" and next_op:
                        unit = Unit("",0,0,0,0,0,0,0,value,_precision(term))
                    else:
                        unit = Unit("",0,0,0,0,0,0,value,0,_precision(term))
            text = text[len(term):]

            if next_op == "":
                if a == 0:
                    c,e,h,k,m,s = unit.dimensions
                    a = unit.a * scalar
                    b = unit.b
                    prec = unit.prec
                    next_op = "*"
            elif next_op == "*":
                c,e,h,k,m,s = (x+y for x,y in zip((c,e,h,k,m,s),unit.dimensions))
                a *= unit.a
                prec = min(prec,unit.prec)
            elif next_op == "/":
                c,e,h,k,m,s = (x-y for x,y in zip((c,e,h,k,m,s),unit.dimensions))
                a /= unit.a
                prec = min(prec,unit.prec)
            elif next_op == "+":
                b += unit.b
            elif next_op == "-":
                b -= unit.b
            elif next_op == "^":
                if last_unit is not None:
                    repeat = _scan_int(term)
                    if repeat is None or repeat < 2:
                        raise self._error(f"syntax error at '{term}', exponent must be greater than 1")
                    repeat -= 1
                    if last_op == "*":
                        c,e,h,k,m,s = (x+y*repeat for x,y in zip((c,e,h,k,m,s),last_unit.dimensions))
                        a *= math.pow(last_unit.a,repeat)
                    elif last_op == "/":
                        c,e,h,k,m,s = (x-y*repeat for x,y in zip((c,e,h,k,m,s),last_unit.dimensions))
                        a /= math.pow(last_unit.a,repeat)
                    else:
                        raise self._error(f"^ not allowed after '{last_op}' at '{term}'")
                    prec = min(prec,last_unit.prec)
            last_op = next_op
            if text:
                next_op,text = text[0],text[1:]
            else:
                next_op = ""
            last_unit = unit

        return self.primary(name,c,e,h,k,m,s,a,b,prec)

    def _load(self) -> None: # pylint: disable=too-many-branches
        """@private Read the unit definition file (`unit_init()`)"""
        try:
            with open(self.file,"r",encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError as err:
            raise UnitsError(f"{self.file}: {err.strerror}") from err

        for self._linenum,line in enumerate(lines,1):
            line = line.split(";",1)[0].rstrip()
            if not line or line[0].isspace():
                continue

            # constant
            if line[0] == "#":
                match = re.match(r"(.)=",line[1:],re.DOTALL)
                value = _scan_float(line[3:])[0] if match else None
                if value is None:
                    _logger.error("%s(%d): constant definition '%s' is not valid",self.file,self._linenum,line)
                else:
                    self.constant(match.group(1),value)
                continue

            # scalar
            if line[0] == "*":
                match = re.match(r"([^=]{1,7})=",line[1:])
                value = _scan_int(line[1+match.end():]) if match else None
                if value is None:
                    _logger.error("%s(%d): scalar '%s' is not valid",self.file,self._linenum,line)
                else:
                    self.scalar(match.group(1),value)
                continue

            match = re.match(r"([^=]+)=",line)
            if match:
                name,rest = match.group(1),line[match.end():]

                # primary
                values = []
                for _ in range(8):
                    value,size = _scan_float(rest)
                    if value is None or rest[size:size+1] != ",":
                        break
                    values.append(value)
                    rest = rest[size+1:]
                if len(values) == 8:
                    prec = _scan_int(rest)
                    if prec is not None:
                        self.primary(name,*values,prec) # pylint: disable=no-value-for-parameter
                        continue

                # derived
                derivation = _DERIVATION.match(line[match.end():])
                if derivation:
                    self.derive(name,derivation.group(0))
                    continue

            raise self._error(f"unit '{line}' is not recognized")

        _logger.debug("%s loaded ok",self.file)

    #
    # Lookup and conversion
    #
    def find(self,name:str) -> Unit:
        """Find a unit, deriving it if needed (`unit_find()`)

        Arguments
        ---------
        - `name`: unit name or derivation, e.g., `kW`, `m/s`, `ft^3/min`

        Returns
        -------
        - `Unit`: the unit

        Exceptions
        ----------
        - `UnitsError`: the unit could not be found or derived
        """
        unit = self._find_raw(name)
        if unit is not None:
            return unit
        linenum,self._linenum = self._linenum,0
        try:
            return self.derive(name,name)
        except UnitsError as err:
            raise UnitsError(f"could not find unit '{name}' ({err})") from err
        finally:
            self._linenum = linenum

    def convert(self,value:float|complex,from_unit:str|Unit,to_unit:str|Unit) -> float|complex:
        """Convert a value from one unit to another (`unit_convert()`)

        Arguments
        ---------
        - `value`: value to convert (`complex` values are converted as
          `unit_convert_complex()` does)
        - `from_unit`: unit of `value`
        - `to_unit`: unit of the result

        Returns
        -------
        - `float|complex`: the converted value

        Exceptions
        ----------
        - `UnitsError`: a unit is not found or the units have different
          dimensions
        """
        if isinstance(from_unit,str) and isinstance(to_unit,str) and from_unit == to_unit:
            return value
        src = from_unit if isinstance(from_unit,Unit) else self.find(from_unit)
        dst = to_unit if isinstance(to_unit,Unit) else self.find(to_unit)
        if not src.compatible(dst):
            raise UnitsError(f"could not convert units from {src.name} to {dst.name}, mismatched units")
        if isinstance(value,complex):
            return complex((value.real-src.b)*(src.a/dst.a)+dst.b,(value.imag-src.b)*(src.a/dst.a)+dst.b)
        return (float(value)-src.b)*(src.a/dst.a)+dst.b

    #
    # Self-test
    #
    TESTS = [
        # (from value, from unit, to value, to unit, precision)
        (1,"ratio",1,"unit",0),
        (1,"%",0.01,"unit",0),
        (1,"pu",1,"1/unit",0),
        (1,"/%",1,"1/%",0),
        (3.141592635,"unit",3.141592635,"unit",0),
        (2*3.141592635,"rad",1,"unit",0),
        (360,"deg",1,"unit",0),
        (400,"grad",1,"unit",0),
        (4,"quad",1,"unit",0),
        (4*3.141592635,"sr",1,"unit",0),
        (1,"R",5.0/9.0,"K",0.001),
        (0,"degC",273.14,"K",0.001),
        (0,"degF",459.65,"R",0.001),
        (212,"degF",100.0,"degC",0.01),
        (32,"degF",0.0,"degC",0.01),
        (20,"degC",68.0,"degF",0.01),
        (77,"degF",25.0,"degC",0.01),
        (1,"kg",1000,"g",0),
        (1,"N",1,"m*kg/s^2",0),
        (1,"J",1,"N*m",0),
        (1,"min",60,"s",0),
        (1,"h",60,"min",0),
        (1,"day",24,"h",0),
        (1,"yr",365,"day",0),
        (1,"syr",365.24,"day",0),
        (1,"cm",0.01,"m",0),
        (1,"mm",0.1,"cm",0),
        (1,"km",1000,"m",0),
        (1,"in",2.54,"cm",0),
        (1,"ft",12,"in",0),
        (1,"yd",3,"ft",0),
        (1,"mile",5280,"ft",0),
        (1,"sf",1,"ft^2",0),
        (1,"sy",1,"yd^2",0),
        (1,"cf",1,"ft^3",0),
        (1,"cy",1,"yd^3",0),
        (1,"l",0.001,"m^3",0),
        (1,"gal",3.785412,"l",0),
        (2.2046,"lb",1,"kg",0),
        (1,"tonne",1000,"kg",0),
        (1,"mph",1,"mile/h",0),
        (1,"fps",1,"ft/s",0),
        (1,"fpm",1,"ft/min",0),
        (1,"gps",1,"gal/s",0),
        (1,"gpm",1,"gal/min",0),
        (1,"gph",1,"gal/h",0),
        (1,"cfm",1,"ft^3/min",0),
        (1,"ach",1,"1/h",0),
        (1,"Hz",1,"1/s",0),
        (1,"W",1,"J/s",0),
        (1,"kW",1000,"W",0),
        (1,"MW",1000,"kW",0),
        (1,"Wh",1,"W*h",0),
        (1,"kWh",1000,"Wh",0),
        (1,"MWh",1000,"kWh",0),
        (1,"Btu",0.293,"Wh",0),
        (1,"kBtu",1000,"Btu",0),
        (1,"MBtu",1000,"kBtu",0),
        (1,"ton",12000,"Btu/h",0),
        (1,"tons",1,"ton*s",0),
        (1,"tonh",1,"ton*h",0),
        (1,"hp",746,"W",0),
        (1,"W",1,"V*A",0),
        (1,"C",1,"A*s",0),
        (1,"F",1,"C/V",0),
        (1,"Ohm",1,"V/A",0),
        (1,"H",1,"Ohm*s",0),
        ]
    """Conversions checked by `test()`, from gridlabd's `unit_test()`"""

    def test(self,output:Callable|None=None) -> int:
        """Run the unit conversion self-test (`unit_test()`)

        Each conversion in `TESTS` is checked forward and back within its
        precision (default 1e-4).

        Arguments
        ---------
        - `output`: function that receives one result line per test
          (default logs at DEBUG level)

        Returns
        -------
        - `int`: number of failed tests
        """
        if output is None:
            output = _logger.debug
        # pylint: disable=logging-fstring-interpolation
        failed = 0
        output("BEGIN: units tests")
        for from_value,from_unit,to_value,to_unit,precision in self.TESTS:
            precision = precision if precision else 1e-4
            try:
                value = self.convert(from_value,from_unit,to_unit)
                if abs(value-to_value) > precision:
                    raise UnitsError(f"incorrect unit conversion {from_value:g} {from_unit} -> {to_value:g} {to_unit} (got {value:g} {to_unit} instead)")
                value = self.convert(value,to_unit,from_unit) # pylint: disable=arguments-out-of-order
                if abs(value-from_value) > precision:
                    raise UnitsError(f"incorrect unit conversion {to_value:g} {to_unit} -> {from_value:g} {from_unit} (got {value:g} {from_unit} instead)")
                output(f"SUCCESS: {from_value:g} {from_unit} = {to_value:g} {to_unit}")
            except UnitsError as err:
                output(f"FAILED: {err}")
                failed += 1
        output(f"END: {len(self.TESTS)} units tested")
        return failed
