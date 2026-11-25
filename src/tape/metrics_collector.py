# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Metrics collectors (class `metrics_collector`)

A `metrics_collector` collects the values of its parent every second and
computes metrics (minimum, maximum, average, median, energy, voltage
violations, ...) over each interval, for a `metrics_collector_writer` to
write.

Syntax
------

    module tape;
    object metrics_collector {
        parent <triplex_meter|meter|house|waterheater|inverter|capacitor|regulator|substation>;
        interval <seconds>;
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `interval` | `double[s]` | `-1 s` | Interval at which the metrics_collector output is stored in JSON format |

Description
-----------

The parent's class (or a class it inherits from) selects what is
collected:

| Parent | Values | Metrics |
| ------ | ------ | ------- |
| `triplex_meter`, `meter` | `measured_real_power`, `measured_reactive_power`, `price`, voltages (`voltage_1`, `voltage_2`, `voltage_12`; or `voltage_A` ... `voltage_CA`), `nominal_voltage` | power statistics, energy, bill, line-to-line and line-to-neutral voltage statistics, unbalance, and ANSI range A and B violation durations and counts |
| `house` | `total_load`, `hvac_load`, `air_temperature`, `cooling_setpoint`, `heating_setpoint` | load and temperature statistics, average setpoint deviations |
| `waterheater` | `actual_load` | load statistics (keyed on the house it belongs to) |
| `inverter` | `VA_Out` | real and reactive power statistics |
| `capacitor`, `regulator` | `cap_X_switch_count`, `tap_X_change_count` | operations |
| `substation` or `meter` that is a `SWING` bus | `distribution_load` or `measured_power`, and the `power_losses` of the powerflow links | feeder power statistics, energy, losses |

A metrics collector is expected to satisfy:

1. At initialization it checks its parent (a substation must be a
   `SWING` bus) and that `interval` is positive.
2. Its postsync pass asks to run again one second later; at each commit
   it stores the values, interpolating over the seconds it did not run.
3. At the commit of each time `interval` seconds after the last, it
   computes the metrics of the interval.

Examples
--------

    >>> from arras import Model, Class, Runner
    >>> from tape.metrics_collector import metrics
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''clock { timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 00:00:10"; }
    ... module tape;
    ... class inverter { complex VA_Out[VA]; }
    ... object inverter { name "pv"; VA_Out 1000+100j; object metrics_collector { name "mc"; interval 5; }; }
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> metrics(m, "mc")
    [1000.0, 1000.0, 1000.0, 1000.0, 100.0, 100.0, 100.0, 100.0]
    >>> Class.reset()

Caveats
-------

- Collecting every second makes the run take a time step every second.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The energy of an interval is its average power times `interval`
   seconds; gridlabd multiplies by the flag `interval_write` (1), so its
   energies are the average power over one second.

References
----------

- `arras-energy/gridlabd`: `module/tape/metrics_collector.cpp`,
  `metrics_collector.h`
- [Metrics_collector class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Metrics_collector.md)
  (`docs/Module/Tape/Metrics_collector.md`)
"""

import math
from typing import Any

from ._base import TapeClass, prop
from ._common import Prop, gl_error, gl_warning, get_state, set_state, clock, to_double, is_named

LINK_CLASSES = ("overhead_line", "underground_line", "triplex_line", "transformer", "regulator", "switch", "fuse")
"""Classes whose losses a swing bus collector adds"""

SIZES = {"triplex_meter": 30, "meter": 30, "house": 18, "waterheater": 4, "inverter": 8,
    "capacitor": 1, "regulator": 1, "swingbus": 18}
"""Number of metrics of each kind"""

class MetricsState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a metrics collector between handler calls"""

    def __init__(self):
        self.kind = ""
        self.parent_name = "No name given"
        self.metrics: list[float] = []
        self.arrays: dict[str,list[float]] = {}
        self.interval = -1
        self.curr_index = 0
        self.last_index = 0
        self.last_write = 0
        self.next_write = 0
        self.start_time = 0
        self.interval_write = False
        self.last_vol_val = -1.0
        self.price = 0.0
        self.links: list[str] = []

def state(model:Any, name:str) -> MetricsState:
    """State of a metrics collector, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = MetricsState()
        set_state(model, name, st)
    return st

def metrics(model:Any, name:str) -> list[float]:
    """The metrics a metrics collector computed for its last interval"""
    return list(state(model, name).metrics)

def _median(values:list[float]) -> float:
    """`findMedian()`: sorts `values` in place, as `std::sort()` does"""
    values.sort()
    n = len(values)
    return values[n//2] if n % 2 else (values[n//2 - 1] + values[n//2])/2

def _out_of_limit(last:float, values:list[float], above:bool, limit:float) -> tuple[float,int]:
    """`findOutLimit()`: the duration and count of violations of `limit`"""
    # pylint: disable=too-many-branches
    count = 0
    duration = 0.0
    if values[0] > limit:
        past = 1
    elif values[0] == limit:
        past = 0
        count += 1
    else:
        past = -1
    if len(values) <= 1:
        return 0.0, 0
    for value in values[1:]:
        if value > limit:
            if past == 1:
                duration += 1
            elif past == 0:
                duration += 1
                past = 1
            else:
                count += 1
                duration += 0.5
                past = 1
        elif value == limit:
            if past == 1:
                duration += 1
                count += 1
                past = 0
            elif past == -1:
                count += 1
                past = 0
        else:
            if past == 1:
                duration += 0.5
                count += 1
                past = -1
            elif past == 0:
                past = -1
    if last >= 0:
        if (last < limit < values[0]) or (last > limit > values[0]):
            count += 1
            duration += 0.5
        elif last > limit and values[0] > limit:
            duration += 1
        elif values[0] == limit and last != limit:
            duration += 1
            count += 1
    return (duration, count) if above else (len(values) - duration, count)

class MetricsCollector(TapeClass):
    """Class `metrics_collector`; see the module documentation"""

    NAME = "metrics_collector"
    PASSCONFIG = "POSTTOPDOWN"
    PROPERTIES = (
        ("interval[s]", "double", prop("Interval at which the metrics_collector output is stored in JSON format", "-1 s")),
    )
    EVENTS = ("init", "postsync", "commit")

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool:
        """`metrics_collector::init()`"""
        # pylint: disable=too-many-branches,too-many-return-statements
        st = state(model, name)
        parent = model.objects[name].get("parent")
        if not parent:
            gl_error("metrics_collector must have a parent (triplex meter, house, waterheater, inverter, substation, or meter)")
            return False
        oclass = model.objects[parent].oclass
        for kind in ("triplex_meter", "house", "waterheater", "inverter", "capacitor", "regulator"):
            if oclass.isa(kind):
                st.kind = kind
                break
        else:
            if oclass.isa("substation"):
                bustype = Prop(model, parent, "bustype")
                if not bustype.is_valid or bustype.ptype != "enumeration":
                    gl_error(f"metrics_collector:{name if is_named(model, name) else 'unnamed'} failed to map bustype variable from {parent if is_named(model, parent) else 'unnamed'}")
                    return False
                if bustype.integer() != 2:
                    gl_error("If a metrics_collector is attached to a substation, it must be a SWING bus")
                    return False
                st.kind = "swingbus"
            elif oclass.isa("meter"):
                st.kind = "meter"
                bustype = Prop(model, parent, "bustype")
                if bustype.is_valid and bustype.ptype == "enumeration" and bustype.integer() == 2:
                    st.kind = "swingbus"
            else:
                gl_error("metrics_collector allows only these parents: triplex meter, house, waterheater, inverter, substation, meter, capacitor, regulator")
                return False
        owner = parent
        if st.kind == "waterheater":
            owner = model.objects[parent].get("parent") or ""
        if owner and is_named(model, owner):
            st.parent_name = owner
        elif st.kind == "swingbus":
            st.parent_name = "Swing Bus Metrics"
        if st.kind == "swingbus":
            st.links = [x for x in sorted(model.objects, key=lambda n: model.objects[n].id) if model.objects[x].oclass.module == "powerflow"]
            if not st.links:
                gl_warning("No link objects were found.")
        st.metrics = [0.0]*SIZES[st.kind]
        st.interval = int(to_double(model.get_property(name, "interval") or "-1", "s"))
        if st.interval <= 0:
            gl_error(f"metrics_collector::init(): invalid interval of {st.interval}, must be greater than 0")
            return False
        names = {"triplex_meter": ("real", "reactive", "vll", "vln", "unbalance"),
            "meter": ("real", "reactive", "vll", "vln", "unbalance"),
            "house": ("total", "hvac", "air", "cooling", "heating"), "waterheater": ("wh",),
            "inverter": ("real", "reactive"), "swingbus": ("real", "reactive", "real_loss", "reactive_loss"),
            "capacitor": ("count",), "regulator": ("count",)}[st.kind]
        st.arrays = {key: [0.0]*st.interval for key in names}
        st.curr_index = st.last_index = 0
        st.last_write = t
        st.next_write = t + st.interval
        st.start_time = t
        return True

    @staticmethod
    def _interpolate(values:list[float], idx1:int, idx2:int, val2:float) -> None:
        """`interpolate()`"""
        values[idx2] = val2
        steps = idx2 - idx1
        if steps > 1:
            val1 = values[idx1]
            delta = (val2 - val1)/steps
            for i in range(idx1 + 1, idx2):
                val1 += delta
                values[i] = val1

    @staticmethod
    def _double(model:Any, name:str, pname:str) -> float:
        target = Prop(model, name, pname)
        return target.double() if target.is_valid else 0.0

    @staticmethod
    def _complex(model:Any, name:str, pname:str) -> complex:
        target = Prop(model, name, pname)
        return target.complex_value()[0] if target.is_valid and target.ptype == "complex" else complex(0, 0)

    @classmethod
    def read(cls, model:Any, name:str, st:MetricsState) -> bool:
        """`metrics_collector::read_line()`"""
        # pylint: disable=too-many-locals,too-many-statements,too-many-branches
        now = clock(model)
        st.curr_index = now - st.last_write
        if st.curr_index > st.last_index:
            st.curr_index -= 1
        if st.curr_index < 0 or st.curr_index >= st.interval:
            gl_error("metrics_collector::curr_index value exceeds the limit")
            return False
        parent = model.objects[name]["parent"]
        a, i1, i2 = st.arrays, st.last_index, st.curr_index
        put = cls._interpolate
        if st.kind in ("triplex_meter", "meter"):
            put(a["real"], i1, i2, cls._double(model, parent, "measured_real_power"))
            put(a["reactive"], i1, i2, cls._double(model, parent, "measured_reactive_power"))
            st.price = cls._double(model, parent, "price")
            if st.kind == "triplex_meter":
                v1 = abs(cls._complex(model, parent, "voltage_1"))
                v2 = abs(cls._complex(model, parent, "voltage_2"))
                v12 = abs(cls._complex(model, parent, "voltage_12"))
                if st.start_time == now:
                    st.last_vol_val = abs(v12)
                vavg = 0.5*(v1 + v2)
                put(a["vll"], i1, i2, abs(v12))
                put(a["vln"], i1, i2, vavg)
                put(a["unbalance"], i1, i2, 0.5*abs(v1 - v2)/vavg if vavg else math.nan)
            else:
                va, vb, vc = (abs(cls._complex(model, parent, f"voltage_{p}")) for p in "ABC")
                vab, vbc, vca = (abs(cls._complex(model, parent, f"voltage_{p}")) for p in ("AB", "BC", "CA"))
                vll = (vab + vbc + vca)/3.0
                vdev = max(abs(vab - vll), abs(vbc - vll), abs(vca - vll))
                if st.start_time == now:
                    st.last_vol_val = vll
                put(a["vll"], i1, i2, vll)
                put(a["vln"], i1, i2, (va + vb + vc)/3.0)
                put(a["unbalance"], i1, i2, vdev/vll if vll else math.nan)
        elif st.kind == "house":
            air = cls._double(model, parent, "air_temperature")
            put(a["total"], i1, i2, cls._double(model, parent, "total_load"))
            put(a["hvac"], i1, i2, cls._double(model, parent, "hvac_load"))
            put(a["air"], i1, i2, air)
            put(a["cooling"], i1, i2, air - cls._double(model, parent, "cooling_setpoint"))
            put(a["heating"], i1, i2, air - cls._double(model, parent, "heating_setpoint"))
        elif st.kind == "waterheater":
            put(a["wh"], i1, i2, cls._double(model, parent, "actual_load"))
        elif st.kind == "inverter":
            va_out = cls._complex(model, parent, "VA_Out")
            put(a["real"], i1, i2, va_out.real)
            put(a["reactive"], i1, i2, va_out.imag)
        elif st.kind == "capacitor":
            put(a["count"], i1, i2, sum(cls._double(model, parent, f"cap_{p}_switch_count") for p in "ABC"))
        elif st.kind == "regulator":
            put(a["count"], i1, i2, sum(cls._double(model, parent, f"tap_{p}_change_count") for p in "ABC"))
        else:
            feeder = cls._complex(model, parent, "distribution_load" if model.objects[parent].oclass.isa("substation") else "measured_power")
            put(a["real"], i1, i2, feeder.real)
            put(a["reactive"], i1, i2, feeder.imag)
            losses = complex(0, 0)
            for link in st.links:
                if model.objects[link].oclass.name in LINK_CLASSES:
                    loss = cls._complex(model, link, "power_losses")
                    losses += complex(abs(loss.real), loss.imag)
            put(a["real_loss"], i1, i2, losses.real)
            put(a["reactive_loss"], i1, i2, losses.imag)
        st.last_index = st.curr_index
        return True

    @classmethod
    def compute(cls, model:Any, name:str, st:MetricsState) -> None:
        """`metrics_collector::write_line()`: the metrics of the interval"""
        a, m = st.arrays, st.metrics
        def stats(key:str) -> list[float]:
            values = a[key]
            last = values[-1]
            result = [min(values), max(values), sum(values)/len(values), _median(values)]
            values[0] = last
            return result
        if st.kind in ("triplex_meter", "meter"):
            m[0:4] = stats("real")
            m[4:8] = stats("reactive")
            m[8] = m[2]*st.interval/3600
            m[9] = m[6]*st.interval/3600
            m[10] = m[8]*st.price/1000
            vll = a["vll"]
            m[11:14] = [min(vll), max(vll), sum(vll)/len(vll)]
            m[14:17] = [min(a["vln"]), max(a["vln"]), sum(a["vln"])/len(a["vln"])]
            m[17:20] = [min(a["unbalance"]), max(a["unbalance"]), sum(a["unbalance"])/len(a["unbalance"])]
            nominal = cls._double(model, model.objects[name]["parent"], "nominal_voltage")
            for index, (above, scale) in enumerate(((True, 1.05*math.sqrt(3)), (False, 0.95*math.sqrt(3)),
                    (True, 1.058*math.sqrt(3)), (False, 0.917*math.sqrt(3)), (False, 0.1))):
                m[20 + 2*index], m[21 + 2*index] = _out_of_limit(st.last_vol_val, vll, above, nominal*scale)
            st.last_vol_val = vll[-1]
            for key in ("vll", "vln", "unbalance"):
                a[key][0] = a[key][-1]
        elif st.kind == "house":
            m[4:8] = stats("total")
            m[0:4] = stats("hvac")
            m[8:12] = stats("air")
            m[12] = sum(a["cooling"])/len(a["cooling"])
            m[13] = sum(a["heating"])/len(a["heating"])
            a["cooling"][0] = a["cooling"][-1]
            a["heating"][0] = a["heating"][-1]
        elif st.kind == "waterheater":
            m[0:4] = stats("wh")
        elif st.kind == "inverter":
            m[0:4] = stats("real")
            m[4:8] = stats("reactive")
        elif st.kind in ("capacitor", "regulator"):
            m[0] = max(a["count"])
            a["count"][0] = a["count"][-1]
        else:
            m[0:4] = stats("real")
            m[4:8] = stats("reactive")
            m[8] = m[2]*st.interval/3600
            m[9] = m[6]*st.interval/3600
            m[10:14] = stats("real_loss")
            m[14:18] = stats("reactive_loss")

    @classmethod
    def postsync(cls, model:Any, name:str, t1:int) -> int:
        """`metrics_collector::postsync()`: run again one second later"""
        st = state(model, name)
        if st.next_write <= t1:
            st.interval_write = True
        return t1 + 1

    @classmethod
    def commit(cls, model:Any, name:str, t1:int) -> int|None:
        """`metrics_collector::commit()`"""
        st = state(model, name)
        if not cls.read(model, name, st):
            gl_error("metrics_collector::commit(): error when reading the values")
            return 0
        if st.interval_write:
            st.last_write = t1
            st.next_write = t1 + st.interval
            cls.compute(model, name, st)
            st.interval_write = False
            st.last_index = 0
        return None
