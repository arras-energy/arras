# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Metrics collector writers (class `metrics_collector_writer`)

A `metrics_collector_writer` gathers the metrics of all the
`metrics_collector` objects at each interval and writes them to JSON
files when the run reaches its stop time.

Syntax
------

    module tape;
    object metrics_collector_writer {
        filename "<file>";
        interval <seconds>;
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `filename` | `char1024` | | the JSON formatted output file name |
| `interval` | `double[s]` | `0 s` | Interval at which the metrics_collector_writer output is stored in JSON format |

Description
-----------

A metrics collector writer is expected to satisfy:

1. At initialization it checks that `interval` is positive, that there
   are metrics collectors, and that they all have the same interval. A
   `filename` left empty is `metrics_collector_writer-ID-metrics_collector_output.json`
   (with a warning).
2. At the commit of each time `interval` seconds after the last, it adds
   the metrics of every collector, keyed on the seconds since the start
   and on the name of the collector's parent (for a water heater, the
   house it belongs to), to six documents: billing meters (triplex meters
   and meters), houses (with their water heaters), inverters, capacitors,
   regulators, and the feeder (swing bus). Each document also has its
   `StartTime` and `Metadata` (the index and unit of each metric).
3. When the time reaches `stoptime`, it writes the documents to
   `billing_meter_FILE`, `house_FILE`, `inverter_FILE`, `capacitor_FILE`,
   `regulator_FILE`, and `substation_FILE`, as jsoncpp's `StyledWriter`
   writes them.

