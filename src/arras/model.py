# pylint: disable=too-many-lines,line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras models

The `Model` class holds an Arras Energy (HiPAS GridLAB-D) model: the global
variables, the modules it loads, the classes those modules provide and the
runtime classes that GLM `class` blocks declare, schedules, filters, and
objects. It reads and writes the model as GLM, which `arras-energy/gridlabd`
loads in `source/load.cpp`, and as JSON in the format that gridlabd's
`GldJsonWriter` writes in `source/json.cpp` (`gridlabd -o FILE.json`).

Users can read and write models, search objects by name or property value
with regular expressions, add and delete one object or many, and get and set
one property or many, with each property name and value checked against the
object's class.

Syntax
------

    from arras.model import Model
    m = Model([file], [globals], [strict])   # empty model, or read FILE.glm / FILE.json
    m.read(file)                             # read more GLM or JSON into the model
    m.write(file)                            # write FILE.glm or FILE.json

Arguments
---------
- `file`: name of a `.glm` or `.json` file to read (default `None`)
- `globals`: `arras.globals.Globals` object holding the global variables
  (default is a new `Globals()`)
- `strict`: refuse property values that fail validation; when `False`, a
  warning is logged and the value is stored as given (default `True`)

Description
-----------

Given a GLM or JSON file, `Model(file)` returns a model that is expected to
satisfy:

1. `objects` is a `dict` keyed on object name. Each value is an `Object`
   (a `dict` of property name to value string, with the class in
   `Object.oclass`). An object without a name is keyed `CLASS:ID`, the name
   gridlabd's JSON writer uses.
2. Every object's class is registered in `arras.oclass.Class.registry` and
   listed in `classes`. Classes that modules provide come from a Python
   package that implements the module (an `arras.modules` entry point,
   e.g. the `assert` package), from a gridlabd JSON file
   (`load_classes()`), from `Model.module_loader` when a GLM file loads a
   module, or from classes the user registered with
   `arras.oclass.Class`. Runtime classes come from GLM `class` blocks and
   from the `classes` section of a JSON file.
3. Every stored property is a header property (`HEADER`), an event handler
   (`on_init`, ...), or a property that the object's class or one of its
   parents defines, and every value was accepted by the type checks below
   (unless `strict` is `False`).
4. Every `parent` and `object` property names an object of the model, and
   no object is its own ancestor. Values that refer to objects are checked
   when a read finishes, so GLM and JSON files may refer to objects that
   appear later in the file.
5. `write_json()` writes the sections of gridlabd's JSON format
   (`application`, `version`, `modules`, `header`, `classes`, `globals`,
   `schedules`, `filters`, `objects`), which `read_json()` reads back.
   `write_glm()` writes GLM that `read_glm()` reads back into the same
   objects, ids, and values.
6. A method that adds, deletes, or sets more than one item checks all of
   them before it changes the model: either every change is made or none is.

Property value checks
---------------------

| Type | Accepted values | Stored as |
| ---- | --------------- | --------- |
| `double`, `real`, `float` | number with an optional unit, `nan`, `inf`, `random.DIST(...)`, a schedule or `object.property` transform (`NAME[*SCALE][+BIAS]`), a filter `NAME(input)` | number in the property's unit when the unit given differs |
| `complex` | `A`, `A+Bi`, `A+Bj`, `A+Bd`, `A+Br`, with an optional unit; Python `complex`; a JSON list `[A,B]` or dict `{"real":A,"imag":B}` | rectangular or polar text, converted to the property's unit |
| `int16`, `int32`, `int64` | integer (decimal or `0x` hex) in the type's range | as given |
| `bool` | `TRUE`, `FALSE` (any case), integers | `TRUE` or `FALSE` |
| `enumeration` | a keyword or an integer | as given |
| `set` | keywords separated by `|`, single-character keywords run together when the set is `CHARSET`, or an integer | as given |
| `timestamp` | a date and time, `INIT`, `NEVER`, `NOW`, or seconds (see `arras.globals.Globals.timestamp_from_string`) | as given |
| `char8`, `char32`, `char256`, `char1024` | text shorter than 8, 32, 256, 1024 characters | as given |
| `object` | name of an object of the model | as given |
| other types | any text | as given |

Values may also be given as Python values (`int`, `float`, `bool`,
`complex`, a `list` or `set` of keywords for `set` properties). GLM values
`inherit` (copy the parent's value) and `@NAME` (copy object NAME's value)
are resolved when read.

Header properties
-----------------

`id` and `class` are read-only. `name` is changed with `rename()`. The others
(`parent`, `groupid`, `rank`, `clock`, `valid_to`, `schedule_skew`,
`latitude`, `longitude`, `in_svc`, `out_svc`, `rng_state`, `heartbeat`,
`guid`, `flags`) are set like class properties. JSON's `in` and `out` are
read as `in_svc` and `out_svc`.

