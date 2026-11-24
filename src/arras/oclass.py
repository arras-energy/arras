# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Arras object classes

The `Class` class holds the definition of an Arras Energy (HiPAS GridLAB-D)
object class: its name, the module that implements it, its parent class,
its properties, functions, event handlers, and synchronization passes. It
models the class registry that `arras-energy/gridlabd` implements in
`source/class.cpp` and the `class { ... }` block that the GLM loader reads
in `source/load.cpp`.

Users can register classes, declare and publish properties, look up
properties through the inheritance chain, define keywords, functions and
event handlers, and write a class out as `gridlabd --modhelp` text, GLM, or
XML.

Syntax
------

    from arras.oclass import Class
    c = Class(name, [module], [passconfig])   # register a class
    c = Class.declare(name, [parent])         # GLM `class name [: public parent] {...}`
    c = Class.find(name)                      # look up a registered class

Arguments
---------
- `name`: class name (fewer than 64 characters)
- `module`: name of the module that implements the class, or `None` for a
  class declared in a GLM file (default `None`)
- `passconfig`: synchronization passes and class options, an `int` built
  from `PASSCONFIG` or a `|`-separated string of its keys (default `NOSYNC`)

Description
-----------

Given a name, `Class(name,module)` returns a class that is expected to
satisfy:

1. The class is added to the registry `Class.registry` with the next class
   id, as `class_register()` does. Registering a name that the same module
   (or GLM, when `module` is `None`) has already registered raises
   `ClassError`; the same name in a different module is allowed.
2. `add_property(name,ptype)` follows the loader's rules for a
   `<type> <name>[<unit>];` line in a `class` block: a property that the
   class or a parent already defines is checked (a different type raises
   `ClassError`) and returned; otherwise a new *extended* property is added.
   Units are allowed only for `double`, `complex`, and `randomvar`;
   keywords only for `enumeration` and `set`. No property can be added once
   an object of the class exists (`numobjs > 0`).
3. `publish(name,ptype)` follows `class_define_map()` for one property:
   the name may carry its unit as `name[unit]`; header property names
   (`RESERVED`) are refused; the property's default is the type default
   from gridlabd's `property_type[]` table.
4. `find_property(name)` searches the class, then its parents, as
   `class_find_property()` does, and returns `None` when no class in the
   chain defines the name.
5. `set_parent(parent)` follows `parent <name>;` for GLM classes (any
   registered class) and `PT_INHERIT` for module classes (a class of the
   same module, set once). A class cannot inherit from itself, directly or
   through its parents.
6. `modhelp()`, `to_glm()`, and `to_xml()` return the same text that
   `print_class_d()`, `class_saveall()`, and `class_saveall_xml()` write.

Property types
--------------

| Type | XSD type | Default |
| ---- | -------- | ------- |
| `double`, `real`, `float` | `decimal` | `0.0` |
| `complex` | `string` | `0+0i` |
| `enumeration`, `set`, `timestamp` | `string` | `0` |
| `int16`, `int32`, `int64` | `integer` | `0` |
| `char8`, `char32`, `char256`, `char1024`, `string`, `double_array`, `complex_array` | `string` | empty |
| `bool` | `string` | `FALSE` |
| `python` | `string` | `None` |
| `object`, `delegated`, `loadshape`, `enduse`, `randomvar`, `method` | `string` | none |

See `PROPERTY_TYPES` for the exact table.

Examples
--------

    >>> from arras.oclass import Class
    >>> Class.reset()
    >>> node = Class("node", module="powerflow", passconfig="PRETOPDOWN|BOTTOMUP|POSTTOPDOWN")
    >>> node.publish("voltage_A[V]", "complex", description="bus voltage, phase A")
    <Property node.voltage_A:complex[V]>
    >>> node.publish("bustype", "enumeration", keywords={"PQ":0, "PV":1, "SWING":2})
    <Property node.bustype:enumeration>
    >>> load = Class("load", module="powerflow")
    >>> load.set_parent("node")
    >>> load.find_property("voltage_A").oclass.name
    'node'
    >>> load.isa("node")
    True
    >>> test = Class.declare("test")
    >>> test.add_property("x", "double", unit="MW")
    <Property test.x:double[MW]>
    >>> test.add_property("x", "double") is test.find_property("x")
    True
    >>> test.add_property("x", "int32")
    Traceback (most recent call last):
    ...
    arras.oclass.ClassError: property x is defined in class test as type double
    >>> test.set_event("on_init", "python:mymodule.init")
    >>> print(load.modhelp().expandtabs(4), end="")
    class load {
        parent node;
        class node {
            complex voltage_A[V]; // bus voltage, phase A
            enumeration {PQ=0, PV=1, SWING=2} bustype;
        }
    <BLANKLINE>
    }
    <BLANKLINE>

