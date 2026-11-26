# pylint: disable=line-too-long
"""Class `power_metrics`: IEEE 1366 reliability indices

Syntax
------

    object power_metrics {
        base_time_value <real> s;
    }

Outputs: `SAIFI`, `SAIDI`, `CAIDI`, `ASAI`, `MAIFI`, and their interval
values `SAIFI_int` ... `MAIFI_int`.

Description
-----------

gridlabd's reliability module (`metrics` objects) drives `power_metrics`
objects through the functions the class publishes, which are the class
methods here (each takes the model and the object's name):

- `calc_metrics(model, name, number_int, number_int_secondary,
  total_customers, rest_time, base_time)` (gridlabd `calc_metrics`,
  `perform_rel_calcs()`): records an interruption of `number_int`
  customers (and `number_int_secondary` momentary ones) out of
  `total_customers`, lasting `rest_time` seconds, then updates the
  indices. For an interruption longer than 300 s: SAIFI (interrupted
  customers over total customers), SAIDI (customer outage time in units of
  `base_time_value`, over total customers), CAIDI (SAIDI over SAIFI), ASAI
  (1 minus customer outage hours over customer hours in a year). Always:
  MAIFI (momentary interruptions, counted with the recloser operations of
  `extra_data`, plus the interruption itself when shorter than 300 s,
  over total customers). With no customers, the index is 0. Annual
  indices accumulate over the run; interval (`_int`) indices since the
  last interval reset;
- `reset_interval_metrics(model, name)`: checks for a `fault_check`
  object (`check_fault_check()`), then resets the interval indices (ASAI
  to 1);
- `reset_annual_metrics(model, name)`: resets the interval indices and the
  interval ASAI accumulator;
- `init_reliability(model, name, caller)`: records the calling `metrics`
  object and returns a handle to `extra_data` (the recloser operation
  count that MAIFI uses), as gridlabd returns the address of
  `Extra_PF_Data`;
- `logfile_extra(model, name)`: the text the `metrics` log file starts
  with, naming the time base of `base_time_value`.

The indices start at 0 (ASAI at 1) and `base_time_value` at 60 s, as
gridlabd's `create()` sets them. The object has no initialization checks.

Caveats
-------

- The reliability module and `fault_check` are not ported, so nothing calls
  these functions during a run, and `reset_interval_metrics()` fails as it
  does in gridlabd without a `fault_check` object.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None; the accumulators reset as gridlabd resets them (the annual reset
clears the interval ASAI accumulator, not the annual one).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/power_metrics.cpp`,
  `power_metrics.h`
- IEEE Std 1366-2003, *IEEE Guide for Electric Power Distribution
  Reliability Indices*
"""

from typing import Any

from ._base import prop
from ._common import get_double, set_double, object_state, objects_of, msg, PowerflowError
from .powerflow_library import PowerflowLibrary

TRL_QUALIFIED = 8
"""Technology readiness level `TRL_QUALIFIED`"""

MOMENTARY = 300
"""Longest momentary interruption (s), IEEE 1366"""

_IEEE = "as per IEEE 1366-2003"
_INT = f"over the period specified by base_time_value {_IEEE}"

class ExtraData: # pylint: disable=too-few-public-methods
    """Handle to a `power_metrics` object's `Extra_PF_Data` (the recloser
    operation count), as `init_reliability()` returns it"""

    def __init__(self, state:dict[str,Any]):
        self._state = state

    @property
    def value(self) -> float:
        """The value"""
        return self._state["extra"]

    @value.setter
    def value(self, value:float) -> None:
        self._state["extra"] = float(value)

