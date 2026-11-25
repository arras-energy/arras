# pylint: disable=line-too-long,too-many-arguments,too-many-positional-arguments
# (the markdown tables in the docstring are kept one row per line; the checks
# take the arguments of the C++ functions they port)
"""Violation recorders (class `violation_recorder`)

A `violation_recorder` checks the objects of a powerflow model for limit
violations at each sample and writes each violation to a CSV file, and a
summary of the counts when the run ends.

Syntax
------

    module tape;
    object violation_recorder {
        file "<file>";
        summary "<file>";
        virtual_substation "<link>";
        interval <seconds>;
        violation_flag "VIOLATION1|...";
        <limit> <decimal>;
    }

Properties
----------

| Property | Type | Description |
| -------- | ---- | ----------- |
| `file` | `char256` | output file name |
| `summary` | `char256` | summary output file name |
| `virtual_substation` | `char256` | name of the substation node to monitor for reverse flow violation |
| `interval` | `double[s]` | recording interval (0 'every iteration', -1 'on change') |
| `flush_interval` | `double[s]` | file flush interval (0 never, negative on samples) |
| `strict` | `bool` | stop the simulation on a problem with the files |
| `echo` | `bool` | causes the violation_recorder to echo messages to the screen |
| `limit` | `int32` | the maximum number of lines to write to the file |
| `violation_delay` | `int32` | the number of seconds to skip before recording violations |
| `xfrmr_thermal_limit_upper`, `..._lower` | `double` | transformer power limits (per unit of the rating) |
| `line_thermal_limit_upper`, `..._lower` | `double` | line current limits (per unit of the rating) |
| `node_instantaneous_voltage_limit_upper`, `..._lower` | `double` | node voltage limits (per unit) |
| `node_continuous_voltage_limit_upper`, `..._lower`, `node_continuous_voltage_interval` | `double` | continuous voltage limits (per unit) and interval (s) |
| `secondary_dist_voltage_rise_upper_limit`, `..._lower_limit` | `double` | voltage rise limits from transformer to meter (per unit) |
| `substation_breaker_A_limit`, `_B_`, `_C_` | `double` | breaker current limits (A) |
| `substation_pf_lower_limit` | `double` | substation power factor limit |
| `inverter_v_chng_per_interval_upper_bound`, `..._lower_bound`, `inverter_v_chng_interval` | `double` | inverter voltage change limits (per unit) and interval (s) |
| `violation_flag` | `set` | bit set for determining which violations to check (`VIOLATION0` to `VIOLATION8`, `ALLVIOLATIONS`) |

All default to 0 (and `FALSE`).

Description
-----------

The checks read these properties by name, so the classes may come from a
gridlabd JSON file or from GLM:

| Violation | Objects | Check |
| --------- | ------- | ----- |
| 1 | `transformer`, `overhead_line`, `underground_line`, `triplex_line` | power (current) out of each phase over the rating of the configuration (conductor) |
| 2 | `node`, `triplex_node`, `triplex_meter`, `commercialMeter` group | voltage magnitude over the nominal voltage (twice it for split phases) |
| 3 | `triplex_node`, `triplex_meter`, `commercialMeter` group | as 2, continuously for `node_continuous_voltage_interval` |
| 4, 5 | the `virtual_substation` link | reverse flow current (`flow_direction`) over 50% or 75% of the breaker limit |
| 6 | `inverter` | change of the output voltage per interval |
| 7 | meters fed by a transformer | per-unit voltage rise from the transformer's `from` node to the meter |
| 8 | the `virtual_substation` link | power factor of `power_in` below the limit |

A violation recorder is expected to satisfy:

1. At initialization it opens `file` and writes its header, and finds
   the objects of each kind (a warning for each kind with none).
2. It checks the violations of `violation_flag` (from `violation_delay`
   seconds after the first check) at each postsync pass (`interval` 0),
   at the commit of each time `interval` seconds after the last check, or
   at each commit (`interval` -1).
3. Each violation is a row `TIME,VIOLATIONn, VALUE, UPPER, LOWER, OBJECT,
   CLASS, PHASE, MESSAGE` (numbers with `%f`), echoed to the output when
   `echo` is true. After `limit` rows the file ends with `# end of file`.
4. When the run ends it writes `summary` with the count of each violation
   and of the objects in violation.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> folder = tempfile.mkdtemp()
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 00:00:00"; }}
    ... module tape;
    ... class node {{ set {{A=1,B=2,C=4,N=8}} phases; complex voltage_A[V]; double nominal_voltage[V]; }}
    ... object node {{ name "n1"; phases A; voltage_A 130; nominal_voltage 120; }}
    ... object violation_recorder {{ file "{folder}/v.csv"; summary "{folder}/s.csv"; violation_flag VIOLATION2;
    ...     node_instantaneous_voltage_limit_upper 1.05; node_instantaneous_voltage_limit_lower 0.95; interval -1; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> print(open(f"{folder}/v.csv").read().splitlines()[-1])
    2020-01-01 00:00:00 UTC,VIOLATION2, 1.083333, 1.050000, 0.950000, n1, node, A, Per unit voltage violates limit.
    >>> print(open(f"{folder}/s.csv").read().splitlines()[10])
        NODE (1 of 1 nodes in violation),1
    >>> Class.reset()

Caveats
-------

- Objects are found by class name (and the `commercialMeter` group id);
  the powerflow classes need not exist, and a kind with no objects is
  skipped with a warning.
- A transformer's `power_rating` of 0 is the sum of its phase ratings,
  and phase ratings of 0 are a third of `power_rating`, as powerflow's
  `transformer_configuration::init()` sets them.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Every object of a kind is checked and counted; gridlabd's object
   lists drop the second object they are given (`vobjlist::tack()` adds an
   empty item for it), so it checks one object less and counts one less
   in the summary.
2. The summary counts each object in violation once; gridlabd's
   `uniqueList::insert()` drops the second name in the same way.
3. A triplex line without a conductor is checked against the rating of
   its configuration; gridlabd dereferences a null pointer.

References
----------

- `arras-energy/gridlabd`: `module/tape/violation_recorder.cpp`,
  `violation_recorder.h`
- [Violation_recorder class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Violation_recorder.md)
  (`docs/Module/Tape/Violation_recorder.md`)
"""

