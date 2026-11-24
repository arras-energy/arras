# pylint: disable=line-too-long,consider-using-f-string
# (the markdown tables in the docstring are kept one row per line, and
# messages use C printf formats, as gridlabd writes them)
"""Real number assert objects (class `double_assert`)

A `double_assert` object checks at each time step that a `double` property
of its parent is (or is not) within a tolerance of a value, and stops the
simulation when it is not.

Syntax
------

    module assert;
    object double_assert {
        parent "<object-name>";
        status "ASSERT_TRUE";         // ASSERT_TRUE, ASSERT_FALSE, ASSERT_NONE
        once "ONCE_FALSE";            // ONCE_FALSE, ONCE_TRUE, ONCE_DONE
        within_mode "WITHIN_VALUE";   // WITHIN_VALUE, WITHIN_RATIO
        value <decimal>;
        within <decimal>;
        target "<property-name>";
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `status` | `enumeration {ASSERT_NONE=3, ASSERT_FALSE=2, ASSERT_TRUE=1}` | `ASSERT_TRUE` | Conditions for the assert checks |
| `once` | `enumeration {ONCE_DONE=2, ONCE_TRUE=1, ONCE_FALSE=0}` | `ONCE_FALSE` | Conditions for a single assert check |
| `within_mode` | `enumeration {WITHIN_RATIO=1, WITHIN_VALUE=0}` | `WITHIN_VALUE` | Method of applying tolerance |
| `value` | `double` | `0` | Value to assert |
| `within` | `double` | `0` | Tolerance for a successful assert |
| `target` | `char1024` | | Property to perform the assert upon |

Description
-----------

Each `double_assert` object is expected to satisfy:

1. A `within` of zero or less fails the initialization with
   `init_double_assert(obj=ID;NAME): A non-positive value has been
   specified for within.`
2. At each committed time, when `once` is `ONCE_TRUE` the value is
   remembered and `once` becomes `ONCE_DONE`; when `once` is `ONCE_DONE`
   the test is skipped while `value` is the value remembered, and runs
   (remembering the new value) when it has changed.
3. The target is the parent's `target` property (a global variable when
   the object has no parent). A target that is not found or is not a
   `double` fails with `Specified target TARGET for PARENT is not valid.`
4. The tolerance is `within` (`WITHIN_VALUE`), or `value*within` but no
   less than 0.001 (`WITHIN_RATIO`).
5. With `ASSERT_TRUE`, a target value `x` with `|x-value|` greater than the
   tolerance (or NaN) fails with `Assert failed on PARENT: TARGET x not
   within TOLERANCE of given value VALUE`. With `ASSERT_FALSE`, `|x-value|`
   less than the tolerance (or NaN) fails with `... is within ...`. With
   `ASSERT_NONE` the test is not run. A failure returns 0, which stops the
   run with `arras.exitcodes.RUNERR`.

Examples
--------

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
    ... module assert;
    ... class climate { double temperature[degF]; }
    ... object climate {
    ...     temperature 50;
    ...     object double_assert { target "temperature"; value 55; within 1; };
    ... }
    ... ''')
    >>> r = Runner(model=m)
    >>> r.returncode
    5
    >>> print(r.stderr[0])
    ERROR [2020-01-01 00:00:00 UTC]: Assert failed on climate:0: temperature 50 not within 1.000000 of given value 55
    >>> Class.reset()

Caveats
-------

- gridlabd also resets `once` from `ONCE_DONE` to `ONCE_TRUE` whenever
  `value` is set during a run (`postnotify()`); `arras` has no property
  notifications, so the test runs again only when `value` changes.
- The deltamode update function (`update_double_assert()`) is not modeled.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16, with the assert fixes)
----------------------------------------------------------------------------------

None. An object without a parent tests the global variable named
`target` and names it `global` in messages, as gridlabd does with the
assert fixes.

References
----------

- `arras-energy/gridlabd`: `module/assert/double_assert.cpp`,
  `double_assert.h`
- [Double_assert class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Assert/Double_assert.md)
  (`docs/Module/Assert/Double_assert.md`)
"""

import math
from typing import Any

from ._base import AssertClass
from ._common import TS_NEVER, to_double, object_verbose, get_state, set_state, runner

