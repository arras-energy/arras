# pylint: disable=line-too-long,consider-using-f-string,duplicate-code
# (the markdown tables in the docstring are kept one row per line, and
# messages use C printf formats, as gridlabd writes them)
"""Integer assert objects (class `int_assert`)

An `int_assert` object checks at each time step that an integer property
of its parent is (or is not) within a tolerance of a value, and stops the
simulation when it is not.

Syntax
------

    module assert;
    object int_assert {
        parent "<object-name>";
        status "ASSERT_TRUE";         // ASSERT_TRUE, ASSERT_FALSE, ASSERT_NONE
        once "ONCE_FALSE";            // ONCE_FALSE, ONCE_TRUE, ONCE_DONE
        within_mode "WITHIN_VALUE";   // WITHIN_VALUE, WITHIN_RATIO
        value <integer>;
        within <integer>;
        target "<property-name>";
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `status` | `enumeration {ASSERT_NONE=3, ASSERT_FALSE=2, ASSERT_TRUE=1}` | `ASSERT_TRUE` | |
| `once` | `enumeration {ONCE_DONE=2, ONCE_TRUE=1, ONCE_FALSE=0}` | `ONCE_FALSE` | |
| `within_mode` | `enumeration {WITHIN_RATIO=1, WITHIN_VALUE=0}` | `WITHIN_VALUE` | |
| `value` | `int32` | `0` | |
| `within` | `int32` | `0` | |
| `target` | `char1024` | | |

gridlabd publishes these properties without descriptions.

Description
-----------

Each `int_assert` object is expected to satisfy:

1. `value` and `within` are `int32` properties stored by gridlabd in
   64-bit members whose upper half stays zero, so the object uses their
   32 bits as unsigned numbers: a negative `value` or `within` is read as
   that number plus 2^32. As a result the initialization check for a
   negative `within` (`A negative value has been specified for within.`)
   never fails.
2. The `once` logic is that of `double_assert`.
3. The target is the parent's `target` property (a global variable when
   the object has no parent). A target that is not found or is not an
   `int16`, `int32`, or `int64` fails with `Specified target TARGET for
   PARENT is not valid.`
4. The tolerance is `within` (`WITHIN_VALUE`), or `value*within` but no
   less than 1 (`WITHIN_RATIO`), kept to its low 32 bits as a signed
   integer.
5. With `ASSERT_TRUE`, a target value `x` with `|x-value|` greater than the
   tolerance fails with `Assert failed on PARENT: TARGET x not within
   TOLERANCE of given value VALUE`; with `ASSERT_FALSE`, `|x-value|` less
   than the tolerance fails with `... is within ...`. A difference of more
   than 2^32-1 gives the warning `int_assert may be incorrect, difference
   range outside 32-bit abs() range`. The numbers in the message are the
   low 32 bits of each (gridlabd prints 64-bit values with `%i`). A failure
   returns 0, which stops the run with `arras.exitcodes.RUNERR`.

Examples
--------

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2000-01-01 00:00:00 UTC"; stoptime "2000-01-01 00:00:00 UTC"; }
    ... module assert;
    ... class house { int32 compressor_count; }
    ... object house {
    ...     compressor_count 4;
    ...     object int_assert { target "compressor_count"; value 4; within 1; };
    ... }
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> Class.reset()

Caveats
-------

- gridlabd reads `int16` and `int32` targets as 64-bit integers, which
  includes the bytes after the property; `arras` uses the property value.
- See the `once` caveat of `double_assert`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. An object without a parent tests the global variable named `target`
   and names it `global` in messages; gridlabd dereferences the missing
   parent.
2. The documentation gives `value` and `within` as `double`; the code
   publishes `int32`, which `arras` follows.

References
----------

- `arras-energy/gridlabd`: `module/assert/int_assert.cpp`, `int_assert.h`
- [Int_assert class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Assert/Int_assert.md)
  (`docs/Module/Assert/Int_assert.md`)
"""

from typing import Any

from ._base import AssertClass
from ._common import TS_NEVER, object_verbose, runner
from ._compare import _int32
from .double_assert import STATUS, ONCE, WITHIN_MODE, ASSERT_TRUE, ASSERT_FALSE, IN_ABS, IN_RATIO, once_check

class IntAssert(AssertClass):
    """Class `int_assert`; see the module documentation"""

    NAME = "int_assert"

    PROPERTIES = (
        ("status", "enumeration", {"default": "ASSERT_TRUE", "keywords": STATUS}),
        ("once", "enumeration", {"keywords": ONCE}),
        ("within_mode", "enumeration", {"keywords": WITHIN_MODE}),
        ("value", "int32", {}),
        ("within", "int32", {}),
        ("target", "char1024", {}),
    )

    @staticmethod
    def _member(model:Any, name:str, prop:str) -> int:
        """An `int32` property read from its zero-extended 64-bit member"""
        text = model.get_property(name, prop)
        value = int(str(text), 0) if text not in (None, "") else 0
        return value & 0xFFFFFFFF

    @classmethod
    def init(cls, model:Any, name:str) -> bool:
        if cls._member(model, name, "within") < 0: # never true, as in gridlabd
            return cls.init_failed(model, name, "A negative value has been specified for within.")
        return True

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=too-many-locals
        flags = cls.flags(model, name)
        value = cls._member(model, name, "value")
        within = cls._member(model, name, "within")
        if not once_check(cls, model, name, value, lambda text: object_verbose(name, flags, text)):
            return TS_NEVER
        found = cls.find_target(model, name, ("int16", "int32", "int64"))
        if found is None:
            return 0
        pname, target, prop = found
        mode = cls.keyword(model, name, "within_mode")
        limit = 0
        if mode == IN_RATIO:
            limit = max(_int32(value * within), 1)
        elif mode == IN_ABS:
            limit = _int32(within)
        x = prop.integer()
        status = cls.keyword(model, name, "status")
        if status in (ASSERT_TRUE, ASSERT_FALSE):
            diff = x - value
            if diff > 0xFFFFFFFF or diff < -0xFFFFFFFF:
                runner().warning("int_assert may be incorrect, difference range outside 32-bit abs() range")
            m = int(abs(float(diff)))
            if status == ASSERT_TRUE and m > limit:
                runner().error(f"Assert failed on {pname}: {target} {_int32(x)} not within {limit} of given value {_int32(value)}")
                return 0
            if status == ASSERT_FALSE and m < limit:
                runner().error(f"Assert failed on {pname}: {target} {_int32(x)} is within {limit} of given value {_int32(value)}")
                return 0
            object_verbose(name, flags, f"Assert passed on {pname}")
            return TS_NEVER
        object_verbose(name, flags, f"Assert test is not being run on {pname}")
        return TS_NEVER