import math
from typing import Any

from . import _file
from ._base import TapeClass, prop
from ._common import (TS_INIT, TS_OPEN, TS_DONE, TS_ERROR, TS_ZERO, Prop, gl_error,
    gl_warning, gl_output, get_state, set_state, strtime, to_double, cprintf, is_named)
from .recorder import bool_value

VIOLATIONS = {"VIOLATION0": 0x00, "VIOLATION1": 0x01, "VIOLATION2": 0x02, "VIOLATION3": 0x04,
    "VIOLATION4": 0x08, "VIOLATION5": 0x10, "VIOLATION6": 0x20, "VIOLATION7": 0x40,
    "VIOLATION8": 0x80, "ALLVIOLATIONS": 0xFF}
"""Keywords of `violation_flag`, in publication order"""

XFMR, OHLN, UGLN, TPXL, NODE, TPXN, TPXM, INVT, CMTR = range(1, 10)
"""Object kinds counted in the summary"""

PHASE_A, PHASE_B, PHASE_C, PHASE_S1, PHASE_S2 = 0x1, 0x2, 0x4, 0x10, 0x20
PHASE_S = 0x70
"""Phase bits (gridlabd `PHASE_*`)"""

FLOW_AR, FLOW_BR, FLOW_CR = 0x002, 0x020, 0x200
"""Reverse flow bits of `flow_direction`"""

LIMITS = ("xfrmr_thermal_limit_upper", "xfrmr_thermal_limit_lower", "line_thermal_limit_upper",
    "line_thermal_limit_lower", "node_instantaneous_voltage_limit_upper",
    "node_instantaneous_voltage_limit_lower", "node_continuous_voltage_limit_upper",
    "node_continuous_voltage_limit_lower", "node_continuous_voltage_interval",
    "secondary_dist_voltage_rise_upper_limit", "secondary_dist_voltage_rise_lower_limit")
"""`double` limits whose description is their name"""

class Tracked: # pylint: disable=too-few-public-methods
    """An object checked, with its last values (gridlabd `vobjlist`)"""

    def __init__(self, name:str):
        self.name = name
        self.ref: str|None = None
        self.last_v = [0.0]*3
        self.last_t = [0]*3
        self.last_s = [0]*3

    def update_last(self, i:int, v:float, t:int, s:int) -> None:
        """`vobjlist::update_last()`"""
        if 0 <= i <= 2:
            self.last_v[i], self.last_t[i], self.last_s[i] = v, t, s

class ViolationState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a violation recorder between handler calls"""

    def __init__(self):
        self.status = TS_INIT
        self.fp: Any = None
        self.write_interval = 0
        self.flush_interval = 0
        self.write_count = 0
        self.last_write = TS_ZERO
        self.next_write = TS_ZERO
        self.last_flush = TS_ZERO
        self.interval_write = False
        self.sim_start = -1
        self.lists: dict[str,list[Tracked]] = {}
        self.unique: dict[str,set[str]] = {}
        self.counts = [[0]*10 for _ in range(8)]
        self.monitor: str|None = None
        self.limits: dict[str,float] = {}

def state(model:Any, name:str) -> ViolationState:
    """State of a violation recorder, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = ViolationState()
        set_state(model, name, st)
    return st

def _sign(x:float) -> int:
    return (x > 0) - (x < 0)

