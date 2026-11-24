# pylint: disable=line-too-long,consider-using-f-string
# (the markdown tables in the docstring are kept one row per line, and
# messages use C printf formats, as gridlabd writes them)
"""Complex number assert objects (class `complex_assert`)

A `complex_assert` object checks at each time step that a `complex`
property of its parent (or its real part, imaginary part, magnitude, or
angle) is (or is not) within a tolerance of a value, and stops the
simulation when it is not.

Syntax
------

    module assert;
    object complex_assert {
        parent "<object-name>";
        status "ASSERT_TRUE";         // ASSERT_TRUE, ASSERT_FALSE, ASSERT_NONE
        once "ONCE_FALSE";            // ONCE_FALSE, ONCE_TRUE, ONCE_DONE
        operation "FULL";             // FULL, REAL, IMAGINARY, MAGNITUDE, ANGLE
        value <complex>;
        within <decimal>;
        target "<property-name>";
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `status` | `enumeration {ASSERT_NONE=3, ASSERT_FALSE=2, ASSERT_TRUE=1}` | `ASSERT_TRUE` | Conditions for the assert checks |
| `once` | `enumeration {ONCE_DONE=2, ONCE_TRUE=1, ONCE_FALSE=0}` | `ONCE_FALSE` | Conditions for a single assert check |
| `operation` | `enumeration {ANGLE=4, MAGNITUDE=3, IMAGINARY=2, REAL=1, FULL=0}` | `FULL` | Complex operation for the comparison |
| `value` | `complex` | `0+0i` | Value to assert |
| `within` | `double` | `0` | Tolerance for a successful assert |
| `target` | `char1024` | | Property to perform the assert upon |

Description
-----------

Each `complex_assert` object is expected to satisfy:

1. A `within` of zero or less fails the initialization with
   `init_complex_assert(obj=ID;NAME): A non-positive value has been
   specified for within.`
2. The `once` logic is that of `double_assert`, with both parts of `value`
   compared.
3. The target is the parent's `target` property (a global variable when
   the object has no parent). A target that is not found or is not a
   `complex` fails with `Specified target TARGET for PARENT is not valid.`
4. `FULL` tests the real part, then the imaginary part; `REAL` and
   `IMAGINARY` test one part; `MAGNITUDE` tests the difference of the
   magnitudes; `ANGLE` tests the difference of the angles in radians
   (without wrapping). With `ASSERT_TRUE` a difference greater than
   `within` (or NaN) fails; with `ASSERT_FALSE` a difference less than
   `within` (or NaN) fails. The messages are those of
   `complex_assert.cpp`, for example `Assert failed on PARENT: real part of
   TARGET x not within WITHIN of given value VALUE`. A failure returns 0,
   which stops the run with `arras.exitcodes.RUNERR`.
5. Passed tests and tests that are not run write verbose messages without
   the object name (gridlabd's `gl_verbose()`).

Examples
--------

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
    ... module assert;
    ... class meter { complex voltage_A[V]; }
    ... object meter {
    ...     voltage_A 110.0;
    ...     object complex_assert { target "voltage_A"; value 110+10d; operation ANGLE; within 0.01; };
    ... }
    ... ''')
    >>> r = Runner(model=m)
    >>> print(r.stderr[0])
    ERROR [2020-01-01 00:00:00 UTC]: Assert failed on meter:0: Angle of voltage_A (0) not within 0.010000 of given value 0.174533
    >>> Class.reset()

Caveats
-------

- See the `once` caveat of `double_assert`. The deltamode update function
  (`update_complex_assert()`) is not modeled.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16, with the assert fixes)
----------------------------------------------------------------------------------

None. An object without a parent tests the global variable named
`target` and names it `global` in messages, as gridlabd does with the
assert fixes.

References
----------

- `arras-energy/gridlabd`: `module/assert/complex_assert.cpp`,
  `complex_assert.h`
- [Complex_assert class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Assert/Complex_assert.md)
  (`docs/Module/Assert/Complex_assert.md`)
"""