ASSERT_TRUE, ASSERT_FALSE, ASSERT_NONE = 1, 2, 3
"""Values of `status`"""

ONCE_FALSE, ONCE_TRUE, ONCE_DONE = 0, 1, 2
"""Values of `once`"""

IN_ABS, IN_RATIO = 0, 1
"""Values of `within_mode` (`WITHIN_VALUE`, `WITHIN_RATIO`)"""

STATUS = {"ASSERT_NONE": ASSERT_NONE, "ASSERT_FALSE": ASSERT_FALSE, "ASSERT_TRUE": ASSERT_TRUE}
"""Keywords of `status`, as gridlabd lists them"""

ONCE = {"ONCE_DONE": ONCE_DONE, "ONCE_TRUE": ONCE_TRUE, "ONCE_FALSE": ONCE_FALSE}
"""Keywords of `once`, as gridlabd lists them"""

WITHIN_MODE = {"WITHIN_RATIO": IN_RATIO, "WITHIN_VALUE": IN_ABS}
"""Keywords of `within_mode`, as gridlabd lists them"""

def once_check(cls:Any, model:Any, name:str, value:Any, verbose:Any) -> bool:
    """Apply the `once` logic; `False` when the test is skipped (and
    `verbose(message)` is called)"""
    once = cls.keyword(model, name, "once")
    if once == ONCE_TRUE:
        set_state(model, name, value)
        cls.set_keyword(model, name, "once", ONCE_DONE)
    elif once == ONCE_DONE:
        if get_state(model, name) == value:
            verbose("Assert skipped with ONCE logic")
            return False
        set_state(model, name, value)
    return True

class DoubleAssert(AssertClass):
    """Class `double_assert`; see the module documentation"""

    NAME = "double_assert"

    PROPERTIES = (
        ("status", "enumeration", {"default": "ASSERT_TRUE", "description": "Conditions for the assert checks", "keywords": STATUS}),
        ("once", "enumeration", {"description": "Conditions for a single assert check", "keywords": ONCE}),
        ("within_mode", "enumeration", {"description": "Method of applying tolerance", "keywords": WITHIN_MODE}),
        ("value", "double", {"description": "Value to assert"}),
        ("within", "double", {"description": "Tolerance for a successful assert"}),
        ("target", "char1024", {"description": "Property to perform the assert upon"}),
    )

    @classmethod
    def init(cls, model:Any, name:str) -> bool:
        if cls._double(model, name, "within") <= 0.0:
            return cls.init_failed(model, name, "A non-positive value has been specified for within.")
        return True

    @staticmethod
    def _double(model:Any, name:str, prop:str) -> float:
        text = model.get_property(name, prop)
        return to_double(str(text)) if text not in (None, "") else 0.0

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=too-many-locals,too-many-return-statements
        flags = cls.flags(model, name)
        value = cls._double(model, name, "value")
        within = cls._double(model, name, "within")
        if not once_check(cls, model, name, value, lambda text: object_verbose(name, flags, text)):
            return TS_NEVER
        found = cls.find_target(model, name, ("double",))
        if found is None:
            return 0
        pname, target, prop = found
        mode = cls.keyword(model, name, "within_mode")
        limit = 0.0
        if mode == IN_RATIO:
            limit = max(value * within, 0.001)
        elif mode == IN_ABS:
            limit = within
        x = prop.double()
        status = cls.keyword(model, name, "status")
        if status == ASSERT_TRUE:
            m = abs(x - value)
            if math.isnan(m) or m > limit:
                runner().error("Assert failed on %s: %s %g not within %f of given value %g" % (pname, target, x, limit, value))
                return 0
            object_verbose(name, flags, f"Assert passed on {pname}")
            return TS_NEVER
        if status == ASSERT_FALSE:
            m = abs(x - value)
            if math.isnan(m) or m < limit:
                runner().error("Assert failed on %s: %s %g is within %f of given value %g" % (pname, target, x, limit, value))
                return 0
            object_verbose(name, flags, f"Assert passed on {pname}")
            return TS_NEVER
        object_verbose(name, flags, f"Assert test is not being run on {pname}")
        return TS_NEVER