Caveats
-------

- `Class` is an independent Python model of gridlabd's classes. It does
  not read from or write to a running `gridlabd` process, and it does not
  load module libraries, so the classes that gridlabd modules publish
  must be registered by the user.
- The registry is shared by all `Class` objects in the Python process, as
  gridlabd's class list is shared by a run. Call `Class.reset()` to start
  a new model.
- Units are recorded as given; they are not checked against gridlabd's
  `unitfile.txt`.
- Objects are not modeled. `numobjs` counts the objects created from the
  class; code that models objects is expected to increment it.
- Functions are Python callables; gridlabd function addresses, intrinsic
  functions (`intrinsic create(...)`), C++ code blocks, `notify` hooks, and
  property delegation are not modeled. Memory sizes and offsets are not
  modeled.
- Event handlers are stored as their script text; they are not run.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `set_parent()` raises `ClassError` when the new parent would create an
   inheritance loop. The core accepts the parent and reports the loop
   later, when `class_find_property()` walks the chain.
2. `define_keyword()` raises `ClassError` for properties that are not
   `enumeration` or `set`; the core attaches the keyword to any property.
3. A deprecated property is reported (log warning) once per property
   after the first `find_property()` while `suppress_repeat_messages` is
   true. The core sets every flag bit except `DEPRECATED_NONOTICE`
   (`prop->flags |= ~PF_DEPRECATED_NONOTICE`), which also suppresses the
   notice.
4. Header property names (`RESERVED`) are refused by `publish()` only,
   as in the core; `add_property()` accepts them, as the GLM loader does.

References
----------

- `arras-energy/gridlabd`: `source/class.cpp`, `source/class.h`,
  `source/property.cpp`, `source/property.h`, `source/load.cpp`
  (`class_block()`, `class_properties()`, `class_parent_definition()`,
  `class_event_handler()`), `source/cmdarg.cpp` (`print_class_d()`)
- [Class directive](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/GLM/Directive/Class.md)
  (`docs/GLM/Directive/Class.md`) and
  [modhelp](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Command/Modhelp.md)
  (`docs/Command/Modhelp.md`)