Examples
--------

    >>> import os, json, tempfile
    >>> from arras import Model, Class, Runner
    >>> Class.reset()
    >>> here = os.getcwd()
    >>> os.chdir(tempfile.mkdtemp())
    >>> m = Model()
    >>> m.read_glm(f'''clock {{ timezone "UTC"; starttime "2020-01-01 00:00:00"; stoptime "2020-01-01 00:00:10"; }}
    ... module tape;
    ... class inverter {{ complex VA_Out[VA]; }}
    ... object inverter {{ name "pv"; VA_Out 1000+100j; object metrics_collector {{ interval 5; }}; }}
    ... object metrics_collector_writer {{ filename "metrics.json"; interval 5; }}
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> data = json.load(open("inverter_metrics.json"))
    >>> sorted(data), data["10"]["pv"]
    (['10', '5', 'Metadata', 'StartTime'], [1000.0, 1000.0, 1000.0, 1000.0, 100.0, 100.0, 100.0, 100.0])
    >>> os.chdir(here)
    >>> Class.reset()

Caveats
-------

- The writer reads the metrics that the collectors computed when it
  commits; collectors created after it compute theirs later in the same
  commit, so their metrics lag one interval (gridlabd's commit order
  depends on object ranks).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The default file name has no padding; gridlabd's `%256s-%16i` pads the
   class name and the id with spaces.
2. A file that cannot be written gives a warning; gridlabd writes nothing
   and gives no message.

References
----------

- `arras-energy/gridlabd`: `module/tape/metrics_collector_writer.cpp`,
  `metrics_collector_writer.h`, `third_party/jsonCpp/jsoncpp.cpp`
- [Metrics_collector_writer class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Tape/Metrics_collector_writer.md)
  (`docs/Module/Tape/Metrics_collector_writer.md`)
"""

from typing import Any

from ._base import TapeClass, prop
from ._common import TS_NEVER, gl_error, gl_warning, get_state, set_state, strtime, to_double, to_timestamp
from ._json import styled
from .metrics_collector import state as collector_state

def _meta(items:list[tuple[str,str]]) -> dict[str,Any]:
    return {key: {"index": index, "units": unit} for index, (key, unit) in enumerate(items)}

METER_METADATA = _meta([("real_power_min", "W"), ("real_power_max", "W"), ("real_power_avg", "W"),
    ("real_power_median", "W"), ("reactive_power_min", "VAR"), ("reactive_power_max", "VAR"),
    ("reactive_power_avg", "VAR"), ("reactive_power_median", "VAR"), ("real_energy", "Wh"),
    ("reactive_energy", "VARh"), ("bill", "USD"), ("voltage12_min", "V"), ("voltage12_max", "V"),
    ("voltage12_avg", "V"), ("voltage_min", "V"), ("voltage_max", "V"), ("voltage_avg", "V"),
    ("voltage_unbalance_min", "V"), ("voltage_unbalance_max", "V"), ("voltage_unbalance_avg", "V"),
    ("above_RangeA_Duration", "s"), ("above_RangeA_Count", ""), ("below_RangeA_Duration", "s"),
    ("below_RangeA_Count", ""), ("above_RangeB_Duration", "s"), ("above_RangeB_Count", ""),
    ("below_RangeB_Duration", "s"), ("below_RangeB_Count", ""), ("below_10_percent_NormVol_Duration", "s"),
    ("below_10_percent_NormVol_Count", "")])
"""Metadata of the billing meter metrics"""

HOUSE_METADATA = _meta([(f"total_load_{x}", "kW") for x in ("min", "max", "avg", "median")]
    + [(f"hvac_load_{x}", "kW") for x in ("min", "max", "avg", "median")]
    + [(f"air_temperature_{x}", "degF") for x in ("min", "max", "avg", "median")]
    + [("air_temperature_deviation_cooling", "degF"), ("air_temperature_deviation_heating", "degF")]
    + [(f"waterheater_load_{x}", "kW") for x in ("min", "max", "avg", "median")])
"""Metadata of the house metrics"""

INVERTER_METADATA = _meta([(f"real_power_{x}", "W") for x in ("min", "max", "avg", "median")]
    + [(f"reactive_power_{x}", "VAR") for x in ("min", "max", "avg", "median")])
"""Metadata of the inverter metrics"""

COUNT_METADATA = _meta([("operation_count", "")])
"""Metadata of the capacitor and regulator metrics"""

FEEDER_METADATA = _meta([(f"real_power_{x}", "W") for x in ("min", "max", "avg", "median")]
    + [(f"reactive_power_{x}", "VAR") for x in ("min", "max", "avg", "median")]
    + [("real_energy", "Wh"), ("reactive_energy", "VARh")]
    + [(f"real_power_losses_{x}", "W") for x in ("min", "max", "avg", "median")]
    + [(f"reactive_power_losses_{x}", "VAR") for x in ("min", "max", "avg", "median")])
"""Metadata of the feeder metrics"""

DOCUMENTS = (("billing_meter", METER_METADATA), ("house", HOUSE_METADATA), ("inverter", INVERTER_METADATA),
    ("capacitor", COUNT_METADATA), ("regulator", COUNT_METADATA), ("substation", FEEDER_METADATA))
"""Output documents (file prefix, metadata)"""

class WriterState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State of a metrics collector writer between handler calls"""

    def __init__(self):
        self.interval = 0
        self.start = 0
        self.last_write = 0
        self.next_write = 0
        self.final_write = TS_NEVER
        self.interval_write = False
        self.collectors: list[str] = []
        self.documents: dict[str,dict[str,Any]] = {}
        self.files: dict[str,str] = {}

def state(model:Any, name:str) -> WriterState:
    """State of a writer, created on first use"""
    st = get_state(model, name)
    if st is None:
        st = WriterState()
        set_state(model, name, st)
    return st

class MetricsCollectorWriter(TapeClass):
    """Class `metrics_collector_writer`; see the module documentation"""

    NAME = "metrics_collector_writer"
    PASSCONFIG = "POSTTOPDOWN"
    PROPERTIES = (
        ("filename", "char1024", prop("the JSON formatted output file name")),
        ("interval[s]", "double", prop("Interval at which the metrics_collector_writer output is stored in JSON format")),
    )
    EVENTS = ("init", "postsync", "commit")

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool:
        """`metrics_collector_writer::init()`"""
        st = state(model, name)
        filename = model.get_property(name, "filename") or ""
        if not filename:
            filename = f"{cls.NAME}-{model.objects[name].id}-metrics_collector_output.json"
            model.objects[name]["filename"] = filename
            gl_warning(f"metrics_collector_writer::init(): no filename defined, auto-generating '{filename}'")
        st.files = {prefix: f"{prefix}_{filename[:1000]}" for prefix, _ in DOCUMENTS}
        interval = to_double(model.get_property(name, "interval") or "0", "s")
        st.interval = int(interval)
        if st.interval <= 0:
            gl_error(f"metrics_collector_writer::init(): invalid interval of {st.interval}, must be greater than 0")
            return False
        st.collectors = [x for x in sorted(model.objects, key=lambda n: model.objects[n].id) if model.objects[x].oclass.name == "metrics_collector"]
        if not st.collectors:
            gl_error("No metrics_collector objects were found.")
            return False
        for collector in st.collectors:
            if to_double(model.get_property(collector, "interval") or "-1", "s") != interval:
                gl_error("Currently the time interval of the metrics_collector should be the same as the metrics_collector_writer")
                return False
        st.start = st.last_write = t
        st.next_write = t + st.interval
        stop = model.globals.get("stoptime") or "NEVER"
        st.final_write = TS_NEVER if stop in ("NEVER", "") else to_timestamp(model, stop)
        start = strtime(model, t)
        st.documents = {prefix: {"StartTime": start, "Metadata": meta} for prefix, meta in DOCUMENTS}
        return True

    @classmethod
    def postsync(cls, model:Any, name:str, t1:int) -> int: # pylint: disable=unused-argument
        """`metrics_collector_writer::postsync()`"""
        st = state(model, name)
        if st.next_write <= t1:
            st.interval_write = True
            st.last_write = t1
            st.next_write = t1 + st.interval
        return TS_NEVER

    @classmethod
    def commit(cls, model:Any, name:str, t1:int) -> int|None:
        """`metrics_collector_writer::commit()`"""
        st = state(model, name)
        if st.interval_write:
            cls.write(model, st, t1)
            st.interval_write = False
        return None

    @classmethod
    def write(cls, model:Any, st:WriterState, t1:int) -> None:
        """`metrics_collector_writer::write_line()`"""
        groups: dict[str,dict[str,Any]] = {prefix: {} for prefix, _ in DOCUMENTS}
        for collector in st.collectors:
            cst = collector_state(model, collector)
            metrics, key = cst.metrics, cst.parent_name
            if cst.kind in ("triplex_meter", "meter"):
                groups["billing_meter"][key] = list(metrics)
            elif cst.kind == "house":
                house = groups["house"].setdefault(key, [0.0]*18)
                house[0:14] = [metrics[i] for i in (4, 5, 6, 7, 0, 1, 2, 3, 8, 9, 10, 11, 12, 13)]
            elif cst.kind == "waterheater":
                house = groups["house"].setdefault(key, [0.0]*18)
                house[14:18] = metrics[0:4]
            elif cst.kind == "inverter":
                groups["inverter"][key] = list(metrics)
            elif cst.kind == "capacitor":
                groups["capacitor"][key] = list(metrics)
            elif cst.kind == "regulator":
                groups["regulator"][key] = list(metrics)
            else:
                groups["substation"][key] = list(metrics)
        stamp = str(t1 - st.start)
        for prefix, _ in DOCUMENTS:
            st.documents[prefix][stamp] = groups[prefix]
        if st.final_write <= t1:
            for prefix, _ in DOCUMENTS:
                try:
                    with open(st.files[prefix], "w", encoding="utf-8") as out:
                        out.write(styled(st.documents[prefix]) + "\n")
                except OSError as err:
                    gl_warning(f"metrics_collector_writer: unable to write '{st.files[prefix]}' ({err.strerror})")
