# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""General purpose assert objects (class `assert`)

An `assert` object compares a property of its parent (or of each object of
a group, or a global variable when it has neither) with a value or a pair
of values at each time step, and stops the simulation when the comparison
does not have the outcome given by `status`.

Syntax
------

    module assert;
    object assert {
        parent "<object-name>";
        status "TRUE";                // TRUE, FALSE, NONE (or INIT), ERROR
        target "<property-name>";
        part "<optional-part-name>";
        relation "==";                // ==, <, <=, >, >=, !=, inside, outside
        value "<unary-comparison-value>";
        within "<comparison-limit-value>";
        lower "<lower-binary-comparison-value>";
        upper "<upper-binary-comparison-value>";
        group "<optional-group-specification>";
        start "INIT";
        stop "NEVER";
        hold "0 s";
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `status` | `enumeration {ERROR=3, FALSE=2, TRUE=1, INIT=0, NONE=0}` | `TRUE` | desired outcome of assert test |
| `target` | `char1024` (required) | | the target property to test |
| `part` | `char32` | | the target property part to test |
| `relation` | `enumeration {outside=7, inside=6, !==3, >==2, >=5, <==1, <=4, ===0}` (required) | `==` | the relation to use for the test |
| `value` | `char1024` (required) | | the value to compare with for binary tests |
| `within` | `char1024` | `0` | the bounds within which the value must bed compared |
| `lower` | `char1024` | | the lower bound to compare with for interval tests (same value as `value`) |
| `upper` | `char1024` | `0` | the upper bound to compare with for interval tests (same value as `within`) |
| `group` | `char1024` | | a target group specification to use instead of parent object |
| `start` | `timestamp` | `INIT` | time to start assertion |
| `stop` | `timestamp` | `NEVER` | time to stop assertion |
| `hold` | `double` [s] | `0` | a duration over which the assertion must be violated before failing |

Description
-----------

Given a model that loads the module (`module assert;`), each `assert`
object is expected to satisfy:

1. At initialization, the targets are found: the `target` property of each
   object that `group` selects (see Group specifications), else of the
   parent, else the global variable named `target`. A target that does not
   exist, or a `group` that is not valid, fails the initialization with
   `init_assert(obj=ID;NAME): NAME: ...`; a group that selects no object
   gives a warning.
2. At each committed time `t`: when `status` is `NONE` (or `INIT`) the test
   is not run; when `t` is before `start`, `start` is returned (the core
   does not use commit times, so no event is added at `start`); when `t`
   is after `stop`, the test is not run.
3. Without `part`, the value text and `within` text are converted to the
   target's type and compared as the core compares properties
   (`property_compare_basic_str()`): real numbers (`double`; the first
   member of an `enduse`, `randomvar`, or `loadshape`) use `within` as the
   tolerance of `==` and `!=` (`|x-value| <= within`) and as the upper
   bound of `inside` and `outside`; a `complex` supports only `==` and
   `!=`, with `|x-value| <= |within|` (both parts compared; exact equality
   when `within` is empty); integers, enumerations, sets, and timestamps
   compare their full values as signed integers; strings compare bytes
   (`strcmp()`), with the value cut to the size of the `charN` type;
   `bool` and `object` support only `==` and `!=`. `inside` is inclusive
   and `outside` is its negation. A value that cannot be converted
   (including the name of an object that does not exist), or a relation
   the type does not support, makes the comparison false with a warning.
4. With `part`, `value` and `within` are read as numbers (`atof()`) and
   compared with the part of the target (see Parts) as real numbers.
5. The outcome is `TRUE` when the comparison holds, else `FALSE`. When it
   differs from `status` (always, for `ERROR`) for some target, the object
   fails, unless `hold` is positive and the outcome has differed at every
   commit since the first commit at which it differed for less than
   `hold` seconds (strictly). A failure writes
   `NAME: assert failed on [NOT ]'OBJECT.TARGET.PART' 'X' 'RELATION'
   'VALUE' 'WITHIN'`, where `X` is the target value (real and complex
   numbers written with the `double_format` and `complex_format` globals
   and the unit), and returns `TS_INVALID`, which stops the run with
   `arras.exitcodes.RUNERR`.

Parts
-----

| Type | Parts |
| ---- | ----- |
| `complex` | `real`, `imag`, `mag`, `arg` (radians), `ang` (degrees) |
| `timestamp` | `seconds`, `minutes`, `hours`, `days` since 1970; `second`, `minute`, `hour`, `day`, `month`, `year`, `weekday` (0 is Sunday), `yearday` (from 0), `isdst`, `nanosecond`, `tzoffset` (seconds west of UTC) in the `timezone_locale` time zone |
| `object` | `id`, `rng_state`, `latitude`, `longitude`, `schedule_skew`, and `clock.P`, `valid_to.P`, `in_svc.P`, `out_svc.P`, `heartbeat.P` for each timestamp part `P` of the object referred to |
| `enduse` | `breaker_amps`, `impedance_fraction`, `current_fraction`, `power_fraction`, `power_factor`, `voltage_factor`, `heatgain`, `heatgain_fraction`, the `motorX.*` and `electronicX.*` reals, and `.real`, `.imag`, `.mag`, `.arg`, `.ang` of `total`, `energy`, `demand`, `admittance`, `current`, `power` |
| `randomvar` | `a`, `b`, `low`, `high` |

A part not defined for the type makes the comparison false with the error
`part P is not defined for type T`; a type without parts gives a warning.

Group specifications
--------------------

`group` selects objects by header values with terms `NAME OP VALUE`
separated by `;`, `AND`, or `and`. `NAME` is `class`, `isa`, `groupid`,
`module`, `id`, `name`, `parent`, or `rank`, and `OP` is `=`, `!=`, `<`,
`>`, `<=`, or `>=`. For example, `group "class=test";` selects every
object of class `test`.

Messages
--------

Errors and warnings are prefixed with the object name, as gridlabd's
`gld_object::error()` and `warning()` do. Objects with the `QUIET` flag
write no errors, objects with the `WARNING` flag write no warnings, and
objects with the `VERBOSE` flag write verbose messages (when the `verbose`
global is set) for passed tests, holds, and tests that are not run. The
flags come from the object's `flags` header and the `assert::message_flags`
global (see `assert`).

Examples
--------

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-01-01 00:00:00 UTC"; stoptime "2020-01-01 00:00:00 UTC"; }
    ... module assert;
    ... class test { double x[MW]; }
    ... object test {
    ...     x 50 MW;
    ...     object assert { target "x"; relation "=="; value "50000 kW"; };
    ...     object assert { target "x"; relation "inside"; lower 49; upper 51; };
    ...     object assert { target "x"; relation ">"; value 51; status FALSE; };
    ... }
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> m.set_property("assert:3", "status", "TRUE")
    >>> r = Runner(model=m)
    >>> r.returncode
    5
    >>> print(r.stderr[0])
    ERROR [2020-01-01 00:00:00 UTC]: assert:3: assert failed on 'test:0.x.' '+50 MW' '>' '51' '0'
    >>> Class.reset()

Caveats
-------

- `value` and `lower` share one value in gridlabd, as do `within` and
  `upper`. In `arras` they are separate properties; the one set last in
  the object is used. Model output lists both, and `Model.check()` reports
  `value` as a required property that is not set when only `lower` is set.
- `randomvar` and `loadshape` values are not updated by `arras` (see
  `arras.module`); their value is a number that the model holds (set by an
  event handler, for example), else 0.
- An object `on_init` or `on_commit` handler replaces the class's, so the
  assert test is not run for that object.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16, with the assert fixes)