"""

import re
import logging
from typing import Any, Callable, Iterator

from arras.exceptions import ArrasException

_logger = logging.getLogger(__file__)

MAXNAMELEN = 64
"""Class and property names must be shorter than this (gridlabd
`MAXCLASSNAMELEN`, `MAXPROPNAMELEN`)"""

PASSCONFIG = {
    "NOSYNC": 0x0000,
    "PRETOPDOWN": 0x0001,
    "BOTTOMUP": 0x0002,
    "POSTTOPDOWN": 0x0004,
    "FORCE_NAME": 0x0020,
    "PARENT_OVERRIDE_OMIT": 0x0040,
    "UNSAFE_OVERRIDE_OMIT": 0x0080,
    "ABSTRACTONLY": 0x0100,
    "AUTOLOCK": 0x0200,
    "OBSERVER": 0x0400,
}
"""Synchronization pass and class option flags (gridlabd `PASSCONFIG`)"""

PROPERTY_TYPES = {
    "double": ("decimal", "0.0"),
    "complex": ("string", "0+0i"),
    "enumeration": ("string", "0"),
    "set": ("string", "0"),
    "int16": ("integer", "0"),
    "int32": ("integer", "0"),
    "int64": ("integer", "0"),
    "char8": ("string", ""),
    "char32": ("string", ""),
    "char256": ("string", ""),
    "char1024": ("string", ""),
    "object": ("string", None),
    "delegated": ("string", None),
    "bool": ("string", "FALSE"),
    "timestamp": ("string", "0"),
    "double_array": ("string", ""),
    "complex_array": ("string", ""),
    "real": ("decimal", "0.0"),
    "float": ("decimal", "0.0"),
    "loadshape": ("string", None),
    "enduse": ("string", None),
    "randomvar": ("string", None),
    "method": ("string", None),
    "string": ("string", ""),
    "python": ("string", "None"),
}
"""Property types as `name: (xsdname, default)`, in the order of gridlabd's
`property_type[]` table (`source/property.cpp`, without `void`)"""

UNIT_TYPES = ("double", "complex", "randomvar")
"""Property types that accept a unit in a GLM `class` block"""

KEYWORD_TYPES = ("enumeration", "set")
"""Property types that accept keywords"""

ACCESS = {
    "PUBLIC": 0x0f,
    "REFERENCE": 0x0d,
    "PROTECTED": 0x01,
    "PRIVATE": 0x0c,
    "HIDDEN": 0x1f,
}
"""Property access codes (gridlabd `PROPERTYACCESS`)"""

FLAGS = {
    "RECALC": 0x0001,
    "CHARSET": 0x0002,
    "EXTENDED": 0x0004,
    "REQUIRED": 0x0008,
    "OUTPUT": 0x0010,
    "DYNAMIC": 0x0020,
    "DEPRECATED_NONOTICE": 0x4000,
    "DEPRECATED": 0x8000,
}
"""Property flags (gridlabd `PF_*`)"""

EVENTS = ("init", "precommit", "presync", "sync", "postsync", "commit", "finalize")
"""Class event handlers, set in GLM as `on_<event> "<script>";`"""

RESERVED = ("parent", "rank", "clock", "valid_to", "latitude", "longitude",
    "in_svc", "out_svc", "name", "flags")
"""Object header property names that `publish()` refuses"""

GSO_NOINTERNALS = 0x0001
"""`glm_save_options` flag: omit module classes that have no extended
properties, and omit internal members"""

GSO_NOMACROS = 0x0002
"""`glm_save_options` flag: write class members without macros"""

class ClassError(ArrasException):
    """Object class error"""

def _flags(value:int|str|None, table:dict[str,int], what:str) -> int:
    """Convert an `int` or a `|`-separated string of keys to flag bits"""
    if value is None:
        return 0
    if isinstance(value,int):
        return value
    result = 0
    for key in (x.strip() for x in value.split("|")):
        if key:
            if key not in table:
                raise ClassError(f"'{key}' is not a valid {what}")
            result |= table[key]
    return result

class Property: # pylint: disable=too-many-instance-attributes
    """Class property

    Attributes
    ----------
    - `oclass`: class that defines the property
    - `name`: property name
    - `ptype`: property type (see `PROPERTY_TYPES`)
    - `unit`: unit name, or `None`
    - `keywords`: dict of keyword values for `enumeration` and `set` types,
      in the order gridlabd lists them
    - `access`: access name (see `ACCESS`)
    - `flags`: flag bits (see `FLAGS`)
    - `description`: description, or `None`
    - `default`: default value string, or `None`
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
            oclass:"Class",
            name:str,
            ptype:str,
            unit:str|None=None,
            keywords:dict[str,int]|None=None,
            access:str="PUBLIC",
            flags:int|str|None=0,
            description:str|None=None,
            default:str|None=None,
            ):
        """Create a property (use `Class.publish()` or `Class.add_property()`)"""
        if ptype not in PROPERTY_TYPES:
            raise ClassError(f"property type '{ptype}' is not recognized")
        if access not in ACCESS:
            raise ClassError(f"property access '{access}' is not valid")
        self.oclass = oclass
        """Class that defines the property"""
        self.name = name
        """Property name"""
        self.ptype = ptype
        """Property type"""
        self.unit = unit
        """Unit name"""
        self.keywords: dict[str,int] = dict(keywords) if keywords else {}
        """Keyword values for enumeration and set types"""
        self.access = access
        """Access name"""
        self.flags = _flags(flags, FLAGS, "property flag")
        """Flag bits"""
        self.description = description
        """Description"""
        self.default = default
        """Default value string"""
        if self.ptype == "set" and self.keywords and all(len(x) == 1 for x in self.keywords):
            self.flags |= FLAGS["CHARSET"]

    def __repr__(self) -> str:
        unit = f"[{self.unit}]" if self.unit else ""
        return f"<Property {self.oclass.name}.{self.name}:{self.ptype}{unit}>"

    def has_flag(self, name:str) -> bool:
        """Check whether a flag (see `FLAGS`) is set"""
        return bool(self.flags & FLAGS[name])

    @property
    def is_extended(self) -> bool:
        """`True` for a property added by a GLM `class` block"""
        return self.has_flag("EXTENDED")

    @property
    def is_hidden(self) -> bool:
        """`True` when the access hides the property from `modhelp`"""
        return ACCESS[self.access] & ACCESS["HIDDEN"] == ACCESS["HIDDEN"]

    def modhelp(self) -> str:
        """Declaration line as `gridlabd --modhelp` prints it, without tabs or
        newline"""
        if self.unit is not None:
            text = f"{self.ptype} {self.name}[{self.unit}];"
        elif self.ptype in KEYWORD_TYPES:
            keys = ", ".join(f"{key}={value & 0xffffffffffffffff}" for key, value in self.keywords.items())
            text = f"{self.ptype} {{{keys}}} {self.name};"
        else:
            text = f"{self.ptype} {self.name};"
        flags = ",".join(x for x in ("DEPRECATED","REQUIRED","OUTPUT","DYNAMIC") if self.has_flag(x))
        flags = f"({flags}) " if flags else ""
        if flags or self.description is not None:
            text += f" // {flags}{self.description or ''}"
        return text

