# pylint: disable=line-too-long
"""Class `regulator_configuration`: the settings of a voltage regulator

Syntax
------

    object regulator_configuration {
        connect_type {WYE_WYE,OPEN_DELTA_ABBC,OPEN_DELTA_BCAC,OPEN_DELTA_CABA,CLOSED_DELTA};
        band_center <real> V;
        band_width <real> V;
        time_delay <real> s;
        dwell_time <real> s;
        raise_taps <integer>;
        lower_taps <integer>;
        current_transducer_ratio <real> pu;
        power_transducer_ratio <real> pu;
        compensator_r_setting_A <real> V;   // also _B, _C, and compensator_x_setting_A/B/C
        CT_phase {A,B,C};
        PT_phase {A,B,C};
        regulation <real> %;
        control_level {INDIVIDUAL,BANK};
        Control {MANUAL,OUTPUT_VOLTAGE,LINE_DROP_COMP,REMOTE_NODE};
        reverse_flow_control {LOCK_NONE,LOCK_NEUTRAL,LOCK_CURRENT_POSITION};
        Type {A,B};
        tap_pos_A <integer>;                // also tap_pos_B, tap_pos_C
    }

Description
-----------

A library object that `regulator`, not ported yet, refers to. When it
initializes, it is expected to fail when:

1. `Control` is `LINE_DROP_COMP` and `power_transducer_ratio` is 0;
2. `control_level` is `BANK` and `CT_phase` or `PT_phase` is not exactly
   one phase;
3. `raise_taps` or `lower_taps` is not positive;
4. `Control` is not `MANUAL` and `regulation` is 0, or `connect_type` is
   not `WYE_WYE` (with a warning when `band_width` is 0);
5. `connect_type` is not `WYE_WYE`;
6. the solver method is `GS`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A `connect_type` other than `WYE_WYE` fails with every solver method;
   gridlabd allows it with FBS, which this module solves with NR.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/regulator_configuration.cpp`,
  `regulator_configuration.h`
"""

from typing import Any

from ._base import prop, keywords
from ._common import PHASE_A, PHASE_B, PHASE_C, SM_GS, g, get_double, get_int, msg, PowerflowError
from .powerflow_library import LibraryObject

UNKNOWN, WYE_WYE, OPEN_DELTA_ABBC, OPEN_DELTA_BCAC, OPEN_DELTA_CABA, CLOSED_DELTA = range(6)
"""`connect_type` values"""

MANUAL, OUTPUT_VOLTAGE, REMOTE_NODE, LINE_DROP_COMP = 1, 2, 3, 4
"""`Control` values"""

INDIVIDUAL, BANK = 1, 2
"""`control_level` values"""