import math
from typing import Any

from ._base import AssertClass
from ._common import TS_NEVER, to_complex, to_double, angle, runner
from .double_assert import STATUS, ONCE, ASSERT_TRUE, ASSERT_FALSE, once_check

FULL, REAL, IMAGINARY, MAGNITUDE, ANGLE = range(5)
"""Values of `operation`"""

OPERATION = {"ANGLE": ANGLE, "MAGNITUDE": MAGNITUDE, "IMAGINARY": IMAGINARY, "REAL": REAL, "FULL": FULL}
"""Keywords of `operation`, as gridlabd lists them"""

def _bad(error:float, within:float, true:bool) -> bool:
    if math.isnan(error):
        return True
    return abs(error) > within if true else abs(error) < within

class ComplexAssert(AssertClass):
    """Class `complex_assert`; see the module documentation"""

    NAME = "complex_assert"

    PROPERTIES = (
        ("status", "enumeration", {"default": "ASSERT_TRUE", "description": "Conditions for the assert checks", "keywords": STATUS}),
        ("once", "enumeration", {"description": "Conditions for a single assert check", "keywords": ONCE}),
        ("operation", "enumeration", {"description": "Complex operation for the comparison", "keywords": OPERATION}),
        ("value", "complex", {"description": "Value to assert"}),
        ("within", "double", {"description": "Tolerance for a successful assert"}),
        ("target", "char1024", {"description": "Property to perform the assert upon"}),
    )

    @staticmethod
    def _within(model:Any, name:str) -> float:
        text = model.get_property(name, "within")
        return to_double(str(text)) if text not in (None, "") else 0.0

    @classmethod
    def init(cls, model:Any, name:str) -> bool:
        if cls._within(model, name) <= 0.0:
            return cls.init_failed(model, name, "A non-positive value has been specified for within.")
        return True

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=too-many-return-statements,too-many-locals
        value = to_complex(cls.get(model, name, "value"), None, f"{name}.value")
        within = cls._within(model, name)
        if not once_check(cls, model, name, value, runner().verbose):
            return TS_NEVER
        found = cls.find_target(model, name, ("complex",))
        if found is None:
            return 0
        pname, target, prop = found
        x = prop.complex()
        status = cls.keyword(model, name, "status")
        operation = cls.keyword(model, name, "operation")
        if status not in (ASSERT_TRUE, ASSERT_FALSE):
            runner().verbose(f"Assert test is not being run on {pname}")
            return TS_NEVER
        true = status == ASSERT_TRUE
        word = "not within" if true else "is within"
        if operation in (FULL, REAL, IMAGINARY):
            error = x - value
            if _bad(error.real, within, true) and operation in (FULL, REAL):
                runner().error("Assert failed on %s: real part of %s %g %s %f of given value %g" % (pname, target, x.real, word, within, value.real))
                return 0
            if _bad(error.imag, within, true) and operation in (FULL, IMAGINARY):
                runner().error("Assert failed on %s: imaginary part of %s %+gi %s %f of given value %+gi" % (pname, target, x.imag, word, within, value.imag))
                return 0
        elif operation == MAGNITUDE:
            if _bad(abs(x) - abs(value), within, true):
                fmt = "Assert failed on %s: Magnitude of %s (%g) not within %f of given value %g" if true \
                    else "Assert failed on %s: Magnitude of %s %g is within %f of given value %g"
                runner().error(fmt % (pname, target, abs(x), within, abs(value)))
                return 0
        elif operation == ANGLE:
            if _bad(angle(x) - angle(value), within, true):
                fmt = "Assert failed on %s: Angle of %s (%g) not within %f of given value %g" if true \
                    else "Assert failed on %s: Angle of %s %g is within %f of given value %g"
                runner().error(fmt % (pname, target, angle(x), within, angle(value)))
                return 0
        runner().verbose(f"Assert passed on {pname}")
        return TS_NEVER
