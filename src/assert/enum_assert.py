# pylint: disable=line-too-long,consider-using-f-string
# (the markdown tables in the docstring are kept one row per line, and
# messages use C printf formats, as gridlabd writes them)
"""Enumeration assert objects (class `enum_assert`)

An `enum_assert` object checks at each time step that an `enumeration`
property of its parent has (or does not have) a value, given as the
keyword's integer, and stops the simulation when it does not.

Syntax
------

    module assert;
    object enum_assert {
        parent "<object-name>";
        status "ASSERT_TRUE";         // ASSERT_TRUE, ASSERT_FALSE, ASSERT_NONE
        value <integer>;
        target "<property-name>";
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `status` | `enumeration {ASSERT_NONE=3, ASSERT_FALSE=2, ASSERT_TRUE=1}` | `ASSERT_TRUE` | Conditions for the assert checks |
| `value` | `int32` | `0` | Value to assert |
| `target` | `char1024` | | Property to perform the assert upon |

Description
-----------

Each `enum_assert` object is expected to satisfy:

1. The target is the parent's `target` property (a global variable when
   the object has no parent). A target that is not found or is not an
   `enumeration` fails with `Specified target TARGET for PARENT is not
   valid.`
2. With `ASSERT_TRUE`, a target value other than `value` fails with
   `Assert failed on PARENT: TARGET=x did not match VALUE`; with
   `ASSERT_FALSE`, a target value equal to `value` fails with `... did
   match ...`. A failure returns 0, which stops the run with
   `arras.exitcodes.RUNERR`.
3. Passed tests and tests that are not run write verbose messages without
   the object name (gridlabd's `gl_verbose()`).

Examples
--------

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
    ... module assert;
    ... class climate { enumeration {NONE=0, LINEAR=1, QUADRATIC=2} interpolate; }
    ... object climate {
    ...     interpolate NONE;
    ...     object enum_assert { target "interpolate"; value 1; };
    ... }
    ... ''')
    >>> r = Runner(model=m)
    >>> print(r.stderr[0])
    ERROR [2020-01-01 00:00:00 UTC]: Assert failed on climate:0: interpolate=0 did not match 1
    >>> Class.reset()

Caveats
-------

- The deltamode update function (`update_enum_assert()`) is not modeled.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The failure message prints the two integers with `%g` as numbers;
   gridlabd passes integers to `%g`, whose output is undefined.
2. An object without a parent tests the global variable named `target`
   and names it `global` in messages; gridlabd dereferences the missing
   parent.

References
----------

- `arras-energy/gridlabd`: `module/assert/enum_assert.cpp`, `enum_assert.h`
- [Enum_assert class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Assert/Enum_assert.md)
  (`docs/Module/Assert/Enum_assert.md`)
"""

from typing import Any

from ._base import AssertClass
from ._common import TS_NEVER, runner
from ._compare import _int32
from .double_assert import STATUS, ASSERT_TRUE, ASSERT_FALSE

class EnumAssert(AssertClass):
    """Class `enum_assert`; see the module documentation"""

    NAME = "enum_assert"

    PROPERTIES = (
        ("status", "enumeration", {"default": "ASSERT_TRUE", "description": "Conditions for the assert checks", "keywords": STATUS}),
        ("value", "int32", {"description": "Value to assert"}),
        ("target", "char1024", {"description": "Property to perform the assert upon"}),
    )

    @classmethod
    def init(cls, model:Any, name:str) -> bool:
        return True

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int:
        found = cls.find_target(model, name, ("enumeration",))
        if found is None:
            return 0
        pname, target, prop = found
        x = _int32(prop.enumeration())
        text = model.get_property(name, "value")
        value = int(str(text), 0) if text not in (None, "") else 0
        status = cls.keyword(model, name, "status")
        if status == ASSERT_TRUE:
            if value != x:
                runner().error("Assert failed on %s: %s=%g did not match %g" % (pname, target, x, value))
                return 0
            runner().verbose(f"Assert passed on {pname}")
            return TS_NEVER
        if status == ASSERT_FALSE:
            if value == x:
                runner().error("Assert failed on %s: %s=%g did match %g" % (pname, target, x, value))
                return 0
            runner().verbose(f"Assert passed on {pname}")
            return TS_NEVER
        runner().verbose(f"Assert test is not being run on {pname}")
        return TS_NEVER