_PHASES = keywords(("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C))

class RegulatorConfiguration(LibraryObject):
    """Behavior of class `regulator_configuration`"""

    NAME = "regulator_configuration"
    PROPERTIES = (
        ("connect_type", "enumeration", prop("Designation of connection style", "UNKNOWN", flags="REQUIRED", keywords=keywords(
            ("UNKNOWN", UNKNOWN), ("WYE_WYE", WYE_WYE), ("OPEN_DELTA_ABBC", OPEN_DELTA_ABBC), ("OPEN_DELTA_BCAC", OPEN_DELTA_BCAC),
            ("OPEN_DELTA_CABA", OPEN_DELTA_CABA), ("CLOSED_DELTA", CLOSED_DELTA)))),
        ("band_center[V]", "double", prop("band center setting of regulator control", "0 V")),
        ("band_width[V]", "double", prop("band width setting of regulator control", "0 V")),
        ("time_delay[s]", "double", prop("mechanical time delay between tap changes", "0 s")),
        ("dwell_time[s]", "double", prop("time delay before a control action of regulator control", "0 s")),
        ("raise_taps", "int16", prop("number of regulator raise taps, or the maximum raise voltage tap position", "0")),
        ("lower_taps", "int16", prop("number of regulator lower taps, or the minimum lower voltage tap position", "0")),
        ("current_transducer_ratio[pu]", "double", prop("primary rating of current transformer", "0 pu")),
        ("power_transducer_ratio[pu]", "double", prop("potential transformer rating", "0 pu")),
        *((f"compensator_{rx}_setting_{x}[V]", "double", prop(f"Line Drop Compensation {rx.upper()} setting of regulator control (in volts) on Phase {x}", "0 V"))
            for rx in "rx" for x in "ABC"),
        ("CT_phase", "set", prop("phase(s) monitored by CT", "ABC", keywords=_PHASES)),
        ("PT_phase", "set", prop("phase(s) monitored by PT", "ABC", keywords=_PHASES)),
        ("regulation[%]", "double", prop("regulation of voltage regulator in %", "0 %")),
        ("control_level", "enumeration", prop("Designates whether control is on per-phase or banked level", "INDIVIDUAL",
            keywords=keywords(("INDIVIDUAL", INDIVIDUAL), ("BANK", BANK)))),
        ("Control", "enumeration", prop("Type of control used for regulating voltage", "MANUAL", keywords=keywords(
            ("MANUAL", MANUAL), ("OUTPUT_VOLTAGE", OUTPUT_VOLTAGE), ("LINE_DROP_COMP", LINE_DROP_COMP), ("REMOTE_NODE", REMOTE_NODE)))),
        ("reverse_flow_control", "enumeration", prop("Type of control used when power is flowing in reverse through the regulator", "LOCK_NONE",
            keywords=keywords(("LOCK_NONE", 0), ("LOCK_NEUTRAL", 1), ("LOCK_CURRENT_POSITION", 2)))),
        ("Type", "enumeration", prop("Defines regulator type", "B", keywords=keywords(("A", 1), ("B", 2)))),
        ("tap_pos_A", "int16", prop("initial tap position of phase A", "999")),
        ("tap_pos_B", "int16", prop("initial tap position of phase B", "999")),
        ("tap_pos_C", "int16", prop("initial tap position of phase C", "999")),
    )

    @classmethod
    def check(cls, model:Any, name:str) -> None:
        control = get_int(model, name, "Control")
        if control == LINE_DROP_COMP and get_double(model, name, "power_transducer_ratio") == 0:
            raise PowerflowError("power_transducer_ratio must be set as a non-zero value when operating in LINE_DROP_COMP mode")
        if get_int(model, name, "control_level") == BANK:
            if get_int(model, name, "CT_phase") not in (1, 2, 4):
                raise PowerflowError("There are too many CT_phases specified for a BANK control_level (or it wasn't specified).  Should only be one phase monitored.")
            if get_int(model, name, "PT_phase") not in (1, 2, 4):
                raise PowerflowError("There are too many PT_phases specified for a BANK control_level (or it wasn't specified).  Should only be one phase monitored.")
        if get_int(model, name, "raise_taps") <= 0 or get_int(model, name, "lower_taps") <= 0:
            raise PowerflowError("raise and lower taps must be specified to non-zero numbers")
        connect = get_int(model, name, "connect_type")
        if control != MANUAL:
            if get_double(model, name, "band_width") == 0:
                msg(model, name).warning("band_width is set to zero in automatic control. May cause oscillations.")
            if get_double(model, name, "regulation") == 0:
                raise PowerflowError("regulation must be set to a non-zero number when operating in an automatic controlled mode.")
            if connect != WYE_WYE:
                raise PowerflowError("At this time, only WYE_WYE regulators are supported in automatic control modes.")
        if connect != WYE_WYE:
            raise PowerflowError("Only WYE_WYE regulator connections are fully supported in FBS & NR solvers at this time.")
        if g(model, "solver_method") == SM_GS:
            raise PowerflowError("Regulators are not supported in the Gauss-Seidel solver method.")