----------------------------------------------------------------------------------

The core and module fixes that `arras` matches are listed in DESIGN.md
decision 8.4 (integer, enumeration, and complex comparisons, conversion
errors, `object` parts, real `complex` values with a unit, and messages
without a repeated object name). Remaining differences:

1. `group` supports only the header terms listed above; gridlabd's find
   language also has `~` and `!~` matches, `latitude`, `longitude`,
   `clock`, `insvc`, and `outsvc` terms, and object property terms.
2. The message flags are read when the object is initialized; gridlabd
   applies `assert::message_flags` when the object is created.

References
----------

- `arras-energy/gridlabd`: `module/assert/assert.cpp`, `assert.h`,
  `source/property.cpp` (`property_compare_basic()`,
  `property_compare_basic_str()`, `complex_get_part()`),
  `source/compare.cpp`, `source/convert.cpp`, `source/timestamp.cpp`
  (`timestamp_get_part()`), `source/object.cpp` (`object_get_part()`),
  `source/enduse.cpp`, `source/random.cpp`, `source/find.cpp`
- [Assert class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Assert/Assert.md)
  (`docs/Module/Assert/Assert.md`)
"""

from typing import Any

from ._base import AssertClass
from ._common import AssertError, Target, TS_NEVER, TS_INVALID, to_double, to_timestamp, \
    object_error, object_warning, object_verbose, get_state, set_state, runner
from ._compare import RELATIONS, compare_with_string, compare_part
from ._find import find

AS_NONE, AS_TRUE, AS_FALSE, AS_ERROR = 0, 1, 2, 3
"""Values of `status` (gridlabd `g_assert::ASSERTSTATUS`)"""

class _State: # pylint: disable=too-few-public-methods
    """Targets and hold start time of an assert object"""

    def __init__(self, targets:list[Target]):
        self.targets = targets
        self.started = TS_NEVER

class Assert(AssertClass):
    """Class `assert` (gridlabd `g_assert`); see the module documentation"""

    NAME = "assert"

    PROPERTIES = (
        ("status", "enumeration", {"default": "TRUE", "description": "desired outcome of assert test",
            "keywords": {"ERROR": AS_ERROR, "FALSE": AS_FALSE, "TRUE": AS_TRUE, "INIT": AS_NONE, "NONE": AS_NONE}}),
        ("target", "char1024", {"flags": "REQUIRED", "description": "the target property to test"}),
        ("part", "char32", {"description": "the target property part to test"}),
        ("relation", "enumeration", {"flags": "REQUIRED", "description": "the relation to use for the test",
            "keywords": dict(reversed(RELATIONS.items()))}),
        ("value", "char1024", {"flags": "REQUIRED", "description": "the value to compare with for binary tests"}),
        ("within", "char1024", {"default": "0", "description": "the bounds within which the value must bed compared"}),
        ("lower", "char1024", {"description": "the lower bound to compare with for interval tests"}),
        ("upper", "char1024", {"default": "0", "description": "the upper bound to compare with for interval tests"}),
        ("group", "char1024", {"description": "a target group specification to use instead of parent object"}),
        ("start", "timestamp", {"default": "INIT", "description": "time to start assertion"}),
        ("stop", "timestamp", {"default": "NEVER", "description": "time to stop assertion"}),
        ("hold", "double", {"unit": "s", "description": "a duration over which the assertion must be violated before failing"}),
    )

    @classmethod
    def init(cls, model:Any, name:str) -> bool:
        flags = cls.flags(model, name)
        group = cls.get(model, name, "group")
        target = cls.get(model, name, "target")
        object_verbose(name, flags, f"group = '{group}'")
        targets = []
        if group == "":
            parent = cls.parent(model, name)
            prop = Target(model, parent, target)
            if not prop.is_valid:
                return cls.init_failed(model, name, f"{name}: target '{parent or 'global'}' property '{target}' does not exist")
            targets.append(prop)
        else:
            try:
                names = find(model, group)
            except AssertError as err:
                runner().error(str(err))
                return cls.init_failed(model, name, f"{name}: group '{group}' is not valid")
            for item in names:
                prop = Target(model, item, target)
                if not prop.is_valid:
                    return cls.init_failed(model, name, f"{name}: group target '{item}' property '{target}' does not exist")
                targets.append(prop)
            if not targets:
                object_warning(name, flags, f"group '{group}' contains no objects")
        set_state(model, name, _State(targets))
        return True

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=too-many-locals
        flags = cls.flags(model, name)
        status = cls.keyword(model, name, "status")
        start = to_timestamp(model, cls.get(model, name, "start") or "INIT")
        stop = to_timestamp(model, cls.get(model, name, "stop") or "NEVER")
        if status == AS_NONE:
            object_verbose(name, flags, "assert test is not being run")
            return TS_NEVER
        if t < start:
            return start
        if t > stop:
            return TS_NEVER
        state = get_state(model, name)
        hold_text = cls.get(model, name, "hold")
        hold = to_double(hold_text, "s", f"{name}.hold") if hold_text else 0.0
        start_count = 0
        for target in state.targets:
            if cls._evaluate(model, name, target) != status:
                if hold == 0 or t > float(state.started) + hold:
                    relation = cls.keyword(model, name, "relation")
                    keyword = next(k for k, v in model.objects[name].oclass.find_property("relation").keywords.items() if v == relation)
                    value = cls.get_alias(model, name, ("value", "lower"))
                    value2 = cls.get_alias(model, name, ("within", "upper"))
                    object_error(name, flags, f"assert failed on {'' if status == AS_TRUE else 'NOT '}"
                        f"'{target.owner}.{target.prop}.{cls.get(model, name, 'part')}' '{target.to_string()}' "
                        f"'{keyword}' '{value}' '{value2}'")
                    return TS_INVALID
                start_count += 1
                if state.started == TS_NEVER:
                    state.started = t
                    object_verbose(name, flags, f"assert {target.owner} started at {t} with hold for {hold:g} s")
            else:
                object_verbose(name, flags, f"assert passed on {target.owner}")
        if start_count == 0:
            state.started = TS_NEVER
        return TS_NEVER

    @classmethod
    def _evaluate(cls, model:Any, name:str, target:Target) -> int:
        """Outcome of the test on one target (gridlabd `evaluate_status()`)"""
        a = cls.get_alias(model, name, ("value", "lower"))
        b = cls.get_alias(model, name, ("within", "upper"))
        part = cls.get(model, name, "part")
        relation = cls.keyword(model, name, "relation")
        if part == "":
            result = compare_with_string(target, relation, a, b if b != "" else None)
        else:
            result = compare_part(target, relation, a, b if b != "" else None, part)
        return AS_TRUE if result else AS_FALSE