Examples
--------

    >>> from arras.oclass import Class
    >>> from arras.model import Model
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... class meter {
    ...     double power[kW];
    ...     enumeration {OFF=0, ON=1} status;
    ...     set {A=1, B=2, C=4} phases;
    ... }
    ... object meter {
    ...     name "m1";
    ...     power 1.5 MW;
    ...     phases AB;
    ...     object meter {
    ...         status ON;
    ...     };
    ... }
    ... ''')
    >>> list(m.objects)
    ['m1', 'meter:1']
    >>> m.get_property("m1", "power")
    '1500.0 kW'
    >>> m.get_property("meter:1", "parent")
    'm1'
    >>> m.add_object("meter", "m2", power="2 kW", parent="m1")
    'm2'
    >>> m.find(r"^m\\d$")
    ['m1', 'm2']
    >>> m.find("ON", prop="status")
    ['meter:1']
    >>> m.set_properties(["m1", "m2"], {"status": "OFF"})
    >>> m.get_properties("m2", ["power", "status"])
    {'power': '2 kW', 'status': 'OFF'}
    >>> m.set_property("m2", "status", "MAYBE")
    Traceback (most recent call last):
    ...
    arras.model.ModelError: meter.status: 'MAYBE' is not a keyword of status
    >>> m.set_property("m2", "voltage", 120)
    Traceback (most recent call last):
    ...
    arras.model.ModelError: class 'meter' has no property 'voltage'
    >>> m.delete_object("m1")
    Traceback (most recent call last):
    ...
    arras.model.ModelError: cannot delete m1: referred to by meter:1, m2
    >>> m.delete_object("m1", children="delete")
    ['m1', 'meter:1', 'm2']
    >>> list(m.objects)
    []

Caveats
-------

- `Model` is an independent Python model of a gridlabd model. It does not
  run `gridlabd` or load module libraries, so it does not know the classes
  that a module publishes until they are registered. Modules implemented
  in Python (`arras.modules` entry points, such as the `assert` package)
  register their classes when the model loads them. Register others by
  reading a JSON file that gridlabd wrote (`gridlabd -o FILE.json`, or
  `gridlabd --modhelp=json MODULE > FILE.json`) with `load_classes()` or
  `read_json()`, by assigning `Model.module_loader`, or with
  `arras.oclass.Class`.
- Classes are registered in the shared `arras.oclass.Class.registry`.
  Classes stay registered when a model is deleted; call `Class.reset()` to
  start over. While a model holds objects of a class, `Class.numobjs` is
  positive and no property can be added to the class.
- Property values are stored as text. Objects list only the properties
  that were set; `get_property()` returns the class default for the others.
- `write_json()` writes class defaults for the properties that are not set
  (see `Model.to_json()`), so reading its output back stores those defaults
  as set values. It leaves out the class attributes that need a running
  gridlabd (`object_size`, `profiler.*`) and the `types` section. Set
  values of properties that are not `PUBLIC` are written, though gridlabd
  leaves such properties out.
- A GLM or JSON read that fails keeps the items read before the error.
- GLM support covers `clock`, `module`, `class` (properties, keywords,
  `parent`, event handlers), `object` (nested objects, `:ID`, `:..COUNT`,
  `:FIRST..LAST`), `global`, `modify`, `schedule`, `filter`, comments,
  `${...}` expansion (`arras.globals.Globals.expand`), and the macros
  `#set`, `#define`, `#include`, `#ifdef`, `#ifndef`, `#else`, `#endif`,
  `#print`, `#warning`, `#error`. Other macros (`#if`, `#for`, `#exec`,
  `#input`, ...), class functions and code blocks, backtick expressions, and
  the `instance`, `link`, `script`, `dump`, `extern`, and `gui` directives
  raise `ModelError`.
- `${PYTHON ...}` and `${SHELL ...}` expansions run code, as they do in
  gridlabd. Do not read untrusted GLM files.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Property values are checked when they are set. gridlabd converts values
   to binary when it loads them, so some values it accepts (expressions,
   values with a unit on a unitless property) are refused here.
2. `delete_object()` and `rename()` update or check references from other
   objects; gridlabd has no object deletion or renaming in GLM.
3. Values that end at a newline without `;` are refused. gridlabd ends a
   value at the newline and then expects `;`.
4. `#include` searches the folder of the including file, the working
   folder, the user `include` and `share` folders, the `GLPATH` folders,
   and the `arras` package folder (`arras.folders`).

References
----------

- `arras-energy/gridlabd`: `source/load.cpp` (`object_block()`,
  `object_properties()`, `class_block()`, `module_block()`, `value()`),
  `source/json.cpp` (`GldJsonWriter`), `source/object.cpp`
  (`headerdata[]`, `object_saveall()`, `object_set_name()`),
  `source/module.cpp` (`module_saveall()`), `source/save.cpp`
  (`saveglm()`)
- [Object directive](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/GLM/Directive/Object.md)
  (`docs/GLM/Directive/Object.md`), `docs/GLM/Directive/Class.md`,
  `docs/GLM/Directive/Module.md`, `docs/GLM/Directive/Modify.md`
"""

import os
import re
import json
import bisect
import logging
import datetime
import importlib.metadata
from typing import Any, Callable, Iterable

import arras.folders
from arras.exceptions import ArrasException
from arras.globals import Globals, GlobalsError, TS_NEVER
from arras.oclass import Class, ClassError, Property, PROPERTY_TYPES, FLAGS, ACCESS, EVENTS
from arras.units import UnitsError

_logger = logging.getLogger(__file__)

HEADER = {
    "id": "int32",
    "class": "string",
    "groupid": "char32",
    "name": "string",
    "parent": "object",
    "rank": "int32",
    "clock": "timestamp",
    "valid_to": "timestamp",
    "schedule_skew": "int64",
    "latitude": "double",
    "longitude": "double",
    "in_svc": "timestamp",
    "out_svc": "timestamp",
    "rng_state": "int32",
    "heartbeat": "int64",
    "guid": "int64",
    "flags": "int64",
}
"""Object header properties and their types (gridlabd `headerdata[]` in
`source/object.cpp`, without the computed entries `next`, `child_count`,
`profiler.*`, and `event.*`)"""

READONLY = ("id", "class", "name")
"""Header properties that `set_property()` refuses (use `rename()` for `name`)"""

JSON_ALIASES = {"in": "in_svc", "out": "out_svc"}
"""Header property names that gridlabd's JSON writer uses for other names"""

INTEGER_BITS = {"int16": 16, "int32": 32, "int64": 64}
"""Size of the integer property types"""

CHAR_SIZES = {"char8": 8, "char32": 32, "char256": 256, "char1024": 1024}
"""Buffer size of the fixed-size string property types (text must be shorter)"""

DOUBLE_TYPES = ("double", "real", "float")
"""Property types that hold one real number"""

NOSAVE_GLOBALS = ("savefile", "randomstate")
"""Public globals that `write_glm()` leaves out: `savefile` comes from the
command line (`-o`) and `randomstate` follows from `randomseed`"""

FSO_MINIMAL = 0x8000
"""`filesave_options` bit that leaves default values out of JSON output
(gridlabd `FSO_MINIMAL`)"""

MAXINCLUDE = 32
"""Maximum depth of nested `#include` macros"""

_UNSIGNED = r"(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NUMBER = rf"[-+]?{_UNSIGNED}"
_DOUBLE = re.compile(rf"({_NUMBER}|[-+]?(?:nan|inf(?:inity)?))(?:\s*(\S+))?$", re.IGNORECASE)
_REAL = rf"(?:{_UNSIGNED}|nan|inf(?:inity)?)"
_COMPLEX = re.compile(rf"([-+]?{_REAL})(?:\s*([-+]\s*{_REAL})\s*([ijdr]))?(?:\s+(\S+))?$", re.IGNORECASE)
_INTEGER = re.compile(r"[-+]?(?:0[xX][0-9a-fA-F]+|\d+)$")
_TRANSFORM = re.compile(rf"([A-Za-z_][\w.:]*)(?:\s*\*\s*({_NUMBER}))?(?:\s*([-+])\s*({_UNSIGNED}))?$")
_FILTER = re.compile(r"([A-Za-z_]\w*)\s*\(([^()]*)\)$")
_RANDOM = re.compile(r"random\.\w+\s*\([^()]*\)$")
_DATETIME = re.compile(r"\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d*)?)?(?:\s*\S+)?$")
_LATLON = re.compile(r"\d+\s*[NSEW]\s*[\d:.'\" ]*$")
_NAME = re.compile(r"[A-Za-z_][\w.:]*")

MODULE_ENTRY_POINTS = "arras.modules"
"""Entry point group of the gridlabd modules that Python packages provide:
each entry point is named for the module and refers to a function called
as `function(model)` when a model loads the module (`Model.load_module()`)"""

class ModelError(ArrasException):
    """Model error"""

def module_entry_point(name:str) -> Callable|None:
    """Function that an installed package provides for module `name` in
    the `arras.modules` entry point group, or `None`

    Exceptions
    ----------
    - `ModelError`: the entry point cannot be loaded or is not callable
    """
    for entry in importlib.metadata.entry_points(group=MODULE_ENTRY_POINTS, name=name):
        try:
            loader = entry.load()
        except Exception as err: # pylint: disable=broad-exception-caught
            raise ModelError(f"module '{name}' entry point '{entry.value}' cannot be loaded: {type(err).__name__}: {err}") from err
        if not callable(loader):
            raise ModelError(f"module '{name}' entry point '{entry.value}' is not callable")
        return loader
    return None

def _fmt(value:float) -> str:
    """Text of a float rounded to 15 significant digits (so that unit
    conversion errors such as `1500.0000000000002` do not show), written
    as Python `repr` writes it"""
    return repr(float(f"{float(value):.15g}"))

def _signed(value:float) -> str:
    text = _fmt(value)
    return text if text[0] in "+-" else "+" + text

class Object(dict):
    """Model object: a `dict` of property name to value string

    The `id` and `class` keys are always present. Change values with the
    `Model` methods, which validate them; changing the `dict` directly
    skips validation.

    Attributes
    ----------
    - `oclass`: the object's class (`arras.oclass.Class`)
    """

    def __init__(self, oclass:Class, oid:int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.oclass = oclass
        """Object class"""
        self["id"] = str(oid)
        self["class"] = oclass.name

    def __repr__(self) -> str:
        return f"<Object {self.oclass.name}:{self['id']}>"

    @property
    def id(self) -> int:
        """Object id"""
        return int(self["id"])

class _Scanner:
    """Character scanner for preprocessed GLM text"""

    def __init__(self, text:str, lines:list[tuple[str,int]]):
        self.text = text
        self.pos = 0
        self.lines = lines
        self.starts = [0]
        for match in re.finditer("\n", text):
            self.starts.append(match.end())

    def where(self, pos:int|None=None) -> str:
        """`file(line)` of a position"""
        index = bisect.bisect_right(self.starts, self.pos if pos is None else pos) - 1
        if 0 <= index < len(self.lines):
            name, line = self.lines[index]
            return f"{name}({line})"
        return "(end)" # pragma: no cover

    def error(self, message:str, pos:int|None=None) -> ModelError:
        """A `ModelError` naming the file and line"""
        return ModelError(f"{self.where(pos)}: {message}")

    def skip(self) -> bool:
        """Skip whitespace; returns `False` at the end of the text"""
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1
        return self.pos < len(self.text)

    def peek(self, text:str) -> bool:
        """Check whether the next non-blank text starts with `text`"""
        self.skip()
        return self.text.startswith(text, self.pos)

    def literal(self, text:str) -> bool:
        """Consume `text` if it comes next"""
        if self.peek(text):
            self.pos += len(text)
            return True
        return False

    def expect(self, text:str, what:str) -> None:
        """Consume `text` or raise `ModelError`"""
        if not self.literal(text):
            raise self.error(f"expected '{text}' {what}")

    def word(self, pattern:re.Pattern=_NAME) -> str|None:
        """Consume a word matching `pattern`"""
        self.skip()
        match = pattern.match(self.text, self.pos)
        if match is None:
            return None
        self.pos = match.end()
        return match.group(0)

    def token(self) -> str:
        """Consume text up to whitespace, `{`, `}`, or `;`"""
        self.skip()
        start = self.pos
        while self.pos < len(self.text) and not self.text[self.pos].isspace() and self.text[self.pos] not in "{};":
            self.pos += 1
        return self.text[start:self.pos]

    def block(self) -> str:
        """Consume a `{...}` block with nested braces; returns the text inside"""
        self.expect("{", "to open block")
        start, depth = self.pos, 1
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return self.text[start:self.pos-1]
            self.pos += 1
        raise self.error("missing '}' to close block", start)

    def statement(self) -> str:
        """Consume raw text up to `;` (quotes and braces respected) and the `;`"""
        self.skip()
        start, depth, quote = self.pos, 0, False
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "\\" and quote:
                self.pos += 1
            elif char == '"':
                quote = not quote
            elif not quote and char == "{":
                depth += 1
            elif not quote and char == "}":
                depth -= 1
            elif not quote and depth == 0 and char == ";":
                self.pos += 1
                return self.text[start:self.pos-1].strip()
            self.pos += 1
        raise self.error("missing ';'", start)

    def value(self) -> str:
        """Consume a property value and its `;` (gridlabd `value()`)

        A value is a `\"\"\"...\"\"\"` multi-line string, a `{...}` structured
        value, or text up to `;` in which double quotes are removed and a
        backslash keeps the next character.
        """
        self.skip()
        start = self.pos
        if self.text.startswith('"""', self.pos):
            end = self.text.find('"""', self.pos+3)
            if end < 0:
                raise self.error("unterminated multi-line value ('\"\"\"' not found)")
            raw = self.text[self.pos+3:end]
            self.pos = end + 3
            result = re.sub(r"\\(.)", lambda m: {"n":"\n","t":"\t","r":"\r"}.get(m.group(1), m.group(1)), raw)
        elif self.text.startswith("{", self.pos):
            result = "{" + self.block() + "}"
        else:
            chars, quote = [], False
            while self.pos < len(self.text):
                char = self.text[self.pos]
                if char == "\\" and self.pos + 1 < len(self.text):
                    self.pos += 1
                    chars.append(self.text[self.pos])
                elif char == '"':
                    quote = not quote
                elif char == ";" and not quote:
                    break
                elif char == "\n":
                    raise self.error("missing ';' at end of value", start)
                else:
                    chars.append(char)
                self.pos += 1
            result = "".join(chars).strip()
        if not self.literal(";"):
            raise self.error("missing ';' at end of value", start)
        return result

class _ObjectSpec: # pylint: disable=too-few-public-methods
    """Parsed GLM `object` block"""

    def __init__(self, oclass:Class, first:int|None, count:int, explicit:bool, where:str):
        self.oclass = oclass
        self.first = first
        self.count = count
        self.explicit = explicit
        self.where = where
        self.props: list[tuple[str,str,str]] = []
        self.children: list["_ObjectSpec"] = []

class Model: # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Arras model

    See the module documentation for the description and examples.

    Attributes
    ----------
    - `globals`: global variables (`arras.globals.Globals`)
    - `modules`: dict of loaded modules, each a dict with `major` and `minor`
    - `classes`: dict of the classes the model uses, keyed on class name
    - `schedules`: dict of schedule definitions (the text inside the GLM
      `schedule NAME { ... }` block), keyed on schedule name
    - `filters`: dict of filters, keyed on filter name: the GLM text after
      `filter`, or the dict that gridlabd's JSON writer gives
    - `objects`: dict of `Object`, keyed on object name
    - `strict`: refuse values that fail validation (else log a warning)
    """

    module_loader: Callable[[str],dict|str|None]|None = None
    """Function called as `module_loader(name)` when a GLM file loads a
    module that has no registered classes; returns gridlabd JSON (a dict or
    a file name) for `load_classes()`, or `None`"""

    _default_globals: dict[str,str|None]|None = None

    def __init__(self, file:str|None=None, globals:Globals|None=None, strict:bool=True): # pylint: disable=redefined-builtin
        """Create a model

        Arguments
        ---------
        - `file`: `.glm` or `.json` file to read
        - `globals`: global variables (default is a new `Globals()`)
        - `strict`: refuse values that fail validation

        Exceptions
        ----------
        - `ModelError`: the file cannot be read (see `read()`)
        """
        self.globals = Globals() if globals is None else globals
        """Global variables"""
        self.modules: dict[str,dict[str,int]] = {}
        """Loaded modules"""
        self.classes: dict[str,Class] = {}
        """Classes used by the model"""
        self.schedules: dict[str,str] = {}
        """Schedule definitions"""
        self.filters: dict[str,str|dict] = {}
        """Filter definitions"""
        self.objects: dict[str,Object] = {}
        """Objects keyed on name"""
        self.strict = strict
        """Refuse values that fail validation"""
        self._next_id = 0
        if file is not None:
            self.read(file)

    def __repr__(self) -> str:
        return f"<Model ({len(self.objects)} objects)>"

    def __contains__(self, name:str) -> bool:
        return name in self.objects

    def __getitem__(self, name:str) -> Object:
        return self._object(name)

    def __iter__(self):
        return iter(list(self.objects))

    def __len__(self) -> int:
        return len(self.objects)

    #
    # Classes and modules
    #
    def find_class(self, name:str) -> Class:
        """Find a class by name or `module.class` among the model's classes,
        then in the class registry

        Exceptions
        ----------
        - `ModelError`: the class is not registered
        """
        if isinstance(name, Class):
            oclass = name
        elif name in self.classes:
            oclass = self.classes[name]
        else:
            oclass = Class.find(name)
            if oclass is None:
                raise ModelError(f"class '{name}' is not known (register it or load its module's classes with load_classes())")
        self._use_class(oclass)
        return oclass

    def _use_class(self, oclass:Class) -> None:
        while oclass is not None:
            self.classes.setdefault(oclass.name, oclass)
            if oclass.module is not None and oclass.module not in self.modules:
                self.modules[oclass.module] = {"major": 0, "minor": 0}
            oclass = oclass.parent

    def load_module(self, name:str, major:int|None=None, minor:int|None=None) -> None:
        """Load a module, as GLM `module NAME;` does

        When an installed package provides the module as an `arras.modules`
        entry point (see `MODULE_ENTRY_POINTS`), the entry point is called
        with the model first; it registers the module's classes and
        globals. Then the classes registered for the module are added to
        `classes`. When none are registered and `Model.module_loader` is
        set, its result is passed to `load_classes()`.

        Arguments
        ---------
        - `name`: module name
        - `major`, `minor`: module version

        Exceptions
        ----------
        - `ModelError`: the module's entry point cannot be loaded or fails
        """
        info = self.modules.setdefault(name, {"major": 0, "minor": 0})
        if major is not None:
            info["major"] = int(major)
        if minor is not None:
            info["minor"] = int(minor)
        loader = module_entry_point(name)
        if loader is not None:
            try:
                loader(self)
            except ArrasException as err:
                raise ModelError(f"module '{name}': {err}") from err
        found = [oclass for oclass in Class.registry if oclass.module == name]
        if not found and Model.module_loader is not None:
            data = Model.module_loader(name) # pylint: disable=not-callable
            if data is not None:
                self.load_classes(data)
                found = [oclass for oclass in Class.registry if oclass.module == name]
        for oclass in found:
            self._use_class(oclass)

    def load_classes(self, data:dict|str) -> list[Class]:
        """Register the classes in gridlabd JSON

        Reads the `modules` and `classes` sections that `gridlabd -o
        FILE.json` and `gridlabd --modhelp=json MODULE` write. A class that
        is already registered keeps its properties; properties it lacks are
        added. Classes keyed `module.class` (the `--modhelp=json` form) are
        registered for that module.

        Arguments
        ---------
        - `data`: JSON dict, JSON text, or JSON file name

        Returns
        -------
        - `list[Class]`: the classes read

        Exceptions
        ----------
        - `ModelError`: the data is not gridlabd JSON, or a class or
          property conflicts with a registered one
        """
        data = self._json_data(data)
        for name, info in data.get("modules", {}).items():
            self.load_module(name, info.get("major"), info.get("minor"))
        specs = []
        for key, info in data.get("classes", {}).items():
            module = info.get("module")
            name = key
            if module is None and "." in key:
                module, name = key.split(".", 1)
            oclass = Class.find(name, module=module) if module else self._find_runtime(name)
            try:
                if oclass is None:
                    oclass = Class(name, module=module)
                    if "trl" in info:
                        oclass.trl = int(info["trl"])
            except ClassError as err:
                raise ModelError(f"class '{key}': {err}") from err
            specs.append((oclass, info))
        for oclass, info in specs:
            parent = info.get("parent")
            if parent is not None and oclass.parent is None:
                try:
                    oclass.set_parent(parent)
                except ClassError as err:
                    raise ModelError(f"class '{oclass.name}': {err}") from err
            for pname, pinfo in info.items():
                if isinstance(pinfo, dict):
                    self._load_property(oclass, pname, pinfo)
            self._use_class(oclass)
        return [oclass for oclass, _ in specs]

    @staticmethod
    def _find_runtime(name:str) -> Class|None:
        for oclass in Class.registry:
            if oclass.name == name and oclass.module is None:
                return oclass
        return None

    @staticmethod
    def _load_property(oclass:Class, name:str, info:dict) -> None:
        ptype = info.get("type")
        existing = {prop.name: prop for prop in oclass.properties()}
        if name in existing:
            if existing[name].ptype != ptype:
                raise ModelError(f"property {oclass.name}.{name} is defined as type {existing[name].ptype}, not {ptype}")
            return
        keywords = {key: int(value, 0) if isinstance(value, str) else int(value)
            for key, value in info.get("keywords", {}).items()} or None
        flags = "|".join(x for x in str(info.get("flags", "")).split("|") if x in FLAGS)
        access = info.get("access", "PUBLIC")
        try:
            oclass.publish(name, ptype, unit=info.get("unit"), keywords=keywords,
                access=access if access in ACCESS else "PUBLIC", flags=flags,
                description=info.get("description"), default=info.get("default"))
        except ClassError as err:
            raise ModelError(f"class '{oclass.name}': {err}") from err

    #
    # Objects
    #
    def _object(self, name:str) -> Object:
        if not isinstance(name, str) or name not in self.objects:
            raise ModelError(f"object '{name}' is not found")
        return self.objects[name]

    def _check_name(self, name:str, oclass:Class, oid:int) -> None:
        if not isinstance(name, str) or not name or re.search(r"[\s;{}\"]", name):
            raise ModelError(f"object name {name!r} is not valid")
        if not (name[0].isalpha() or name[0] == "_"):
            if not self.globals.getvalue("relax_naming_rules"):
                raise ModelError(f"object name '{name}' invalid, names must start with a letter or an underscore")
        if name in self.objects:
            raise ModelError(f"an object named '{name}' already exists")
        if ":" in name and name != f"{oclass.name}:{oid}" and re.fullmatch(r"[A-Za-z_]\w*:\d+", name):
            raise ModelError(f"object name '{name}' is reserved for an unnamed object")

    def _new_object(self, oclass:str|Class, name:str|None, oid:int|None,
            values:dict[str,Any], used_ids:set[int], pending:dict[str,Object]) -> tuple[str,Object]:
        """Build a validated object without adding it to the model; object
        references are checked later by `_check_refs()`"""
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        oclass = self.find_class(oclass)
        if oid is None:
            oid = max([self._next_id - 1, *used_ids]) + 1
        elif not isinstance(oid, int) or oid < 0:
            raise ModelError(f"object id {oid!r} is not valid")
        if oid in used_ids:
            raise ModelError(f"object id {oid} is already used")
        if name is None:
            name = f"{oclass.name}:{oid}"
        self._check_name(name, oclass, oid)
        if name in pending:
            raise ModelError(f"an object named '{name}' already exists")
        obj = Object(oclass, oid)
        for key, value in values.items():
            key, text = self._validate(obj, key, value)
            obj[key] = text
        return name, obj

    def _insert(self, name:str, obj:Object) -> None:
        self.objects[name] = obj
        obj.oclass.numobjs += 1
        self._next_id = max(self._next_id, obj.id + 1)

    def _ids(self) -> set[int]:
        return {obj.id for obj in self.objects.values()}

    def add_object(self, oclass:str|Class, name:str|None=None, properties:dict[str,Any]|None=None, oid:int|None=None, **kwargs) -> str:
        """Add an object

        Arguments
        ---------
        - `oclass`: class, class name, or `module.class`
        - `name`: object name; default `CLASS:ID`
        - `properties`: property values (for names that are not Python
          identifiers)
        - `oid`: object id; default is one more than the largest id used
        - `**kwargs`: property values

        Returns
        -------
        - `str`: the object name

        Exceptions
        ----------
        - `ModelError`: the class is not known, the name or id is not valid
          or already used, or a property or value is not valid
        """
        names = self.add_objects([{"class": oclass, "name": name, "id": oid, **(properties or {}), **kwargs}])
        return names[0]

    def add_objects(self, objects:list[dict[str,Any]]|dict[str,dict[str,Any]]) -> list[str]:
        """Add many objects; either all are added or none is

        Arguments
        ---------
        - `objects`: a list of dicts, or a dict keyed on object name, of
          property values; each dict gives `class`, and may give `name`
          and `id`. Objects may refer to each other.

        Returns
        -------
        - `list[str]`: the object names

        Exceptions
        ----------
        - `ModelError`: as for `add_object()`; no object is added
        """
        if isinstance(objects, dict):
            objects = [{**values, "name": name} for name, values in objects.items()]
        pending: dict[str,Object] = {}
        used = self._ids()
        for values in objects:
            values = dict(values)
            if "class" not in values:
                raise ModelError(f"object {values.get('name')!r} has no class")
            oclass, name, oid = values.pop("class"), values.pop("name", None), values.pop("id", None)
            name, obj = self._new_object(oclass, name, None if oid is None else int(oid), values, used, pending)
            pending[name] = obj
            used.add(obj.id)
        known = set(self.objects) | set(pending)
        for name, obj in pending.items():
            self._check_refs(name, obj, known, pending)
        for name, obj in pending.items():
            self._insert(name, obj)
        return list(pending)

    def _refs(self, obj:Object) -> list[tuple[str,str]]:
        """`(property, object name)` of each object reference in `obj`"""
        result = []
        for key, value in obj.items():
            if value and key not in READONLY and self._ptype(obj.oclass, key) == "object":
                result.append((key, value))
        return result

    def _check_refs(self, name:str, obj:Object, known:set[str], pending:dict[str,Object]) -> None:
        for key, value in self._refs(obj):
            if value not in known:
                raise ModelError(f"{name}.{key}: object '{value}' is not found")
        seen, parent = {name}, obj.get("parent")
        while parent:
            if parent in seen:
                raise ModelError(f"{name}.parent: '{obj['parent']}' makes a parent loop")
            seen.add(parent)
            other = pending.get(parent, self.objects.get(parent))
            parent = None if other is None else other.get("parent")

    def delete_object(self, name:str, children:str="error") -> list[str]:
        """Delete an object

        Arguments
        ---------
        - `name`: object name
        - `children`: what to do with objects that refer to it (as `parent`
          or through an `object` property): `error` raises `ModelError`,
          `orphan` removes the references, `delete` deletes the objects
          whose parent is deleted (recursively) and removes the other
          references

        Returns
        -------
        - `list[str]`: names of the objects deleted

        Exceptions
        ----------
        - `ModelError`: the object is not found, other objects refer to it
          and `children` is `error`, or `children` is not valid
        """
        return self.delete_objects([name], children)

    def delete_objects(self, names:Iterable[str], children:str="error") -> list[str]: # pylint: disable=too-many-branches
        """Delete many objects; either all are deleted or none is

        Arguments
        ---------
        - `names`: object names (e.g. the result of `find()`)
        - `children`: see `delete_object()`; references among the deleted
          objects are not counted

        Returns
        -------
        - `list[str]`: names of the objects deleted

        Exceptions
        ----------
        - `ModelError`: see `delete_object()`; no object is deleted
        """
        if children not in ("error", "orphan", "delete"):
            raise ModelError(f"children={children!r} is not valid (use error, orphan, or delete)")
        names = list(names) if not isinstance(names, str) else [names]
        for name in names:
            self._object(name)
        doomed = dict.fromkeys(names)
        if children == "delete":
            grown = True
            while grown:
                grown = False
                for name, obj in self.objects.items():
                    if name not in doomed and obj.get("parent") in doomed:
                        doomed[name] = None
                        grown = True
        referrers = []
        for name, obj in self.objects.items():
            if name not in doomed:
                refs = [key for key, value in self._refs(obj) if value in doomed]
                if refs:
                    referrers.append((name, refs))
        if referrers and children == "error":
            raise ModelError(f"cannot delete {', '.join(names)}: referred to by {', '.join(x for x, _ in referrers)}")
        for name, refs in referrers:
            for key in refs:
                del self.objects[name][key]
        for name in doomed:
            obj = self.objects.pop(name)
            obj.oclass.numobjs -= 1
        return list(doomed)

    def rename(self, name:str, newname:str) -> None:
        """Rename an object and update the references to it

        Exceptions
        ----------
        - `ModelError`: the object is not found, or the new name is not valid
          or already used
        """
        obj = self._object(name)
        if newname == name:
            return
        self._check_name(newname, obj.oclass, obj.id)
        items = [((newname if key == name else key), value) for key, value in self.objects.items()]
        self.objects.clear()
        self.objects.update(items)
        for other in self.objects.values():
            for key, value in self._refs(other):
                if value == name:
                    other[key] = newname

    def find(self, pattern:str|re.Pattern, prop:str="name", oclass:str|None=None) -> list[str]:
        """Search objects with a regular expression

        Arguments
        ---------
        - `pattern`: regular expression, matched with `re.search`
        - `prop`: property whose value is searched (default the object name;
          `class` and `id` are allowed); properties that an object does not
          set are matched with the class default
        - `oclass`: only search objects of this class or of classes that
          inherit from it

        Returns
        -------
        - `list[str]`: names of the matching objects, in model order

        Exceptions
        ----------
        - `ModelError`: the pattern is not a valid regular expression
        """
        try:
            regex = re.compile(pattern) if isinstance(pattern, str) else pattern
        except re.error as err:
            raise ModelError(f"pattern {pattern!r} is not valid ({err})") from err
        result = []
        for name, obj in self.objects.items():
            if oclass is not None and not obj.oclass.isa(oclass):
                continue
            value = name if prop == "name" else self._get(obj, prop, missing=None)
            if value is not None and regex.search(value):
                result.append(name)
        return result

    #
    # Properties
    #
    @staticmethod
    def _ptype(oclass:Class, key:str) -> str|None:
        if key in HEADER:
            return HEADER[key]
        for check in [oclass] + _parents(oclass):
            for prop in check.properties():
                if prop.name == key:
                    return prop.ptype
        return None

    def _get(self, obj:Object, key:str, missing:Any=ModelError) -> str|None:
        key = JSON_ALIASES.get(key, key)
        if key in obj:
            return obj[key]
        if key in HEADER or _event(key):
            return None
        prop = obj.oclass.find_property(key)
        if prop is None:
            if missing is ModelError:
                raise ModelError(f"class '{obj.oclass.name}' has no property '{key}'")
            return missing
        return _default(prop)

    def get_property(self, name:str, prop:str) -> str|None:
        """Get a property value

        Arguments
        ---------
        - `name`: object name
        - `prop`: property name

        Returns
        -------
        - `str`: the value set, else the class default, else the type default
          (`None` when there is none, and for header properties that are not
          set)

        Exceptions
        ----------
        - `ModelError`: the object is not found or its class has no such
          property
        """
        obj = self._object(name)
        if prop == "name":
            return name
        return self._get(obj, prop)

    def get_properties(self, name:str|Iterable[str], props:Iterable[str]|None=None) -> dict[str,Any]:
        """Get many property values

        Arguments
        ---------
        - `name`: object name, or a list of object names
        - `props`: property names; default is every property the object sets

        Returns
        -------
        - `dict[str,str]`: values keyed on property name; for a list of
          objects, a dict of these keyed on object name

        Exceptions
        ----------
        - `ModelError`: see `get_property()`
        """
        if not isinstance(name, str):
            return {item: self.get_properties(item, props) for item in name}
        obj = self._object(name)
        if props is None:
            return dict(obj)
        return {prop: self.get_property(name, prop) for prop in props}

    def set_property(self, name:str, prop:str, value:Any) -> None:
        """Set a property value

        Arguments
        ---------
        - `name`: object name
        - `prop`: property name
        - `value`: value (text or Python value); `None` removes the value so
          the class default applies

        Exceptions
        ----------
        - `ModelError`: the object is not found, the property is read-only or
          not defined by the object's class, or the value is not valid
        """
        self.set_properties(name, {prop: value})

    def set_properties(self, name:str|Iterable[str], values:dict[str,Any]) -> None:
        """Set many property values; either all are set or none is

        Arguments
        ---------
        - `name`: object name, or a list of object names that all get the
          values
        - `values`: values keyed on property name (see `set_property()`)

        Exceptions
        ----------
        - `ModelError`: see `set_property()`; no value is set
        """
        names = [name] if isinstance(name, str) else list(name)
        changes = []
        for item in names:
            obj = self._object(item)
            trial = Object(obj.oclass, obj.id, obj)
            for key, value in values.items():
                key = JSON_ALIASES.get(key, key)
                if key in READONLY:
                    raise ModelError(f"{item}.{key} cannot be set" + (" (use rename())" if key == "name" else ""))
                if value is None:
                    if key not in HEADER and not _event(key) and _lacks(obj.oclass, key):
                        raise ModelError(f"class '{obj.oclass.name}' has no property '{key}'")
                    trial.pop(key, None)
                    continue
                key, text = self._validate(obj, key, value)
                trial[key] = text
            changes.append((item, obj, trial))
        known = set(self.objects)
        pending = {item: trial for item, _, trial in changes}
        for item, _, trial in changes:
            self._check_refs(item, trial, known, pending)
        for _, obj, trial in changes:
            obj.clear()
            obj.update(trial)

    def _validate(self, obj:Object, key:str, value:Any) -> tuple[str,str]:
        """Check a property name and value; returns `(key, text)`"""
        key = JSON_ALIASES.get(key, key)
        oclass = obj.oclass
        if key in HEADER:
            if key in READONLY:
                raise ModelError(f"{oclass.name}.{key} is read-only")
            ptype = {"guid": "string", "flags": "string", "rng_state": "int64"}.get(key, HEADER[key])
            return key, self._check(oclass, key, ptype, None, value)
        if _event(key):
            return key, str(value)
        prop = oclass.find_property(key)
        if prop is None:
            raise ModelError(f"class '{oclass.name}' has no property '{key}'")
        return key, self._check(oclass, key, prop.ptype, prop, value)

    def _check(self, oclass:Class, key:str, ptype:str, prop:Property|None, value:Any) -> str: # pylint: disable=too-many-arguments,too-many-positional-arguments
        try:
            return self._convert(ptype, prop, value, key)
        except (ValueError, GlobalsError, UnitsError, ClassError) as err:
            message = f"{oclass.name}.{key}: {err}"
            if self.strict:
                raise ModelError(message) from err
            _logger.warning("%s (stored as given)", message)
            return value if isinstance(value, str) else str(value)

    def _convert(self, ptype:str, prop:Property|None, value:Any, key:str) -> str:
        """Convert and check a value for a property type; raises `ValueError`"""
        # pylint: disable=too-many-return-statements,too-many-branches
        if ptype in DOUBLE_TYPES:
            if key in ("latitude", "longitude") and isinstance(value, str) and _LATLON.match(value.strip()):
                return value.strip()
            return self._double(prop, value)
        if ptype == "complex":
            return self._complex(prop, value)
        if isinstance(value, bool):
            value = "TRUE" if value else "FALSE"
        if ptype == "set" and isinstance(value, (list, tuple, set, frozenset)):
            value = "|".join(str(x) for x in value)
        text = str(value).strip() if not isinstance(value, str) else value.strip()
        if ptype in INTEGER_BITS:
            if not _INTEGER.match(text):
                raise ValueError(f"'{text}' is not a valid {ptype}")
            bits = INTEGER_BITS[ptype]
            limit = 1 << (bits if "x" in text.lower() else bits-1)
            if not -(1 << (bits-1)) <= int(text, 0) < limit:
                raise ValueError(f"value {text} is out of range for {ptype}")
            return text
        if ptype == "bool":
            if text.upper() in ("TRUE", "FALSE"):
                return text.upper()
            if _INTEGER.match(text):
                return "TRUE" if int(text, 0) else "FALSE"
            raise ValueError(f"'{text}' is not a valid bool")
        if ptype == "enumeration":
            if prop is not None and prop.keywords and text not in prop.keywords and not _INTEGER.match(text):
                raise ValueError(f"'{text}' is not a keyword of {prop.name}")
            return text
        if ptype == "set":
            return self._set(prop, text)
        if ptype == "timestamp":
            unquoted = text.strip("'\"")
            if not _DATETIME.match(unquoted):
                self.globals.timestamp_from_string(unquoted)
            return unquoted
        if ptype in CHAR_SIZES:
            if len(text) >= CHAR_SIZES[ptype]:
                raise ValueError(f"'{text}' is longer than {CHAR_SIZES[ptype]-1} characters")
            return text
        if ptype == "object":
            if text and re.search(r"\s", text):
                raise ValueError(f"'{text}' is not a valid object name")
            return text
        return value if isinstance(value, str) else text

    def _double(self, prop:Property|None, value:Any) -> str: # pylint: disable=too-many-return-statements
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _fmt(value)
        text = str(value).strip()
        match = _DOUBLE.match(text)
        if match:
            number, unit = match.groups()
            if unit is None:
                return text
            if prop is None or prop.unit is None:
                raise ValueError(f"unit '{unit}' given to unitless property")
            if unit == prop.unit:
                return text
            return f"{_fmt(Class.get_units().convert(float(number), unit, prop.unit))} {prop.unit}"
        if _RANDOM.match(text):
            return text
        match = _FILTER.match(text)
        if match and match.group(1) in self.filters:
            return text
        match = _TRANSFORM.match(text)
        if match and (match.group(1) in self.schedules or "." in match.group(1)):
            return text
        raise ValueError(f"'{text}' is not a valid double")

    def _complex(self, prop:Property|None, value:Any) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = complex(value)
        if isinstance(value, complex):
            return f"{_fmt(value.real)}{_signed(value.imag)}j"
        if isinstance(value, (list, tuple)) and len(value) in (2, 3):
            unit = f" {value[2]}" if len(value) == 3 else ""
            value = f"{_fmt(value[0])}{_signed(value[1])}j{unit}"
        elif isinstance(value, dict):
            unit = f" {value['unit']}" if "unit" in value else ""
            for xs, ys, nt in (("real","imag","j"), ("mag","ang","d"), ("mag","arg","r")):
                if xs in value and ys in value:
                    value = f"{_fmt(value[xs])}{_signed(value[ys])}{nt}{unit}"
                    break
            else:
                raise ValueError(f"{value!r} is not a valid complex")
        text = str(value).strip()
        match = _COMPLEX.match(text)
        if not match:
            raise ValueError(f"'{text}' is not a valid complex")
        real, imag, notation, unit = match.groups()
        if unit is None or (prop is not None and unit == prop.unit):
            return text
        if prop is None or prop.unit is None:
            raise ValueError(f"unit '{unit}' given to unitless property")
        units = Class.get_units()
        imag = float(imag.replace(" ", "")) if imag else 0.0
        notation = notation or "j"
        if notation in "ij":
            result = units.convert(complex(float(real), imag), unit, prop.unit)
            return f"{_fmt(result.real)}{_signed(result.imag)}{notation} {prop.unit}"
        return f"{_fmt(units.convert(float(real), unit, prop.unit))}{_signed(imag)}{notation} {prop.unit}"

    @staticmethod
    def _set(prop:Property|None, text:str) -> str:
        if prop is None or not prop.keywords or text == "" or _INTEGER.match(text):
            return text
        if "|" in text:
            parts = [x for x in text.split("|") if x]
        elif prop.has_flag("CHARSET") and text not in prop.keywords:
            parts = list(text)
        else:
            parts = [text]
        for part in parts:
            if part not in prop.keywords:
                raise ValueError(f"'{part}' is not a keyword of {prop.name}")
        return text

    def check(self) -> list[str]:
        """Check the model

        Returns
        -------
        - `list[str]`: problems found: object references that are not found,
          parent loops, and `REQUIRED` properties that are not set (empty
          when none are found)
        """
        problems = []
        known = set(self.objects)
        for name, obj in self.objects.items():
            try:
                self._check_refs(name, obj, known, {})
            except ModelError as err:
                problems.append(str(err))
            for prop in obj.oclass.properties(inherit=True):
                if prop.has_flag("REQUIRED") and prop.name not in obj:
                    problems.append(f"{name}.{prop.name}: required property is not set")
        return problems

    #
    # Files
    #
    def read(self, file:str) -> None:
        """Read a `.glm` or `.json` file into the model

        Exceptions
        ----------
        - `ModelError`: the file type is not supported or the file is not
          valid (see `read_glm()` and `read_json()`)
        """
        ext = os.path.splitext(file)[1].lower()
        if ext == ".glm":
            self.read_glm(file)
        elif ext == ".json":
            self.read_json(file)
        else:
            raise ModelError(f"file type '{ext}' is not supported (use .glm or .json)")

    def write(self, file:str) -> None:
        """Write the model to a `.glm` or `.json` file

        Exceptions
        ----------
        - `ModelError`: the file type is not supported
        """
        ext = os.path.splitext(file)[1].lower()
        if ext == ".glm":
            self.write_glm(file)
        elif ext == ".json":
            self.write_json(file)
        else:
            raise ModelError(f"file type '{ext}' is not supported (use .glm or .json)")

    #
    # JSON
    #
    @staticmethod
    def _json_data(data:dict|str) -> dict:
        if isinstance(data, str):
            try:
                if data.lstrip().startswith("{"):
                    data = json.loads(data)
                else:
                    with open(data, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
            except (OSError, json.JSONDecodeError) as err:
                raise ModelError(f"unable to read JSON ({err})") from err
        if not isinstance(data, dict) or data.get("application") != "gridlabd":
            raise ModelError("JSON data is not from gridlabd (no 'application': 'gridlabd')")
        return data

    def read_json(self, data:dict|str) -> None:
        """Read gridlabd JSON into the model (gridlabd `GldJsonWriter` format)

        Classes are registered with `load_classes()`. Globals that are not
        defined are created with the type given; a global value that cannot
        be converted is logged as a warning and skipped. Objects are added in
        id order and their values validated.

        Arguments
        ---------
        - `data`: JSON dict, JSON text, or JSON file name

        Exceptions
        ----------
        - `ModelError`: the data is not gridlabd JSON, a class is not known,
          or an object, property, or value is not valid
        """
        data = self._json_data(data)
        self.load_classes(data)
        for name, info in data.get("globals", {}).items():
            self._load_global(name, info)
        self.schedules.update(data.get("schedules", {}))
        self.filters.update(data.get("filters", {}))
        objects = sorted(data.get("objects", {}).items(), key=lambda x: int(x[1].get("id", 0)))
        batch = []
        for name, info in objects:
            values = {JSON_ALIASES.get(key, key): value for key, value in info.items()}
            if values.get("parent", "") == "":
                values.pop("parent", None)
            batch.append({**values, "name": name})
        self.add_objects(batch)

    def _load_global(self, name:str, info:dict) -> None:
        value = info.get("value")
        try:
            if not self.globals.isdefined(name):
                ptype = info.get("type", "char1024")
                keywords = {key: int(val, 0) for key, val in info.get("keywords", {}).items()} or None
                match = _DOUBLE.match(str(value)) if ptype == "double" else None
                self.globals.create(name, ptype=ptype if ptype in PROPERTY_TYPES else "char1024",
                    access=info.get("access", "PUBLIC") if info.get("access") in ACCESS else "PUBLIC",
                    keywords=keywords, unit=match.group(2) if match else None)
            if value is not None and self.globals.get(name) != value:
                self.globals.set(name, value)
        except (GlobalsError, ValueError) as err:
            _logger.warning("global '%s' not set (%s)", name, err)

    def to_json(self) -> dict:
        """The model as a dict in gridlabd's JSON format

        Each object lists its id, class, the header properties that are set,
        the properties that are set, and then, as gridlabd does, the class
        default (else the type default) of every other `PUBLIC` property of
        its class and parents (own properties first), except properties with
        no default and `enduse` and `method` properties. When the
        `filesave_options` global has the `MINIMAL` bit (`FSO_MINIMAL`), the
        defaults are left out.
        """
        data: dict[str,Any] = {"application": "gridlabd", "version": self._version()}
        data["modules"] = {name: {"major": str(info["major"]), "minor": str(info["minor"])}
            for name, info in self.modules.items()}
        data["header"] = {name: {"type": ptype, "access": "PROTECTED"} for name, ptype in HEADER.items()}
        data["classes"] = {oclass.name: _class_json(oclass) for oclass in self._class_order()}
        data["globals"] = self._globals_json()
        data["schedules"] = dict(self.schedules)
        if self.filters:
            data["filters"] = dict(self.filters)
        data["objects"] = {}
        minimal = self.globals.find("filesave_options").value & FSO_MINIMAL
        for name, obj in self.objects.items():
            item = {"id": obj["id"], "class": obj["class"]}
            for key in HEADER:
                if key in obj and key not in item:
                    item[{"in_svc": "in", "out_svc": "out"}.get(key, key)] = obj[key]
            item.update({key: value for key, value in obj.items() if key not in HEADER})
            if not minimal:
                for prop in obj.oclass.properties(inherit=True):
                    default = _default(prop)
                    if prop.name not in item and prop.access == "PUBLIC" and default is not None \
                            and prop.ptype not in ("enduse", "method"):
                        item[prop.name] = default
            data["objects"][name] = item
        return data

    def write_json(self, file:str|None=None, indent:int|None=4) -> str:
        """Write the model as gridlabd JSON

        Arguments
        ---------
        - `file`: file name (default: only return the text)
        - `indent`: JSON indentation

        Returns
        -------
        - `str`: the JSON text
        """
        text = json.dumps(self.to_json(), indent=indent) + "\n"
        if file is not None:
            with open(file, "w", encoding="utf-8") as fh:
                fh.write(text)
        return text

    def _version(self) -> str:
        return ".".join(str(self.globals.getvalue(f"version.{x}") or 0) for x in ("major","minor","patch"))

    def _class_order(self) -> list[Class]:
        return sorted(self.classes.values(), key=lambda oclass: oclass.id)

    def _globals_json(self) -> dict:
        result = {}
        for name in self.globals:
            var = self.globals.find(name)
            value = self.globals.get(name)
            if var is None or value is None or var.name != name:
                continue
            item: dict[str,Any] = {"type": var.ptype}
            if var.keywords:
                item["keywords"] = {key: f"0x{code & 0xffffffffffffffff:x}" for key, code in var.keywords.items()}
            item["access"] = var.access
            item["value"] = value[1:-1] if value.startswith('"') and value.endswith('"') else value
            result[name] = item
        return result

    #
    # GLM
    #
    def read_glm(self, source:str) -> None:
        """Read GLM into the model

        Arguments
        ---------
        - `source`: GLM file name, or GLM text (any string that contains a
          newline or `{` is read as text)

        Exceptions
        ----------
        - `ModelError`: the file cannot be read, or the GLM is not valid or
          not supported (the message names the file and line)
        """
        if "\n" in source or "{" in source:
            text, filename = source, "(text)"
        else:
            filename = source
            text = self._read_file(source)
        lines = self._preprocess(text, filename, 0, [])
        scanner = _Scanner("\n".join(x for x, _, _ in lines), [(f, n) for _, f, n in lines])
        while scanner.skip():
            self._directive(scanner)
        self._resolve()

    @staticmethod
    def _read_file(filename:str) -> str:
        try:
            with open(filename, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as err:
            raise ModelError(f"unable to read '{filename}' ({err})") from err

    def _preprocess(self, text:str, filename:str, depth:int, stack:list) -> list[tuple[str,str,int]]:
        """Remove comments, run macros, and expand `${...}`; returns
        `(line, file, number)` for each output line"""
        # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        result = []
        multiline = False
        start = len(stack)
        for number, line in enumerate(text.split("\n"), 1):
            line = line.rstrip("\r")
            where = f"{filename}({number})"
            active = all(stack)
            if multiline:
                multiline = line.count('"""') % 2 == 0
                result.append((line if active else "", filename, number))
                continue
            line = _uncomment(line)
            stripped = line.strip()
            if stripped.startswith("#"):
                match = re.match(r"#(\w+)\s*(.*)$", stripped)
                macro, arg = (match.group(1), match.group(2).strip()) if match else ("", "")
                if macro in ("ifdef", "ifndef"):
                    stack.append(self.globals.isdefined(arg) == (macro == "ifdef"))
                elif macro == "else":
                    if len(stack) <= start:
                        raise ModelError(f"{where}: #else without #ifdef or #ifndef")
                    stack[-1] = not stack[-1]
                elif macro == "endif":
                    if len(stack) <= start:
                        raise ModelError(f"{where}: #endif without #ifdef or #ifndef")
                    stack.pop()
                elif active:
                    arg = self._expand(arg, where)
                    if macro == "include":
                        result.extend(self._include(arg, filename, depth, where, stack))
                        continue
                    self._macro(macro, arg, where)
                result.append(("", filename, number))
                continue
            if active:
                if line.count('"""') % 2 == 1:
                    multiline = True
                result.append((self._expand(line, where), filename, number))
            else:
                result.append(("", filename, number))
        if len(stack) > start:
            raise ModelError(f"{filename}: missing #endif")
        return result

    def _expand(self, text:str, where:str) -> str:
        if "${" not in text:
            return text
        try:
            return self.globals.expand(text)
        except GlobalsError as err:
            raise ModelError(f"{where}: {err}") from err

    def _include(self, arg:str, filename:str, depth:int, where:str, stack:list) -> list:
        name = arg.strip()
        if len(name) >= 2 and name[0] + name[-1] in ('""', "<>"):
            name = name[1:-1]
        if depth >= MAXINCLUDE:
            raise ModelError(f"{where}: #include nesting is too deep")
        search = [os.path.dirname(filename) if filename != "(text)" else ""]
        path = arras.folders.search_path()
        search += path[:1] + [arras.folders.userdir("include")] + path[1:]
        for folder in search:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return self._preprocess(self._read_file(path), path, depth+1, stack)
        raise ModelError(f"{where}: #include file '{name}' is not found")

    def _macro(self, macro:str, arg:str, where:str) -> None:
        try:
            if macro in ("set", "define"):
                match = re.match(r"([^\s=]+)\s*=\s*(.*)$", arg)
                if not match:
                    raise ModelError(f"{where}: #{macro} {arg} is not formatted as NAME=VALUE")
                name, value = match.group(1), match.group(2).strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                if not self.globals.isdefined(name) and (macro == "define" or "::" in name):
                    self.globals.create(name, value, ptype="char1024")
                else:
                    self.globals.set(name, value)
            elif macro in ("print", "warning", "debug", "verbose"):
                getattr(_logger, {"print":"info","verbose":"info"}.get(macro, macro))("%s: %s", where, arg)
            elif macro == "error":
                raise ModelError(f"{where}: #error {arg}")
            else:
                raise ModelError(f"{where}: macro '#{macro}' is not supported")
        except GlobalsError as err:
            raise ModelError(f"{where}: {err}") from err

    def _directive(self, scanner:_Scanner) -> None:
        if scanner.literal(";"):
            return
        start = scanner.pos
        word = scanner.word(re.compile(r"[A-Za-z_]\w*"))
        handlers = {
            "clock": self._glm_clock,
            "module": self._glm_module,
            "class": self._glm_class,
            "object": lambda s: self._instantiate(self._glm_object(s), None),
            "global": self._glm_global,
            "modify": self._glm_modify,
            "schedule": self._glm_schedule,
            "filter": self._glm_filter,
        }
        if word not in handlers:
            raise scanner.error(f"'{word or scanner.token()}' is not a supported GLM directive", start)
        handlers[word](scanner)

    def _glm_clock(self, scanner:_Scanner) -> None:
        scanner.expect("{", "after clock")
        while not scanner.literal("}"):
            pos = scanner.pos
            key = scanner.word()
            if key is None:
                raise scanner.error("expected clock property")
            value = scanner.value().strip("'\"")
            key = {"timezone": "timezone_locale", "tz": "timezone_locale"}.get(key, key)
            try:
                self.globals.set(key, value)
            except GlobalsError as err:
                raise scanner.error(f"clock {key}: {err}", pos) from err

    def _glm_module(self, scanner:_Scanner) -> None:
        name = scanner.word(re.compile(r"[A-Za-z_][\w]*(?:::[A-Za-z_]\w*)?"))
        if name is None:
            raise scanner.error("expected module name")
        self.load_module(name)
        if scanner.literal(";"):
            return
        scanner.expect("{", f"to open module {name} block")
        while not scanner.literal("}"):
            pos = scanner.pos
            key = scanner.word()
            if key is None:
                raise scanner.error(f"expected module {name} property")
            value = scanner.value()
            try:
                if key in ("major", "minor"):
                    self.modules[name][key] = int(value)
                elif key == "class":
                    oclass = Class.find(value, module=name) or Class(value, module=name)
                    self._use_class(oclass)
                else:
                    gname = f"{name}::{key}"
                    if not self.globals.isdefined(gname):
                        self.globals.create(gname, value, ptype="char1024")
                    else:
                        self.globals.set(gname, value)
            except (ValueError, GlobalsError, ClassError) as err:
                raise scanner.error(f"module {name} {key}: {err}", pos) from err

    def _glm_class(self, scanner:_Scanner) -> None:
        pos = scanner.pos
        name = scanner.word()
        if name is None:
            raise scanner.error("expected class name")
        parent = inherit = None
        if scanner.literal(":"):
            inherit = scanner.word() or ""
            parent = scanner.word()
        try:
            oclass = Class.declare(name, parent, inherit or "public") if parent else Class.declare(name)
        except ClassError as err:
            raise scanner.error(str(err), pos) from err
        scanner.expect("{", f"to open class {name} block")
        while not scanner.literal("}"):
            pos = scanner.pos
            item = scanner.statement()
            try:
                self._class_item(oclass, item)
            except ClassError as err:
                raise scanner.error(f"class {name}: {err}", pos) from err
            except ModelError as err:
                raise scanner.error(str(err), pos) from err
        self._use_class(oclass)

    @staticmethod
    def _class_item(oclass:Class, item:str) -> None:
        match = re.fullmatch(r"parent\s+(\S+)", item)
        if match:
            oclass.set_parent(match.group(1))
            return
        match = re.fullmatch(r"(on_\w+)\s+(.*)", item, re.DOTALL)
        if match:
            oclass.set_event(match.group(1), _unquote(match.group(2).strip()))
            return
        match = re.fullmatch(r"(\w+)\s*(?:\{([^}]*)\})?\s*([A-Za-z_][\w.]*)(?:\[([^\]]+)\])?", item)
        if not match or match.group(1) not in PROPERTY_TYPES:
            raise ModelError(f"class {oclass.name}: '{item}' is not a supported class member")
        ptype, spec, pname, unit = match.groups()
        keywords = None
        if spec is not None:
            keywords = {}
            for part in (x.strip() for x in spec.split(",") if x.strip()):
                kmatch = re.fullmatch(r"(\w+)\s*=\s*([-+]?(?:0[xX][0-9a-fA-F]+|\d+))", part)
                if not kmatch:
                    raise ModelError(f"class {oclass.name}: keyword '{part}' is not formatted as NAME=VALUE")
                keywords[kmatch.group(1)] = int(kmatch.group(2), 0)
        oclass.add_property(pname, ptype, unit=unit, keywords=keywords)

    def _glm_object(self, scanner:_Scanner) -> _ObjectSpec:
        pos = scanner.pos
        spec = scanner.token()
        match = re.fullmatch(r"([A-Za-z_][\w.]*)(?::(?:(\d+)\.\.(\d+)|\.\.(\d+)|(\d+)))?", spec)
        if not match:
            raise scanner.error(f"'{spec}' is not a valid object class and id", pos)
        try:
            oclass = self.find_class(match.group(1))
        except ModelError as err:
            raise scanner.error(str(err), pos) from err
        first, last, count, single = match.group(2, 3, 4, 5)
        if first is not None:
            result = _ObjectSpec(oclass, int(first), int(last) - int(first) + 1, True, scanner.where(pos))
        elif count is not None:
            result = _ObjectSpec(oclass, None, int(count), False, scanner.where(pos))
        else:
            result = _ObjectSpec(oclass, None if single is None else int(single), 1, single is not None, scanner.where(pos))
        scanner.expect("{", "to open object block")
        while not scanner.literal("}"):
            ppos = scanner.pos
            key = scanner.word(re.compile(r"[A-Za-z_][\w.:]*"))
            if key is None:
                raise scanner.error("expected property name or nested object")
            if key == "object":
                result.children.append(self._glm_object(scanner))
                scanner.literal(";")
                continue
            result.props.append((key, scanner.value(), scanner.where(ppos)))
        return result

    def _instantiate(self, spec:_ObjectSpec, parent:str|None) -> None: # pylint: disable=too-many-branches
        for index in range(spec.count):
            oid = None if spec.first is None else spec.first + index
            name = None
            for key, value, _ in spec.props:
                if key == "name":
                    name = value
            used = self._ids()
            try:
                name, obj = self._new_object(spec.oclass, name, oid, {}, used, {})
            except ModelError as err:
                raise ModelError(f"{spec.where}: {err}") from err
            if parent is not None:
                obj["parent"] = parent
            for key, value, where in spec.props:
                if key == "name":
                    continue
                if key == "root":
                    obj.pop("parent", None)
                    continue
                try:
                    if value == "inherit" and key != "parent":
                        value = self._get(self._object(obj.get("parent")), key) if obj.get("parent") else None
                        if value is None:
                            raise ModelError(f"cannot inherit {key}, the parent is not set or has no value")
                    elif value.startswith("@") and re.fullmatch(r"@[A-Za-z_][\w.:]*", value) and self._ptype(obj.oclass, key) != "object":
                        value = self._get(self._object(value[1:]), key)
                    key, text = self._validate(obj, key, value)
                    obj[key] = text
                except ModelError as err:
                    raise ModelError(f"{where}: {err}") from err
            self._insert(name, obj)
            for child in spec.children:
                self._instantiate(child, name)

    def _glm_global(self, scanner:_Scanner) -> None:
        pos = scanner.pos
        item = scanner.statement()
        match = re.fullmatch(r"(\w+)\s+([\w.:]+)(?:\[([^\]]+)\])?\s+(.*)", item, re.DOTALL)
        if not match or match.group(1) not in PROPERTY_TYPES:
            raise scanner.error(f"global '{item}' is not formatted as TYPE NAME[UNIT] VALUE", pos)
        ptype, name, unit, value = match.groups()
        value = _unquote(value.strip())
        try:
            if self.globals.isdefined(name):
                self.globals.set(name, value)
            else:
                self.globals.create(name, value, ptype=ptype, unit=unit)
        except GlobalsError as err:
            raise scanner.error(f"global {name}: {err}", pos) from err

    def _glm_modify(self, scanner:_Scanner) -> None:
        pos = scanner.pos
        target = scanner.token()
        value = scanner.value()
        for index in [i for i, c in enumerate(target) if c == "."][::-1]:
            name, key = target[:index], target[index+1:]
            if name in self.objects:
                break
        else:
            raise scanner.error(f"modify target '{target}' does not name an object property", pos)
        try:
            obj = self.objects[name]
            key, text = self._validate(obj, key, value)
            if key in READONLY: # pragma: no cover
                raise ModelError(f"{name}.{key} cannot be modified")
            obj[key] = text
        except ModelError as err:
            raise scanner.error(str(err), pos) from err

    def _glm_schedule(self, scanner:_Scanner) -> None:
        name = scanner.word()
        if name is None:
            raise scanner.error("expected schedule name")
        self.schedules[name] = _dedent(scanner.block())

    def _glm_filter(self, scanner:_Scanner) -> None:
        pos = scanner.pos
        text = scanner.statement()
        match = re.match(r"([A-Za-z_]\w*)\s*\(", text)
        if not match:
            raise scanner.error(f"filter '{text}' is not formatted as NAME(...) = ...", pos)
        self.filters[match.group(1)] = text

    def _resolve(self) -> None:
        known = set(self.objects)
        for name, obj in self.objects.items():
            self._check_refs(name, obj, known, {})

    def write_glm(self, file:str|None=None) -> str:
        """Write the model as GLM

        The GLM holds the clock, the `PUBLIC` globals that differ from their
        defaults (except `NOSAVE_GLOBALS`), modules and their globals, runtime classes and the
        extended properties of module classes, schedules, filters, and
        objects with their ids, in that order.

        Arguments
        ---------
        - `file`: file name (default: only return the text)

        Returns
        -------
        - `str`: the GLM text
        """
        out = ["// generated by arras.model\n"]
        out.append(self._glm_clock_text())
        out.append(self._glm_globals_text())
        for name in self.modules:
            items = [f"\t{key[len(name)+2:]} {_quote(self.globals.get(key))};\n"
                for key in self.globals if key.startswith(f"{name}::") and self.globals.get(key) is not None]
            out.append(f"module {name} {{\n{''.join(items)}}}\n" if items else f"module {name};\n")
        for oclass in self._class_order():
            out.append(_class_glm(oclass))
        for name, text in self.schedules.items():
            body = "".join(f"\t{line}\n" for line in text.split("\n"))
            out.append(f"schedule {name} {{\n{body}}}\n")
        for name, spec in self.filters.items():
            out.append(f"filter {spec if isinstance(spec, str) else _filter_text(name, spec)};\n")
        for name, obj in self.objects.items():
            out.append(self._object_glm(name, obj))
        text = "".join(out)
        if file is not None:
            with open(file, "w", encoding="utf-8") as fh:
                fh.write(text)
        return text

    def _global_text(self, name:str) -> str|None:
        """GLM text of a global; timestamps are written in UTC so that any
        `timezone_locale` reads them back to the same time"""
        var = self.globals.find(name)
        if var is not None and var.ptype == "timestamp" and 0 < var.value < TS_NEVER:
            return datetime.datetime.fromtimestamp(var.value, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return self.globals.get(name)

    def _glm_clock_text(self) -> str:
        lines = [f"\t{key} {_quote(self._global_text(name))};\n"
            for key, name in (("timezone","timezone_locale"), ("starttime","starttime"), ("stoptime","stoptime"))]
        return "clock {\n" + "".join(lines) + "}\n"

    def _glm_globals_text(self) -> str:
        defaults = Model._default_globals
        if defaults is None:
            fresh = Globals()
            defaults = Model._default_globals = {name: fresh.get(name) for name in fresh}
        lines = []
        for name in self.globals:
            if "::" in name or name in ("timezone_locale", "starttime", "stoptime", "clock"):
                continue
            var = self.globals.find(name)
            if var is None or var.name != name or var.access != "PUBLIC" or name in NOSAVE_GLOBALS:
                continue
            value = self._global_text(name)
            if name not in defaults:
                lines.append(f"#define {name}={value}\n")
            elif value != defaults[name]:
                lines.append(f"#set {name}={value}\n")
        return "".join(lines)

    @staticmethod
    def _object_glm(name:str, obj:Object) -> str:
        oclass = obj.oclass
        cname = f"{oclass.module}.{oclass.name}" if oclass.module else oclass.name
        lines = [f"object {cname}:{obj['id']} {{\n"]
        if name != f"{oclass.name}:{obj['id']}":
            lines.append(f"\tname {_quote(name)};\n")
        for key, value in obj.items():
            if key not in ("id", "class"):
                lines.append(f"\t{key} {_quote(value)};\n")
        lines.append("}\n")
        return "".join(lines)

def _parents(oclass:Class) -> list[Class]:
    result = []
    while oclass.parent is not None:
        oclass = oclass.parent
        result.append(oclass)
    return result

def _default(prop:Property) -> str|None:
    """Value of a property that is not set: the class default, else the type
    default (gridlabd zeroes the memory of properties added by a GLM `class`
    block, which have no default)"""
    return prop.default if prop.default is not None else PROPERTY_TYPES[prop.ptype][1]

def _lacks(oclass:Class, key:str) -> bool:
    """@private Check whether a class and its parents lack a property"""
    return oclass.find_property(key) is None

def _event(key:str) -> bool:
    return key.startswith("on_") and key[3:] in EVENTS

def _uncomment(line:str) -> str:
    """Remove a `//` comment that is not inside double quotes"""
    if "//" not in line:
        return line
    quote = False
    for index, char in enumerate(line):
        if char == '"' and (index == 0 or line[index-1] != "\\"):
            quote = not quote
        elif not quote and line.startswith("//", index):
            return line[:index]
    return line

def _unquote(text:str) -> str:
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return re.sub(r"\\(.)", r"\1", text[1:-1])
    return text

def _quote(value:str|None) -> str:
    """GLM text of a value"""
    value = "" if value is None else value
    if "\n" in value:
        return '"""' + value.replace("\\", "\\\\").replace('"', '\\"') + '"""'
    if value.startswith("{") and value.endswith("}"):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

def _dedent(text:str) -> str:
    lines = [line.rstrip() for line in text.strip("\n").split("\n")]
    indent = min((len(x) - len(x.lstrip()) for x in lines if x.strip()), default=0)
    return "\n".join(line[indent:] for line in lines).strip("\n")

def _class_json(oclass:Class) -> dict:
    """Class entry of gridlabd's JSON `classes` section (`write_classes()`)"""
    result: dict[str,Any] = {}
    if oclass.parent is not None:
        result["parent"] = oclass.parent.name
    result["trl"] = str(oclass.trl)
    if oclass.module is not None:
        result["module"] = oclass.module
    for prop in oclass.properties():
        item: dict[str,Any] = {"type": prop.ptype, "access": prop.access}
        if prop.keywords:
            item["keywords"] = {key: f"0x{value & 0xffffffff:x}" for key, value in prop.keywords.items()}
        flags = "|".join(key for key in ("RECALC","CHARSET","EXTENDED","DEPRECATED","DEPRECATED_NONOTICE","REQUIRED","OUTPUT","DYNAMIC") if prop.has_flag(key))
        if flags:
            item["flags"] = flags
        if prop.unit is not None:
            item["unit"] = prop.unit
        if prop.default is not None and prop.default != PROPERTY_TYPES[prop.ptype][1]:
            item["default"] = prop.default
        if prop.description is not None:
            item["description"] = prop.description
        result[prop.name] = item
    return result

def _class_glm(oclass:Class) -> str:
    """GLM `class` block of a runtime class, or of the extended properties of
    a module class (empty when a module class has none)"""
    props = [prop for prop in oclass.properties() if oclass.module is None or prop.is_extended]
    if oclass.module is not None and not props:
        return ""
    head = f"class {oclass.name}"
    if oclass.module is None and oclass.parent is not None:
        head += f" : {oclass.inherit or 'public'} {oclass.parent.name}"
    lines = [head + " {\n"]
    for prop in props:
        if prop.keywords:
            keys = ", ".join(f"{key}={value}" for key, value in prop.keywords.items())
            lines.append(f"\t{prop.ptype} {{{keys}}} {prop.name};\n")
        elif prop.unit is not None:
            lines.append(f"\t{prop.ptype} {prop.name}[{prop.unit}];\n")
        else:
            lines.append(f"\t{prop.ptype} {prop.name};\n")
    for event, script in oclass.events.items():
        lines.append(f"\ton_{event} {_quote(script)};\n")
    lines.append("}\n")
    return "".join(lines)

def _filter_text(name:str, spec:dict) -> str:
    """GLM text of a filter from gridlabd JSON (as `converters/json2glm.py` writes it)"""
    domain = spec["domain"]
    options = "".join(f",{key}={spec[key]}" for key in ("minimum", "maximum", "resolution") if key in spec)
    def poly(coefs):
        terms = []
        for n, coef in enumerate(coefs):
            if n == 0:
                terms.append(f"{coef:g}")
            elif n == 1:
                terms.append(f"{coef:+g}{domain}")
            else:
                terms.append(f"{coef:+g}{domain}^{n}")
        return "".join(terms)
    return f"{name}({domain},{spec['timestep']},{spec['timeskew']}{options}) = ({poly(spec['numerator'])}) / ({poly(spec['denominator'])})"