class ViolationRecorder(TapeClass):
    """Class `violation_recorder`; see the module documentation"""

    NAME = "violation_recorder"
    PASSCONFIG = "POSTTOPDOWN"
    PROPERTIES = (
        ("file", "char256", prop("output file name")),
        ("summary", "char256", prop("summary output file name")),
        ("virtual_substation", "char256", prop("name of the substation node to monitor for reverse flow violation")),
        ("interval[s]", "double", prop("recording interval (0 'every iteration', -1 'on change')")),
        ("flush_interval[s]", "double", prop("file flush interval (0 never, negative on samples)")),
        ("strict", "bool", prop("causes the violation_recorder to stop the simulation should there be a problem opening or writing with the violation_recorder")),
        ("echo", "bool", prop("causes the violation_recorder to echo messages to the screen")),
        ("limit", "int32", prop("the maximum number of lines to write to the file")),
        ("violation_delay", "int32", prop("the number of seconds to skip before recording violations")),
        *((name, "double", prop(name)) for name in LIMITS),
        ("substation_breaker_A_limit", "double", prop("breaker_phase_A_limit")),
        ("substation_breaker_B_limit", "double", prop("breaker_phase_B_limit")),
        ("substation_breaker_C_limit", "double", prop("breaker_phase_C_limit")),
        ("substation_pf_lower_limit", "double", prop("substation_pf_lower_limit")),
        ("inverter_v_chng_per_interval_upper_bound", "double", prop("inverter_v_chng_per_interval_upper_bound")),
        ("inverter_v_chng_per_interval_lower_bound", "double", prop("inverter_v_chng_per_interval_lower_bound")),
        ("inverter_v_chng_interval", "double", prop("inverter_v_chng_interval")),
        ("violation_flag", "set", prop("bit set for determining which violations to check", keywords=dict(reversed(VIOLATIONS.items())))),
    )
    EVENTS = ("init", "postsync", "commit", "finalize")

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`violation_recorder::init()`"""
        # pylint: disable=too-many-return-statements
        st = state(model, name)
        strict = bool_value(model, name, "strict")
        for key, suffix, label in (("file", "violation-log.csv", "filename"), ("summary", "violation-summary.csv", "summary")):
            if not model.get_property(name, key):
                if strict:
                    gl_error(f"violation_recorder::init(): no {label} defined in strict mode")
                    return False
                value = f"{cls.NAME}-{suffix}"
                model.objects[name][key] = value
                gl_warning(f"violation_recorder::init(): no {label} defined, auto-generating '{value}'")
        st.write_interval = int(to_double(model.get_property(name, "interval") or "0", "s"))
        if st.write_interval < -1:
            gl_error(f"violation_recorder::init(): invalid write_interval of {st.write_interval}, must be -1 or greater")
            return False
        st.flush_interval = int(to_double(model.get_property(name, "flush_interval") or "0", "s"))
        fname = model.get_property(name, "file")
        try:
            st.fp = open(fname, "w", encoding="utf-8") # pylint: disable=consider-using-with
        except OSError:
            if strict:
                gl_error(f"violation_recorder::init(): unable to open file '{fname}' for writing")
                return False
            gl_warning(f"violation_recorder::init(): unable to open file '{fname}' for writing")
            st.status = TS_ERROR
            return True
        st.status = TS_OPEN
        st.fp.write(f"# file...... {fname}\n# date...... {_file.asctime()}\n"
            f"# user...... {_file.getenv('USER')}\n# host...... {_file.getenv('HOST')}\n"
            f"# limit..... {int(model.get_property(name, 'limit') or 0)}\n"
            f"# interval.. {st.write_interval}\n"
            "# timestamp, violation, observation, upper_limit, lower_limit, object(s), object type(s), phase, message\n")
        for key in [p[0] for p in cls.PROPERTIES if p[1] == "double" and not p[0].endswith("]")]:
            st.limits[key] = to_double(model.get_property(name, key) or "0")
        for key, kind, value in (("xfrmr", "class", "transformer"), ("ohl", "class", "overhead_line"),
                ("ugl", "class", "underground_line"), ("tplxl", "class", "triplex_line"),
                ("node", "class", "node"), ("tplx_node", "class", "triplex_node"),
                ("tplx_mtr", "class", "triplex_meter"), ("comm_mtr", "groupid", "commercialMeter"),
                ("inverter", "class", "inverter"), ("powerflow", "module", "powerflow")):
            st.lists[key] = cls._find(model, name, kind, value)
        cls._associate(model, st, "tplx_mtr")
        cls._associate(model, st, "comm_mtr")
        substation = model.get_property(name, "virtual_substation") or ""
        if substation:
            st.monitor = substation if substation in model.objects else None
        else:
            gl_warning("No object specified for monitoring reverse flow; no reverse flow violations will be reported.")
        for key in ("xfrmr_v1", "ohl_v1", "ugl_v1", "tplxl_v1", "node_v2", "tplx_node_v2", "tplx_meter_v2",
                "comm_meter_v2", "tplx_node_v3", "tplx_meter_v3", "comm_meter_v3", "inverter_v6",
                "tplx_meter_v7", "comm_meter_v7"):
            st.unique[key] = set()
        return True

    @staticmethod
    def _find(model:Any, name:str, kind:str, value:str) -> list[Tracked]:
        """`make_object_list()`: the objects of a class, group, or module"""
        names = sorted(model.objects, key=lambda x: model.objects[x].id)
        if kind == "class":
            found = [x for x in names if model.objects[x].oclass.name == value]
        elif kind == "groupid":
            found = [x for x in names if model.objects[x].get("groupid") == value]
        else:
            found = [x for x in names if model.objects[x].oclass.module == value]
        if not found:
            message = f"violation_recorder::init(): the defined group returned an empty set for '{value}'"
            if bool_value(model, name, "strict"):
                gl_error(message)
            else:
                gl_warning(message)
        return [Tracked(x) for x in found]

    @staticmethod
    def _associate(model:Any, st:ViolationState, meters:str) -> None:
        """`assoc_meter_w_xfrmr_node()`: the `from` node of the transformer
        that feeds each meter (following links from the transformer's `to`)"""
        nodes = {item.name for item in st.lists["node"]}
        by_name = {item.name: item for item in st.lists[meters]}
        for xfrmr in st.lists["xfrmr"]:
            current = xfrmr.name
            seen = set()
            while current not in seen:
                seen.add(current)
                to = model.get_property(current, "to") if model.objects[current].oclass.find_property("to") else None
                if to in by_name:
                    source = model.get_property(xfrmr.name, "from")
                    if source in nodes:
                        by_name[to].ref = source
                        break
                for link in st.lists["powerflow"]:
                    if model.objects[link.name].oclass.find_property("from") and model.get_property(link.name, "from") == to:
                        current = link.name
                        break
                else:
                    break

    #
    # Values
    #
    @staticmethod
    def has_phase(model:Any, name:str, phase:int) -> bool:
        """`has_phase()`: all the bits of `phase` are in `phases`"""
        target = Prop(model, name, "phases")
        if not target.is_valid:
            return False
        return target.integer() & phase == phase

    @staticmethod
    def observed(model:Any, name:str, pname:str) -> float|None:
        """`get_observed_double_value()`: the magnitude of a complex, or a
        double; `None` when the property is not found"""
        target = Prop(model, name, pname)
        if not target.is_valid:
            return None
        if target.ptype == "complex":
            return abs(target.complex_value()[0])
        return target.double()

    @staticmethod
    def static(value:float, upper:float, lower:float, norm:float) -> float|None:
        """`fails_static_condition()`: the per-unit value when out of limits"""
        pu = value/norm if norm not in (0.0, 1.0) else value
        return pu if pu > upper or pu < lower else None

    @classmethod
    def static_prop(cls, model:Any, name:str, pname:str, upper:float, lower:float, norm:float) -> float|None:
        """`fails_static_condition()` of a property"""
        value = cls.observed(model, name, pname)
        return None if value is None else cls.static(value, upper, lower, norm)

    @classmethod
    def dynamic(cls, model:Any, item:Tracked, i:int, pname:str, t1:int, interval:float, upper:float, lower:float, norm:float) -> float|None:
        """`fails_dynamic_condition()`: the relative change when it is out
        of limits for `interval`"""
        value = cls.observed(model, item.name, pname)
        if value is None:
            return None
        pu = value/norm
        if item.last_t[i] == 0:
            item.update_last(i, pu, t1, 0)
            return None
        pct = (pu - item.last_v[i])/item.last_v[i] if item.last_v[i] else math.copysign(math.inf, pu - item.last_v[i])
        if pct > upper or pct < lower:
            prev, curr = _sign(item.last_s[i]), _sign(pct)
            if prev in (0, curr):
                if t1 - item.last_t[i] >= int(interval):
                    item.update_last(i, pu, t1, curr)
                    return pct
                item.update_last(i, item.last_v[i], item.last_t[i], curr)
                return None
        item.update_last(i, pu, t1, 0)
        return None

    @classmethod
    def continuous(cls, model:Any, item:Tracked, i:int, pname:str, t1:int, interval:float, upper:float, lower:float, norm:float) -> float|None:
        """`fails_continuous_condition()`: the per-unit value when it is out
        of limits for `interval`"""
        value = cls.observed(model, item.name, pname)
        if value is None:
            return None
        pu = value/norm
        if item.last_t[i] == 0:
            item.update_last(i, pu, t1, _sign(pu) if (pu > upper or pu < lower) else 0)
            return None
        if pu > upper or pu < lower:
            prev, curr = _sign(item.last_s[i]), _sign(pu)
            if prev in (0, curr):
                if t1 - item.last_t[i] >= int(interval):
                    item.update_last(i, pu, t1, curr)
                    return pu
                if prev == 0:
                    item.update_last(i, pu, t1, curr)
                    return None
                item.update_last(i, item.last_v[i], item.last_t[i], curr)
                return None
        item.update_last(i, pu, t1, 0)
        return None

    @staticmethod
    def _ref_double(model:Any, name:str|None, pname:str) -> float:
        """A `double` property of an object referred to (0 when missing)"""
        if not name or name not in model.objects:
            return 0.0
        target = Prop(model, name, pname)
        return target.double() if target.is_valid else 0.0

    #
    # Output
    #
    @classmethod
    def report(cls, model:Any, name:str, st:ViolationState, t1:int, number:int, kind:int|None, text:str, unique:str|None=None, objname:str|None=None) -> None:
        """Count a violation (`increment_violation()`) and write it
        (`write_to_stream()`)"""
        index = int(math.log2(number)) if number else 0
        st.counts[index][0] += 1
        if kind is not None:
            st.counts[index][kind] += 1
        if unique is not None and objname is not None:
            st.unique[unique].add(objname)
        if st.status != TS_OPEN:
            gl_error("violation_recorder::write_line(): trying to write line when the tape is not open")
            return
        st.fp.write(f"{strtime(model, t1)},{text[:1022]}\n")
        st.write_count += 1
        if st.flush_interval > 0:
            if st.last_flush + st.flush_interval <= t1:
                st.last_flush = t1
        elif st.flush_interval < 0 and (st.write_count + 1) % (-st.flush_interval) == 0:
            st.fp.flush()
        limit = int(model.get_property(name, "limit") or 0)
        if 0 < limit <= st.write_count:
            st.fp.write("# end of file\n")
            st.fp.close()
            st.fp = None
            st.status = TS_DONE
        if bool_value(model, name, "echo"):
            gl_output(text)

    @staticmethod
    def _label(model:Any, name:str) -> str:
        """`gl_name()`: the object name, or `CLASS:ID`"""
        obj = model.objects[name]
        return name if is_named(model, name) else f"{obj.oclass.name}:{obj.id}"

    #
    # Checks
    #
    @classmethod
    def check(cls, model:Any, name:str, st:ViolationState, t1:int) -> None:
        """`check_violations()`"""
        if st.sim_start == -1:
            st.sim_start = t1
        if t1 - st.sim_start < int(model.get_property(name, "violation_delay") or 0):
            return
        flags = Prop(model, name, "violation_flag").integer()
        for bit, check in ((0x01, cls.check1), (0x02, cls.check2), (0x04, cls.check3), (0x08, cls.check4),
                (0x10, cls.check5), (0x20, cls.check6), (0x40, cls.check7), (0x80, cls.check8)):
            if flags & bit:
                check(model, name, st, t1)

    @classmethod
    def _line_rating(cls, model:Any, name:str, conductor:str) -> float:
        config = model.get_property(name, "configuration") if model.objects[name].oclass.find_property("configuration") else None
        if not config or config not in model.objects:
            return 0.0
        cond = model.get_property(config, conductor) if model.objects[config].oclass.find_property(conductor) else None
        if cond and cond in model.objects:
            return cls._ref_double(model, cond, "rating.summer.continuous")
        return cls._ref_double(model, config, "rating.summer.continuous")

    @classmethod
    def check1(cls, model:Any, name:str, st:ViolationState, t1:int) -> None: # pylint: disable=too-many-locals
        """`check_violation_1()`: thermal limits of transformers and lines"""
        lim = st.limits
        upper, lower = lim["xfrmr_thermal_limit_upper"], lim["xfrmr_thermal_limit_lower"]
        for item in st.lists["xfrmr"]:
            config = model.get_property(item.name, "configuration") if model.objects[item.name].oclass.find_property("configuration") else None
            rating = cls._ref_double(model, config, "power_rating")
            phase_ratings = [cls._ref_double(model, config, f"power{p}_rating") for p in "ABC"]
            if rating == 0:
                rating = sum(phase_ratings)
            if sum(phase_ratings) == 0 and rating > 0:
                phase_ratings = [rating/3]*3
            checks = [("S", PHASE_S, "power_out", rating)] if cls.has_phase(model, item.name, PHASE_S) else \
                [(p, bit, f"power_out_{p}", phase_ratings[i]) for i, (p, bit) in enumerate((("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)))]
            for phase, bit, pname, nominal in checks:
                if phase != "S" and not cls.has_phase(model, item.name, bit):
                    continue
                value = cls.static_prop(model, item.name, pname, upper, lower, nominal*1000.0)
                if value is not None:
                    cls.report(model, name, st, t1, 0x01, XFMR, cprintf("VIOLATION1, %f, %f, %f, %s, %s, %s, Power violates thermal limit.", value, upper, lower, cls._label(model, item.name), model.objects[item.name].oclass.name, phase), "xfrmr_v1", item.name)
        upper, lower = lim["line_thermal_limit_upper"], lim["line_thermal_limit_lower"]
        for key, kind, unique in (("ohl", OHLN, "ohl_v1"), ("ugl", UGLN, "ugl_v1"), ("tplxl", TPXL, "tplxl_v1")):
            for item in st.lists[key]:
                if cls.has_phase(model, item.name, PHASE_S):
                    checks = [("S1", "current_out_A", cls._line_rating(model, item.name, "conductor_1")),
                        ("S2", "current_out_B", cls._line_rating(model, item.name, "conductor_2"))]
                else:
                    checks = [(p, f"current_out_{p}", cls._line_rating(model, item.name, f"conductor_{p}"))
                        for p, bit in (("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)) if cls.has_phase(model, item.name, bit)]
                for phase, pname, nominal in checks:
                    value = cls.static_prop(model, item.name, pname, upper, lower, nominal)
                    if value is not None:
                        cls.report(model, name, st, t1, 0x01, kind, cprintf("VIOLATION1, %f, %f, %f, %s, %s, %s, Current violates thermal limit.", value, upper, lower, cls._label(model, item.name), model.objects[item.name].oclass.name, phase), unique, item.name)

    @classmethod
    def check2(cls, model:Any, name:str, st:ViolationState, t1:int) -> None:
        """`check_violation_2()`: instantaneous voltage limits"""
        upper, lower = st.limits["node_instantaneous_voltage_limit_upper"], st.limits["node_instantaneous_voltage_limit_lower"]
        for key, kind, unique in (("node", NODE, "node_v2"), ("comm_mtr", CMTR, "comm_meter_v2")):
            for item in st.lists[key]:
                nominal = cls.observed(model, item.name, "nominal_voltage") or 0.0
                for phase, bit in (("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)):
                    if cls.has_phase(model, item.name, bit):
                        value = cls.static_prop(model, item.name, f"voltage_{phase}", upper, lower, nominal)
                        if value is not None:
                            cls.report(model, name, st, t1, 0x02, kind, cprintf("VIOLATION2, %f, %f, %f, %s, %s, %s, Per unit voltage violates limit.", value, upper, lower, cls._label(model, item.name), model.objects[item.name].oclass.name, phase), unique, item.name)
        for key, kind, unique in (("tplx_node", TPXN, "tplx_node_v2"), ("tplx_mtr", TPXM, "tplx_meter_v2")):
            for item in st.lists[key]:
                nominal = (cls.observed(model, item.name, "nominal_voltage") or 0.0)*2
                if cls.has_phase(model, item.name, PHASE_S1) and cls.has_phase(model, item.name, PHASE_S2):
                    value = cls.static_prop(model, item.name, "voltage_12", upper, lower, nominal)
                    if value is not None:
                        cls.report(model, name, st, t1, 0x02, kind, cprintf("VIOLATION2, %f, %f, %f, %s, %s, S, Per unit voltage violates limit.", value, upper, lower, cls._label(model, item.name), model.objects[item.name].oclass.name), unique, item.name)

    @classmethod
    def check3(cls, model:Any, name:str, st:ViolationState, t1:int) -> None:
        """`check_violation_3()`: continuous voltage limits"""
        upper, lower = st.limits["node_continuous_voltage_limit_upper"], st.limits["node_continuous_voltage_limit_lower"]
        interval = st.limits["node_continuous_voltage_interval"]
        message = "VIOLATION3, %f, %f, %f, %s, %s, %s, Per unit voltage violates limit continuously over %is interval."
        for key, kind, unique in (("tplx_node", TPXN, "tplx_node_v3"), ("tplx_mtr", TPXM, "tplx_meter_v3")):
            for item in st.lists[key]:
                nominal = (cls.observed(model, item.name, "nominal_voltage") or 0.0)*2
                if cls.has_phase(model, item.name, PHASE_S1) and cls.has_phase(model, item.name, PHASE_S2):
                    value = cls.continuous(model, item, 0, "voltage_12", t1, interval, upper, lower, nominal)
                    if value is not None:
                        cls.report(model, name, st, t1, 0x04, kind, cprintf(message, value, upper, lower, cls._label(model, item.name), model.objects[item.name].oclass.name, "S", int(interval)), unique, item.name)
        for item in st.lists["comm_mtr"]:
            nominal = cls.observed(model, item.name, "nominal_voltage") or 0.0
            for phase, bit in (("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)):
                if cls.has_phase(model, item.name, bit):
                    value = cls.continuous(model, item, 0, f"voltage_{phase}", t1, interval, upper, lower, nominal)
                    if value is not None:
                        cls.report(model, name, st, t1, 0x04, CMTR, cprintf(message, value, upper, lower, cls._label(model, item.name), model.objects[item.name].oclass.name, phase, int(interval)), "comm_meter_v3", item.name)

    @classmethod
    def check4(cls, model:Any, name:str, st:ViolationState, t1:int) -> None:
        """`check_violation_4()`: reverse flow warning"""
        cls.reverse(model, name, st, t1, 0x08, 0.50, "Reverse flow current warning.")

    @classmethod
    def check5(cls, model:Any, name:str, st:ViolationState, t1:int) -> None:
        """`check_violation_5()`: reverse flow violation"""
        cls.reverse(model, name, st, t1, 0x10, 0.75, "Reverse flow current violates limit.")

    @classmethod
    def reverse(cls, model:Any, name:str, st:ViolationState, t1:int, number:int, pct:float, text:str) -> None:
        """`check_reverse_flow_violation()`"""
        link = st.monitor
        if link is None:
            return
        directions = Prop(model, link, "flow_direction")
        if not directions.is_valid:
            return
        flow = directions.integer()
        for phase, bit, reverse in (("A", PHASE_A, FLOW_AR), ("B", PHASE_B, FLOW_BR), ("C", PHASE_C, FLOW_CR)):
            if cls.has_phase(model, link, bit) and flow & reverse == reverse:
                upper = st.limits[f"substation_breaker_{phase}_limit"]*pct
                value = cls.static_prop(model, link, f"current_out_{phase}", upper, 0.0, 1.0)
                if value is not None:
                    cls.report(model, name, st, t1, number, None, cprintf("VIOLATION%i, %f, %f, %f, %s, %s, %s, %s", int(math.log2(number))+1, value, upper, 0.0, cls._label(model, link), model.objects[link].oclass.name, phase, text))

    @classmethod
    def check6(cls, model:Any, name:str, st:ViolationState, t1:int) -> None:
        """`check_violation_6()`: inverter voltage changes"""
        upper = st.limits["inverter_v_chng_per_interval_upper_bound"]
        lower = st.limits["inverter_v_chng_per_interval_lower_bound"]
        interval = st.limits["inverter_v_chng_interval"]
        message = "VIOLATION6, %f, %f, %f, %s, %s, %s, Voltage change between %is intervals violates limit."
        for item in st.lists["inverter"]:
            if cls.has_phase(model, item.name, PHASE_S):
                checks = [("S", 1, "phaseB_V_Out")]
            else:
                checks = [(p, i, f"phase{p}_V_Out") for i, (p, bit) in enumerate((("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C))) if cls.has_phase(model, item.name, bit)]
            for phase, i, pname in checks:
                value = cls.dynamic(model, item, i, pname, t1, interval, upper, lower, 1.0)
                if value is not None:
                    cls.report(model, name, st, t1, 0x20, None, cprintf(message, value, upper, lower, cls._label(model, item.name), model.objects[item.name].oclass.name, phase, int(interval)), "inverter_v6", item.name)

    @classmethod
    def check7(cls, model:Any, name:str, st:ViolationState, t1:int) -> None: # pylint: disable=too-many-locals
        """`check_violation_7()`: voltage rise from transformer to meter"""
        upper = st.limits["secondary_dist_voltage_rise_upper_limit"]
        lower = st.limits["secondary_dist_voltage_rise_lower_limit"]
        message = "VIOLATION7, %f, %f, %f, %s %s, %s %s, %s, Per unit voltage difference between objects violates limit."
        for key, kind, unique, split in (("tplx_mtr", TPXM, "tplx_meter_v7", True), ("comm_mtr", CMTR, "comm_meter_v7", False)):
            for item in st.lists[key]:
                if item.ref is None:
                    continue
                meter_nominal = cls.observed(model, item.name, "nominal_voltage") or 0.0
                sides = ([("S1", PHASE_S1, "voltage_1"), ("S2", PHASE_S2, "voltage_2")] if split else [(None, 0, None)])
                for side, side_bit, side_prop in sides:
                    if side is not None and not cls.has_phase(model, item.name, side_bit):
                        continue
                    for phase, bit in (("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)):
                        if not cls.has_phase(model, item.name, bit):
                            continue
                        meter_voltage = cls.observed(model, item.name, side_prop or f"voltage_{phase}") or 0.0
                        xfrmr_nominal = cls.observed(model, item.ref, "nominal_voltage") or 0.0
                        xfrmr_voltage = cls.observed(model, item.ref, f"voltage_{phase}") or 0.0
                        try:
                            pu = meter_voltage/meter_nominal - xfrmr_voltage/xfrmr_nominal
                        except ZeroDivisionError:
                            pu = math.nan
                        value = cls.static(pu, upper, lower, 1.0)
                        if value is not None:
                            label = f"{phase} {side}" if side else phase
                            cls.report(model, name, st, t1, 0x40, kind, cprintf(message, value, upper, lower, cls._label(model, item.name), cls._label(model, item.ref), model.objects[item.name].oclass.name, model.objects[item.ref].oclass.name, label), unique, item.name)

    @classmethod
    def check8(cls, model:Any, name:str, st:ViolationState, t1:int) -> None:
        """`check_violation_8()`: substation power factor"""
        link = st.monitor
        if link is None:
            return
        target = Prop(model, link, "power_in")
        if not target.is_valid:
            return
        power = target.complex_value()[0] if target.ptype == "complex" else complex(0, 0)
        pf = power.real/abs(power) if abs(power) else math.nan
        lower = st.limits["substation_pf_lower_limit"]
        value = cls.static(pf, 1.0, lower, 1.0)
        if value is not None:
            cls.report(model, name, st, t1, 0x80, None, cprintf("VIOLATION8, %f, %f, %f, %s, %s,, %s", value, 1.0, lower, cls._label(model, link), model.objects[link].oclass.name, "Power factor violates limit."))

    #
    # Events
    #
    @classmethod
    def postsync(cls, model:Any, name:str, t1:int) -> int|None:
        """`violation_recorder::postsync()`"""
        st = state(model, name)
        if st.write_interval == 0:
            if st.status == TS_OPEN:
                cls.check(model, name, st, t1)
        elif st.write_interval > 0:
            if st.last_write + st.write_interval <= t1:
                st.interval_write = True
                st.last_write = t1
                st.next_write = t1 + st.write_interval
            return st.next_write
        return None

    @classmethod
    def commit(cls, model:Any, name:str, t1:int) -> int|None:
        """`violation_recorder::commit()`"""
        st = state(model, name)
        strict = bool_value(model, name, "strict")
        if st.status == TS_ERROR and strict:
            gl_error("violation_recorder::commit(): the object has error'ed and is halting the simulation")
            return 0
        if st.status != TS_OPEN:
            return None
        if st.write_interval > 0 and st.interval_write:
            cls.check(model, name, st, t1)
            st.last_write = t1
            st.interval_write = False
        if st.write_interval == -1:
            cls.check(model, name, st, t1)
        if st.status == TS_ERROR and strict:
            gl_error("violation_recorder::commit(): the object has error'ed and is halting the simulation")
            return 0
        return None

    @classmethod
    def finalize(cls, model:Any, name:str, t:int) -> None: # pylint: disable=unused-argument
        """`violation_recorder::finalize()`: write the summary"""
        st = get_state(model, name)
        if st is None:
            return
        if st.fp is not None:
            st.fp.close()
            st.fp = None
        if st.status == TS_INIT:
            return
        fname = model.get_property(name, "summary")
        try:
            out = open(fname, "w", encoding="utf-8") # pylint: disable=consider-using-with
        except OSError:
            gl_warning(f"violation_recorder::init(): unable to open file '{fname}' for writing")
            return
        lists, unique, counts = st.lists, st.unique, st.counts
        def line(label:str, key:str, of:str, what:str, number:int, kind:int) -> str:
            return f"    {label} ({len(unique[key])} of {len(lists[of])} {what} in violation),{counts[number][kind]}\n"
        with out:
            out.write(f"# file...... {fname}\n# date...... {_file.asctime()}\n"
                f"# user...... {_file.getenv('USER')}\n# host...... {_file.getenv('HOST')}\n")
            out.write(f"VIOLATION1 TOTAL,{counts[0][0]}\n")
            out.write(line("TRANSFORMER", "xfrmr_v1", "xfrmr", "transformers", 0, XFMR))
            out.write(line("OVERHEAD LINE", "ohl_v1", "ohl", "lines", 0, OHLN))
            out.write(line("UNDERGROUND LINE", "ugl_v1", "ugl", "lines", 0, UGLN))
            out.write(line("TRIPLEX LINE", "tplxl_v1", "tplxl", "lines", 0, TPXL))
            out.write(f"VIOLATION2 TOTAL,{counts[1][0]}\n")
            out.write(line("NODE", "node_v2", "node", "nodes", 1, NODE))
            out.write(line("TRIPLEX NODE", "tplx_node_v2", "tplx_node", "nodes", 1, TPXN))
            out.write(line("TRIPLEX METER", "tplx_meter_v2", "tplx_mtr", "meters", 1, TPXM))
            out.write(line("COMMERCIAL METER", "comm_meter_v2", "comm_mtr", "meters", 1, CMTR))
            out.write(f"VIOLATION3 TOTAL,{counts[2][0]}\n")
            out.write(line("TRIPLEX NODE", "tplx_node_v3", "tplx_node", "nodes", 2, TPXN))
            out.write(line("TRIPLEX METER", "tplx_meter_v3", "tplx_mtr", "meters", 2, TPXM))
            out.write(line("COMMERCIAL METER", "comm_meter_v3", "comm_mtr", "meters", 2, CMTR))
            out.write(f"VIOLATION4 TOTAL,{counts[3][0]}\n")
            out.write(f"VIOLATION5 TOTAL,{counts[4][0]}\n")
            out.write(f"VIOLATION6 TOTAL ({len(unique['inverter_v6'])} of {len(lists['inverter'])} inverters in violation),{counts[5][0]}\n")
            out.write(f"VIOLATION7 TOTAL,{counts[6][0]}\n")
            out.write(line("TRIPLEX METER", "tplx_meter_v7", "tplx_mtr", "meters", 6, TPXM))
            out.write(line("COMMERCIAL METER", "comm_meter_v7", "comm_mtr", "meters", 6, CMTR))
            out.write(f"VIOLATION8 TOTAL,{counts[7][0]}\n")