class PowerMetrics(PowerflowLibrary):
    """Behavior of class `power_metrics`"""

    NAME = "power_metrics"
    TRL = TRL_QUALIFIED
    PROPERTIES = (
        ("SAIFI", "double", prop(f"Displays annual SAIFI values {_IEEE}", "0")),
        ("SAIFI_int", "double", prop(f"Displays SAIFI values {_INT}", "0")),
        ("SAIDI", "double", prop(f"Displays annual SAIDI values {_IEEE}", "0")),
        ("SAIDI_int", "double", prop(f"Displays SAIDI values {_INT}", "0")),
        ("CAIDI", "double", prop(f"Displays annual CAIDI values {_IEEE}", "0")),
        ("CAIDI_int", "double", prop(f"Displays SAIDI values {_INT}", "0")),
        ("ASAI", "double", prop(f"Displays annual AISI values {_IEEE}", "1")),
        ("ASAI_int", "double", prop(f"Displays AISI values {_INT}", "1")),
        ("MAIFI", "double", prop(f"Displays annual MAIFI values {_IEEE}", "0")),
        ("MAIFI_int", "double", prop(f"Displays MAIFI values {_INT}", "0")),
        ("base_time_value[s]", "double", prop("time period over which _int values are claculated", "60 s")),
    )

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """Accumulators of an object (gridlabd's private members)"""
        state = object_state(model, name)
        for key in ("SAIFI_num", "SAIDI_num", "ASAI_num", "MAIFI_num", "SAIFI_num_int", "SAIDI_num_int", "ASAI_num_int", "MAIFI_num_int", "extra"):
            state.setdefault(key, 0.0)
        return state

    @classmethod
    def calc_metrics(cls, model:Any, name:str, number_int:int, number_int_secondary:int, total_customers:int, rest_time:int, base_time:int) -> int: # pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument,too-many-locals
        """`calc_metrics` (`perform_rel_calcs()`); returns 1"""
        state = cls.state(model, name)
        out = {}
        def put(key:str, value:float) -> None:
            out[key] = value
        total = int(total_customers)
        interrupted = int(number_int)
        length = int(rest_time)
        normalized = length/get_double(model, name, "base_time_value")
        if length > MOMENTARY:
            if total != 0:
                state["SAIFI_num"] += interrupted
                state["SAIFI_num_int"] += interrupted
                put("SAIFI", state["SAIFI_num"]/total)
                put("SAIFI_int", state["SAIFI_num_int"]/total)
                state["SAIDI_num"] += normalized*interrupted
                state["SAIDI_num_int"] += normalized*interrupted
                put("SAIDI", state["SAIDI_num"]/total)
                put("SAIDI_int", state["SAIDI_num_int"]/total)
            else:
                put("SAIFI", 0.0)
                put("SAIFI_int", 0.0)
                put("SAIDI", 0.0)
                put("SAIDI_int", 0.0)
            for suffix in ("", "_int"):
                saifi = out[f"SAIFI{suffix}"]
                put(f"CAIDI{suffix}", out[f"SAIDI{suffix}"]/saifi if saifi != 0 else 0.0)
            if total != 0:
                hours = total*8760.0
                state["ASAI_num"] += length*interrupted/3600.0
                state["ASAI_num_int"] += length*interrupted/3600.0
                put("ASAI", (hours - state["ASAI_num"])/hours)
                put("ASAI_int", (hours - state["ASAI_num_int"])/hours)
            else:
                put("ASAI", 0.0)
                put("ASAI_int", 0.0)
        if total != 0:
            momentary = state["extra"]*int(number_int_secondary)
            state["MAIFI_num"] += momentary
            state["MAIFI_num_int"] += momentary
            if length < MOMENTARY:
                state["MAIFI_num"] += interrupted
                state["MAIFI_num_int"] += interrupted
            put("MAIFI", state["MAIFI_num"]/total)
            put("MAIFI_int", state["MAIFI_num_int"]/total)
        else:
            put("MAIFI", 0.0)
            put("MAIFI_int", 0.0)
        for key, value in out.items():
            set_double(model, name, key, value)
        return 1

    @classmethod
    def reset_metrics_variables(cls, model:Any, name:str, annual:bool) -> None:
        """`reset_metrics_variables()`"""
        state = cls.state(model, name)
        for key in ("SAIFI_num_int", "SAIDI_num_int", "MAIFI_num_int"):
            state[key] = 0.0
        for key, value in (("SAIFI_int", 0.0), ("SAIDI_int", 0.0), ("CAIDI_int", 0.0), ("ASAI_int", 1.0), ("MAIFI_int", 0.0)):
            set_double(model, name, key, value)
        if annual:
            state["ASAI_num_int"] = 0.0

    @classmethod
    def check_fault_check(cls, model:Any, name:str) -> None:
        """`check_fault_check()`: a `fault_check` object is required
        (raises `PowerflowError`)"""
        if not objects_of(model, "fault_check"):
            raise PowerflowError("power_metrics failed to map fault_check object!")
        msg(model, name).verbose("fault_check object found")

    @classmethod
    def reset_interval_metrics(cls, model:Any, name:str) -> int:
        """`reset_interval_metrics`; returns 1"""
        cls.check_fault_check(model, name)
        cls.reset_metrics_variables(model, name, False)
        return 1

    @classmethod
    def reset_annual_metrics(cls, model:Any, name:str) -> int:
        """`reset_annual_metrics`; returns 1"""
        cls.reset_metrics_variables(model, name, True)
        return 1

    @classmethod
    def init_reliability(cls, model:Any, name:str, caller:str|None) -> ExtraData:
        """`init_reliability`: records the calling `metrics` object; returns
        the handle to the extra data"""
        state = cls.state(model, name)
        state["rel_metrics"] = caller
        return ExtraData(state)

    @classmethod
    def logfile_extra(cls, model:Any, name:str) -> str:
        """`logfile_extra`: the time base line of the `metrics` log file"""
        value = get_double(model, name, "base_time_value")
        bases = {1.0: "1-second base (outage-seconds)", 60.0: "1-minute base (outage-minutes)", 3600.0: "1-hour base (outage-hours)",
            86400.0: "1-day base (outage-days)", 31536000.0: "1-year base (outage-years)"}
        if value in bases:
            return f"1366 metrics based around {bases[value]}\n\n"
        return f"1366 metrics uses time base of {value:.0f} seconds\n\n"
