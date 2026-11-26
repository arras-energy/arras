# pylint: disable=line-too-long
"""Class `power_metrics`: IEEE 1366 reliability indices

Syntax
------

    object power_metrics {
        base_time_value <real> s;
    }

Outputs: `SAIFI`, `SAIDI`, `CAIDI`, `ASAI`, `MAIFI`, and their interval
values `SAIFI_int` ... `MAIFI_int` (over `base_time_value`).

Description
-----------

gridlabd's reliability module (`metrics` objects) drives `power_metrics`
objects: it resets them at the start of each interval and asks them to
compute the indices from the interruptions that `fault_check` records.
The indices start at 0 (`ASAI` and `ASAI_int` at 1, full reliability) and
`base_time_value` at 60 s, as gridlabd's `create()` sets them. The object
has no initialization checks.

Caveats
-------

- The reliability module and `fault_check` are not ported, so the indices
  stay at their initial values.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/power_metrics.cpp`
"""

from ._base import prop
from .powerflow_library import PowerflowLibrary

TRL_QUALIFIED = 8
"""Technology readiness level `TRL_QUALIFIED`"""

_IEEE = "as per IEEE 1366-2003"
_INT = f"over the period specified by base_time_value {_IEEE}"

class PowerMetrics(PowerflowLibrary): # pylint: disable=too-few-public-methods
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