class Class: # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Arras object class

    See the module documentation for the description and examples.

    Attributes
    ----------
    - `id`: class id (registration order, from 0)
    - `name`: class name
    - `module`: module name, or `None` for a GLM class
    - `passconfig`: pass and option bits (see `PASSCONFIG`)
    - `parent`: parent class, or `None`
    - `inherit`: GLM inheritance qualifier (`public`, `protected`,
      `private`), or `None`
    - `functions`: dict of class functions
    - `events`: dict of event handler scripts (see `EVENTS`)
    - `trl`: technology readiness level (0 to 9)
    - `numobjs`: number of objects created from the class
    """

    registry: list["Class"] = []
    """Registered classes, in registration order"""

    _count: int = 0

    def __init__(self, name:str, module:str|None=None, passconfig:int|str|None=0):
        """Register an object class (gridlabd `class_register()`)

        Arguments
        ---------
        - `name`: class name
        - `module`: module name, or `None` for a GLM class
        - `passconfig`: `PASSCONFIG` bits or a `|`-separated string of keys

        Exceptions
        ----------
        - `ClassError`: the name is too long or not valid, the same module
          already registered the name, or `passconfig` is not valid
        """
        if not isinstance(name,str) or not name or "." in name:
            raise ClassError(f"class name {name!r} is not valid")
        if len(name) >= MAXNAMELEN:
            raise ClassError(f"class name '{name}' is too long")
        for other in Class.registry:
            if other.name == name and other.module == module:
                raise ClassError(f"module {module} cannot register class {name}, it is already registered by module {module}")
        self.id = Class._count
        """Class id"""
        self.name = name
        """Class name"""
        self.module = module
        """Module name"""
        self.passconfig = _flags(passconfig, PASSCONFIG, "passconfig")
        """Pass and option bits"""
        self.parent: Class|None = None
        """Parent class"""
        self.inherit: str|None = None
        """GLM inheritance qualifier"""
        self.functions: dict[str,Callable] = {}
        """Class functions"""
        self.events: dict[str,str] = {}
        """Event handler scripts"""
        self.trl = 0
        """Technology readiness level"""
        self.numobjs = 0
        """Number of objects created from the class"""
        self._props: dict[str,Property] = {}
        Class._count += 1
        Class.registry.append(self)
        _logger.debug("class %s registered ok", name)

    def __repr__(self) -> str:
        return f"<Class {self.name}>"

    #
    # Registry
    #
    @classmethod
    def reset(cls) -> None:
        """Remove all registered classes and restart class ids at 0"""
        cls.registry.clear()
        cls._count = 0

    @classmethod
    def find(cls, name:str, module:str|None=None) -> "Class|None":
        """Find a registered class (gridlabd `class_get_class_from_classname()`)

        Arguments
        ---------
        - `name`: class name, or `module.class`
        - `module`: module name; when given, only classes of that module match

        Returns
        -------
        - `Class`: the first class registered with that name, or `None`
        """
        if module is None and "." in name:
            module, name = name.split(".",1)
            for oclass in cls.registry:
                if oclass.module == module and oclass.name == name:
                    return oclass
            return None
        for oclass in cls.registry:
            if oclass.name == name and (module is None or oclass.module == module):
                return oclass
        return None

    @classmethod
    def declare(cls, name:str, parent:"str|Class|None"=None, inherit:str="public") -> "Class":
        """Open a GLM `class name [: inherit parent] { ... }` block
        (gridlabd `class_block()`)

        Arguments
        ---------
        - `name`: class name
        - `parent`: parent class or its name, for a new class only
        - `inherit`: inheritance qualifier, `public`, `protected`, or `private`

        Returns
        -------
        - `Class`: the class already registered with that name, else a new
          GLM class

        Exceptions
        ----------
        - `ClassError`: the qualifier is not valid or the parent is not defined
        """
        if parent is not None:
            if inherit not in ("public","protected","private"):
                raise ClassError("missing inheritance qualifier")
            if not isinstance(parent,Class) and cls.find(parent) is None:
                raise ClassError(f"class {name} inherits from undefined class {parent}")
        oclass = cls.find(name)
        if oclass is None:
            oclass = cls(name)
            if parent is not None:
                oclass.parent = parent if isinstance(parent,Class) else cls.find(parent)
                oclass.inherit = inherit
        return oclass

    @classmethod
    def saveall(cls, options:int=0) -> str:
        """GLM text of all registered classes (gridlabd `class_saveall()`)

        Arguments
        ---------
        - `options`: `glm_save_options` bits (`GSO_NOINTERNALS`, `GSO_NOMACROS`)
        """
        text = "\n////////////////////////////////////////////////////////\n// classes\n"
        return text + "".join(oclass.to_glm(options) for oclass in cls.registry)

    @classmethod
    def saveall_xml(cls) -> str:
        """XML text of all registered classes (gridlabd `class_saveall_xml()`)"""
        return "\t<classes>\n" + "".join(oclass.to_xml() for oclass in cls.registry) + "\t</classes>\n"

    #
    # Inheritance
    #
    def set_parent(self, parent:"str|Class") -> None:
        """Set the parent class

        For a GLM class (`module` is `None`) this is the `parent <name>;`
        statement: any registered class can be the parent. For a module class
        this is `PT_INHERIT`: the parent must be a class of the same module,
        and the parent can be set only once; a warning is logged when the
        class omits a sync pass that the parent marks `UNSAFE_OVERRIDE_OMIT`.

        Exceptions
        ----------
        - `ClassError`: the parent is not found, is already set (module
          classes), or would create an inheritance loop
        """
        if isinstance(parent,Class):
            pclass = parent
        elif self.module is None:
            pclass = Class.find(parent)
        else:
            pclass = Class.find(parent, module=self.module)
        if pclass is None:
            if self.module is None:
                raise ClassError(f"parent class '{parent}' not found")
            raise ClassError(f"parent property class name '{parent}' is not defined")
        if self.module is not None:
            if self.parent is not None:
                raise ClassError(f"class already inherits properties from class {self.parent.name}")
            if pclass.module != self.module:
                raise ClassError(f"parent property class name '{pclass.name}' is not defined")
        check = pclass
        while check is not None:
            if check is self:
                raise ClassError(f"class '{self.name}' cannot inherit from '{pclass.name}' (inheritance loop)")
            check = check.parent
        self.parent = pclass
        if self.module is not None:
            self._check_override(pclass)

    def _check_override(self, pclass:"Class") -> None:
        no_override = pclass.passconfig & ~self.passconfig
        if pclass.passconfig & PASSCONFIG["UNSAFE_OVERRIDE_OMIT"] and not self.passconfig & PASSCONFIG["PARENT_OVERRIDE_OMIT"]:
            for key in ("PRETOPDOWN","BOTTOMUP","POSTTOPDOWN"):
                if no_override & PASSCONFIG[key]:
                    _logger.warning("class '%s' suppresses parent class '%s' %s sync behavior by omitting override", self.name, pclass.name, key)
            if no_override & PASSCONFIG["UNSAFE_OVERRIDE_OMIT"]:
                _logger.warning("class '%s' does not assert UNSAFE_OVERRIDE_OMIT when parent class '%s' does", self.name, pclass.name)

    def isa(self, name:str) -> bool:
        """Check whether the class is, or inherits from, the named class"""
        oclass = self
        while oclass is not None:
            if oclass.name == name:
                return True
            oclass = oclass.parent
        return False

    def has_pass(self, name:str) -> bool:
        """Check whether a `PASSCONFIG` flag is set"""
        return bool(self.passconfig & PASSCONFIG[name])

    #
    # Properties
    #
    def __contains__(self, name:str) -> bool:
        return self.find_property(name) is not None

    def __getitem__(self, name:str) -> Property:
        prop = self.find_property(name)
        if prop is None:
            raise KeyError(name)
        return prop

    def __iter__(self) -> Iterator[str]:
        return iter([prop.name for prop in self.properties(inherit=True)])

    def __len__(self) -> int:
        return len(self.properties(inherit=True))

    def properties(self, inherit:bool=False) -> list[Property]:
        """Properties of the class

        Arguments
        ---------
        - `inherit`: include the parents' properties, after the class's own,
          as gridlabd's `class_get_next_property_inherit()` lists them
        """
        result = list(self._props.values())
        if inherit and self.parent is not None:
            result += self.parent.properties(inherit=True)
        return result

    def find_property(self, name:str) -> Property|None:
        """Find a property in the class or its parents
        (gridlabd `class_find_property()`)

        Returns
        -------
        - `Property`: the property, or `None` if no class in the chain
          defines it
        """
        oclass = self
        while oclass is not None:
            prop = oclass._props.get(name) # pylint: disable=protected-access
            if prop is not None:
                if prop.has_flag("DEPRECATED") and not prop.has_flag("DEPRECATED_NONOTICE"):
                    _logger.warning("class '%s' property '%s' is deprecated", self.name, name)
                    prop.flags |= FLAGS["DEPRECATED_NONOTICE"]
                return prop
            oclass = oclass.parent
        return None

    def _new_property(self, name:str, ptype:str, **kwargs) -> Property:
        if self.numobjs > 0:
            raise ClassError(f"cannot add new properties to class '{self.name}' after class has been instantiated")
        if not isinstance(name,str) or not name:
            raise ClassError(f"property name {name!r} is not valid")
        if len(name) >= MAXNAMELEN:
            raise ClassError(f"property name '{name}' is too big")
        if name in self._props:
            raise ClassError(f"property '{name}' is already defined in class {self.name}")
        prop = Property(self, name, ptype, **kwargs)
        self._props[name] = prop
        return prop

    def add_property(self,
            name:str,
            ptype:str,
            unit:str|None=None,
            keywords:dict[str,int]|None=None,
            ) -> Property:
        """Declare a property as a GLM `class` block does
        (gridlabd `class_properties()` and `class_add_extended_property()`)

        Arguments
        ---------
        - `name`: property name, or `name[unit]` when `unit` is `None`
        - `ptype`: property type (see `PROPERTY_TYPES`)
        - `unit`: unit, for `UNIT_TYPES` only
        - `keywords`: keyword values, for `KEYWORD_TYPES` only

        Returns
        -------
        - `Property`: the property the class or a parent already defines with
          that name, else a new extended property

        Exceptions
        ----------
        - `ClassError`: the type is not recognized, differs from the existing
          property's type, does not accept a unit or keywords, or an object of
          the class already exists
        """
        name, unit = self._split_unit(name, unit)
        if ptype not in PROPERTY_TYPES:
            raise ClassError(f"property type {ptype} is not recognized")
        prop = self.find_property(name)
        if prop is not None:
            if prop.ptype != ptype:
                raise ClassError(f"property {name} is defined in class {self.name} as type {prop.ptype}")
            return prop
        if unit is not None and ptype not in UNIT_TYPES:
            raise ClassError(f"units not permitted for type {ptype}")
        if keywords and ptype not in KEYWORD_TYPES:
            raise ClassError(f"keys not permitted for type {ptype}")
        return self._new_property(name, ptype, unit=unit, keywords=keywords,
            flags=FLAGS["EXTENDED"])

    # pylint: disable=too-many-arguments
    def publish(self,
            name:str,
            ptype:str,
            *,
            unit:str|None=None,
            keywords:dict[str,int]|None=None,
            access:str="PUBLIC",
            flags:int|str|None=0,
            description:str|None=None,
            default:str|None=None,
            ) -> Property:
        """Publish a property as a module does (gridlabd `class_define_map()`)

        Arguments
        ---------
        - `name`: property name, or `name[unit]` when `unit` is `None`
        - `ptype`: property type (see `PROPERTY_TYPES`)
        - `unit`: unit (`PT_UNITS`)
        - `keywords`: keyword values for `KEYWORD_TYPES` (`PT_KEYWORD`), in
          the order gridlabd lists them
        - `access`: access name (`PT_ACCESS`, see `ACCESS`)
        - `flags`: flag bits or `|`-separated `FLAGS` keys (`PT_FLAGS`,
          `PT_REQUIRED`, `PT_OUTPUT`, `PT_DYNAMIC`, `PT_DEPRECATED`)
        - `description`: description (`PT_DESCRIPTION`)
        - `default`: default value (`PT_DEFAULT`); the type default from
          `PROPERTY_TYPES` when `None`

        Returns
        -------
        - `Property`: the new property

        Exceptions
        ----------
        - `ClassError`: the name is reserved, too long, or already defined in
          the class, the type or access is not valid, keywords are given for
          a type that does not accept them, or an object of the class
          already exists
        """
        name, unit = self._split_unit(name, unit)
        if name in RESERVED:
            raise ClassError(f"property name '{name}' conflicts with built-in property")
        if ptype not in PROPERTY_TYPES:
            raise ClassError(f"property type '{ptype}' is not recognized")
        if keywords and ptype not in KEYWORD_TYPES:
            raise ClassError(f"keys not permitted for type {ptype}")
        if default is None:
            default = PROPERTY_TYPES[ptype][1]
        return self._new_property(name, ptype, unit=unit, keywords=keywords,
            access=access, flags=flags, description=description, default=default)

    @staticmethod
    def _split_unit(name:str, unit:str|None) -> tuple[str,str|None]:
        if isinstance(name,str):
            match = re.fullmatch(r"([^\[\]]+)\[([^\[\]]+)\]",name)
            if match:
                if unit is not None and unit != match.group(2):
                    raise ClassError(f"property '{match.group(1)}' unit '{match.group(2)}' differs from unit '{unit}'")
                return match.group(1), match.group(2)
        return name, unit

    def define_keyword(self, name:str, key:str, value:int) -> None:
        """Define an enumeration or set keyword (gridlabd
        `class_define_enumeration_member()`, `class_define_set_member()`)

        The new keyword is listed first, as gridlabd prepends it. Keywords
        of a `set` longer than one character clear the `CHARSET` flag.

        Exceptions
        ----------
        - `ClassError`: the property is not found or is not an `enumeration`
          or `set`
        """
        prop = self.find_property(name)
        if prop is None:
            raise ClassError(f"property '{name}' is not found in class {self.name}")
        if prop.ptype not in KEYWORD_TYPES:
            raise ClassError(f"property '{name}' is not an enumeration or set")
        key = key[:31]
        if prop.ptype == "set":
            if not prop.keywords:
                prop.flags |= FLAGS["CHARSET"]
            if len(key) > 1:
                prop.flags &= ~FLAGS["CHARSET"]
        prop.keywords = {key: value, **{k:v for k,v in prop.keywords.items() if k != key}}

    def extended_count(self) -> int:
        """Number of extended properties (gridlabd `class_get_extendedcount()`)"""
        return sum(1 for prop in self._props.values() if prop.is_extended)

    #
    # Functions and events
    #
    def define_function(self, name:str, call:Callable) -> None:
        """Define a class function (gridlabd `class_define_function()`)

        Exceptions
        ----------
        - `ClassError`: the class already defines the function, or `call`
          is not callable
        """
        if name in self.functions:
            raise ClassError(f"class {self.name} function '{name}' has already been defined")
        if not callable(call):
            raise ClassError(f"class {self.name} function '{name}' is not callable")
        self.functions[name] = call

    def get_function(self, name:str) -> Callable|None:
        """Get a function that the class itself defines (gridlabd
        `class_get_function()`); parents are not searched"""
        return self.functions.get(name)

    def set_event(self, event:str, script:str) -> None:
        """Set an event handler, as GLM `on_<event> "<script>";` does

        Arguments
        ---------
        - `event`: `on_init`, `init`, etc. (see `EVENTS`)
        - `script`: handler script, e.g. `"python:module.function"`

        Exceptions
        ----------
        - `ClassError`: the event is not valid
        """
        name = event[3:] if event.startswith("on_") else event
        if name not in EVENTS:
            raise ClassError(f"event '{event}' is not valid")
        self.events[name] = script

    def get_event(self, event:str) -> str|None:
        """Get an event handler script, or `None`"""
        return self.events.get(event[3:] if event.startswith("on_") else event)

    #
    # Output
    #
    def modhelp(self, tabdepth:int=0) -> str:
        """Class structure as `gridlabd --modhelp` prints it (gridlabd
        `print_class_d()`)"""
        tabs = "\t" * tabdepth
        lines = [f"{tabs}class {self.name} {{\n"]
        if self.parent is not None:
            lines.append(f"{tabs}\tparent {self.parent.name};\n")
            lines.append(self.parent.modhelp(tabdepth+1))
        for name in self.functions:
            lines.append(f"{tabs}\tfunction {name}();\n")
        for prop in self._props.values():
            if not prop.is_hidden:
                lines.append(f"{tabs}\t{prop.modhelp()}\n")
        lines.append(f"{tabs}}}\n\n")
        return "".join(lines)

    def to_glm(self, options:int=0) -> str:
        """GLM text of the class (gridlabd `class_saveall()` for one class)

        Members are written only when `options` includes `GSO_NOMACROS`, as
        in gridlabd. With `GSO_NOINTERNALS`, a module class with no extended
        property is omitted, and only extended properties are written.
        """
        nointernals = options & GSO_NOINTERNALS
        if nointernals and self.module is not None and self.extended_count() == 0:
            return ""
        lines = [f"class {self.name} {{\n"]
        if options & GSO_NOMACROS:
            if not nointernals:
                if self.parent is not None:
                    lines.append(f"#ifdef INCLUDE_PARENT_CLASS\n\tparent {self.parent.name};\n#endif\n")
                for name in self.functions:
                    lines.append(f"#ifdef INCLUDE_FUNCTIONS\n\tfunction {name}();\n#endif\n")
            for prop in self._props.values():
                if not nointernals or prop.is_extended:
                    if "." in prop.name:
                        lines.append(f"#ifdef INCLUDE_DOTTED_PROPERTIES\n\t{prop.ptype} {prop.name};\n#endif\n")
                    else:
                        lines.append(f"\t{prop.ptype} {prop.name};\n")
        lines.append("}\n")
        return "".join(lines)

    def to_xml(self) -> str:
        """XML text of the class (gridlabd `class_saveall_xml()` for one class)"""
        lines = [f"\t\t<class name=\"{self.name}\">\n"]
        if self.parent is not None:
            lines.append(f"\t\t<parent>{self.parent.name}</parent>\n")
        for name in self.functions:
            lines.append(f"\t\t<function>{name}</function>\n")
        for prop in self._props.values():
            lines.append(f"\t\t\t<property type=\"{prop.ptype}\">{prop.name}</property>\n")
        lines.append("\t\t</class>\n")
        return "".join(lines)

    def to_dict(self) -> dict[str,Any]:
        """Class definition as a dict (for JSON output)"""
        return {
            "id": self.id,
            "name": self.name,
            "module": self.module,
            "parent": self.parent.name if self.parent else None,
            "passconfig": [key for key, bit in PASSCONFIG.items() if bit and self.passconfig & bit],
            "functions": list(self.functions),
            "events": dict(self.events),
            "properties": {prop.name: {
                "type": prop.ptype,
                "unit": prop.unit,
                "keywords": dict(prop.keywords),
                "access": prop.access,
                "flags": [key for key, bit in FLAGS.items() if prop.flags & bit],
                "description": prop.description,
                "default": prop.default,
                } for prop in self._props.values()},
        }
