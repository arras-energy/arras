# pylint: disable=line-too-long,too-many-lines
"""Class `inverter`: a DC to AC inverter

Syntax
------

    object inverter {
        parent <meter>|<triplex_meter>; // required
        inverter_type PWM|SIX_PULSE|TWELVE_PULSE|FOUR_QUADRANT;
        generator_mode CONSTANT_PF;     // legacy types
        generator_status ONLINE|OFFLINE;
        four_quadrant_control_mode CONSTANT_PF|CONSTANT_PQ|NONE; // FOUR_QUADRANT
        power_factor <real>;
        P_Out <real> VA;                // CONSTANT_PQ
        Q_Out <real> VAr;               // CONSTANT_PQ
        rated_power <real> VA;          // per phase
        inverter_efficiency <real>;
        use_multipoint_efficiency TRUE|FALSE;
        inverter_manufacturer NONE|FRONIUS|SMA|XANTREX;
        maximum_dc_power <real>;        // multipoint efficiency model
        maximum_dc_voltage <real>;
        minimum_dc_power <real>;
        c_0 <real>; c_1 <real>; c_2 <real>; c_3 <real>;
    }

Arguments
---------

See the published properties (`Inverter.PROPERTIES`); the main inputs are
listed above. A child `solar` object writes the DC input `V_In` and `I_In`;
they can also be set in the model.

Description
-----------

Given an `inverter` object whose parent is a powerflow `meter` or
`triplex_meter`, the class is expected to satisfy:

1. At init, the inverter takes its parent's `phases`; an unset
   `inverter_type` (or `TWO_PULSE`, which has the same value) becomes
   `PWM`, an unset `generator_status` `ONLINE`, and, for the legacy types,
   `generator_mode UNKNOWN` becomes `CONSTANT_PF`, each with gridlabd's
   warning. An unset `inverter_efficiency` gives 0.8 (six and twelve
   pulse) or 0.9 (PWM and four-quadrant). For `FOUR_QUADRANT`, an unset
   `rated_power` (per phase) is 25 kVA, and the inverter's maximum output
   is `rated_power` times the number of phases (for the multipoint
   efficiency model, the manufacturer's maximum).
2. The legacy types in `CONSTANT_PF` mode convert the DC power `VA_In =
   V_In*conj(I_In)` with the efficiency (or the multipoint efficiency
   curve) to an AC output `VA_Out`, split equally among the phases at
   `power_factor`. The output currents `conj(power/voltage)`, at the
   parent's voltages of the last solution, are posted to the parent's
   `current_X` (or `current_12`) accumulators in the bottom-up pass and
   removed in the post-top-down pass, so the powerflow solution of the
   same pass includes them.
3. `FOUR_QUADRANT` in `CONSTANT_PF` gives `VA_Out` with the efficiency
   weighted DC power and `power_factor` (negative is leading); in
   `CONSTANT_PQ` it gives `P_Out + jQ_Out` limited to the maximum output,
   reactive power first, and refuses charging a full battery or
   discharging one at its reserve (`battery_soc`). Outputs above the
   maximum are reduced to it (`excess_input_power` holds the difference).
   The output is posted to the parent's `power_X` (or `power_12`)
   accumulators as a negative load, and removed after the solution.
4. An `OFFLINE` inverter posts nothing and its outputs are 0; a parent out
   of service (`service_status OUT_OF_SERVICE`) gets nothing.

Examples
--------

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-06-01 12:00:00 UTC"; stoptime "2020-06-01 12:00:00 UTC"; }
    ... module powerflow;
    ... module generators;
    ... object node { name n1; phases ABCN; nominal_voltage 2401.7771; bustype SWING; }
    ... object link { name l1; from n1; to m1; phases ABCN; }
    ... object meter { name m1; phases ABCN; nominal_voltage 2401.7771; }
    ... object inverter {
    ...     name inv;
    ...     parent m1;
    ...     generator_status ONLINE;
    ...     inverter_type FOUR_QUADRANT;
    ...     four_quadrant_control_mode CONSTANT_PQ;
    ...     inverter_efficiency 0.95;
    ...     rated_power 10 kVA;
    ...     P_Out 15 kW;
    ...     Q_Out 5 kVAr;
    ...     V_In 400 V;
    ...     I_In 50 A;
    ... }
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> m.get_property("inv", "VA_Out")
    '15000.0+5000.0j'
    >>> from pypower._common import get_complex
    >>> S = get_complex(m, "m1", "measured_power")
    >>> round(S.real), round(S.imag)
    (-15000, -5000)
    >>> Class.reset()

Caveats
-------

- Not ported yet: the four-quadrant modes `VOLT_VAR`, `VOLT_VAR_FREQ_PWR`,
  `LOAD_FOLLOWING`, `GROUP_LOAD_FOLLOWING`, and `VOLTAGE_SOURCE`,
  power-factor regulation (`pf_reg`), the IEEE 1547 checks
  (`enable_1547_checks`), and deltamode with
  `generators::enable_subsecond_models`. Each fails at init with a message
  that names it. Their properties are published, so models that set them
  load.
- The legacy `CONSTANT_PQ`, `CONSTANT_V`, and `SUPPLY_DRIVEN` modes fail
  in the bottom-up pass with gridlabd's "not supported at this time"
  errors.
- `phaseA_I_Out` ... `phaseC_I_Out` are published in volts, as in
  gridlabd.
- The class functions that gridlabd publishes for deltamode
  (`preupdate_gen_object`, `interupdate_gen_object`,
  `postupdate_gen_object`) and for the NR current injection
  (`current_injection_update`) are not published.
- The line losses of gridlabd's `power_electronics` base class are
  placeholders that return 0 there too, so the internal and frequency
  loss factors are 1.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `VSI_Rfilter` and `VSI_Xfilter` are separate values. gridlabd publishes
   the `double` members `Rfilter` and `Xfilter` as `complex`, so
   `VSI_Rfilter` shows `Rfilter + jXfilter` and setting it overwrites
   `Xfilter`. The defaults shown are gridlabd's (`0.03+0.3j`, `0.3+0j`).
   Neither is used until the `VOLTAGE_SOURCE` mode is ported.
2. A parent is in service unless its `service_status` is
   `OUT_OF_SERVICE`. gridlabd compares the stored value with 1, which is
   `IN_SERVICE` for a `meter`; `arras` publishes `triplex_meter`'s
   keywords with other values (`IN_SERVICE` is 0), so the keyword is
   compared instead.
3. An `OFFLINE` legacy inverter clears the currents it posted last. gridlabd
   clears only the four-quadrant powers, so its `postsync()` keeps
   subtracting the last legacy currents from the parent's accumulators at
   every pass while the inverter is offline.

gridlabd's quirks are kept: a complex compared with a number compares
its magnitude (so a negative DC input still gives a positive
four-quadrant output sign test), `TWO_PULSE` becomes `PWM`, and the
battery power term (`power_A` ... `power_C`) is added to the four-quadrant
efficiency-weighted input.

References
----------

- `arras-energy/gridlabd`: `module/generators/inverter.cpp`, `inverter.h`,
  `power_electronics.cpp`, and the autotests in
  `module/generators/autotest/`; `source/complex.h` (comparison operators)
- [Inverter](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Generators/Inverter.md)
"""

import math
from typing import Any

from ._common import (register, MODULE, TS_NEVER, INIT_DEFER, UNKNOWN, ONLINE, OFFLINE,
    CONSTANT_V, CONSTANT_PQ, CONSTANT_PF, SUPPLY_DRIVEN, OF_DELTAMODE, Throw,
    keywords, prop, msg, object_state, object_flags, isa, ref, label, object_id,
    get_double, get_complex, get_int, get_text, set_double, set_complex, set_int, post, cacos, fdiv, csqrt)

TWO_PULSE, SIX_PULSE, TWELVE_PULSE, PWM, FOUR_QUADRANT = 0, 1, 2, 3, 4
"""`inverter_type` values"""

FQM_NONE, FQM_CONSTANT_PQ, FQM_CONSTANT_PF, FQM_CONSTANT_V, FQM_VOLT_VAR, FQM_LOAD_FOLLOWING, \
    FQM_GROUP_LF, FQM_VOLT_VAR_FREQ_PWR, FQM_VSI = 0, 1, 2, 3, 4, 5, 6, 7, 8
"""`four_quadrant_control_mode` values"""

INCLUDED, EXCLUDED, INCLUDED_ALT = 1, 2, 3
"""`pf_reg` values"""

NONE, FRONIUS, SMA, XANTREX = 0, 1, 2, 3
"""`inverter_manufacturer` values"""

MANUFACTURERS = {
    FRONIUS: {"p_dco": 2879, "v_dco": 277, "p_so": 27.9, "c_o": -1.009e-5, "c_1": -1.367e-5, "c_2": -3.587e-5, "c_3": -3.421e-3, "p_max": 2700},
    SMA: {"p_dco": 2694, "v_dco": 302, "p_so": 20.7, "c_o": -1.545e-5, "c_1": 6.525e-5, "c_2": 2.836e-3, "c_3": -3.058e-4, "p_max": 2500},
    XANTREX: {"p_dco": 4022, "v_dco": 266, "p_so": 24.1, "c_o": -8.425e-6, "c_1": 8.590e-6, "c_2": 7.76e-4, "c_3": -5.278e-4, "p_max": 3800},
}
"""CEC multipoint efficiency parameters of the manufacturer presets"""

MULTIPOINT = (("p_dco", "maximum_dc_power"), ("v_dco", "maximum_dc_voltage"), ("p_so", "minimum_dc_power"),
    ("c_o", "c_0"), ("c_1", "c_1"), ("c_2", "c_2"), ("c_3", "c_3"))
"""Members of the multipoint efficiency model and their properties"""

NOT_PORTED = {FQM_VOLT_VAR: "VOLT_VAR", FQM_VOLT_VAR_FREQ_PWR: "VOLT_VAR_FREQ_PWR",
    FQM_LOAD_FOLLOWING: "LOAD_FOLLOWING", FQM_GROUP_LF: "GROUP_LOAD_FOLLOWING", FQM_VSI: "VOLTAGE_SOURCE"}
"""Four-quadrant control modes that are not ported yet"""

PHASE_BITS = (0x01, 0x02, 0x04)

def _d(description:str, default:str|None=None) -> dict[str,Any]:
    return prop(description, default)

def _phase_props() -> tuple[tuple[str,str,dict[str,Any]],...]:
    out: list[tuple[str,str,dict[str,Any]]] = []
    a3 = "on A phase in three-phase system; 240-V connection on a triplex system"
    for kind, unit, what in (("V_Out", "V", "AC voltage"), ("I_Out", "V", "AC current")):
        out.append((f"phaseA_{kind}[{unit}]", "complex", _d(f"{what} {a3}")))
        out.append((f"phaseB_{kind}[{unit}]", "complex", _d(f"{what} on B phase in three-phase system")))
        out.append((f"phaseC_{kind}[{unit}]", "complex", _d(f"{what} on C phase in three-phase system")))
    for kind in ("power_{}", "curr_VA_out_{}", "prev_VA_out_{}"):
        out.append((f"{kind.format('A')}[VA]", "complex", _d(f"AC power {a3}")))
        out.append((f"{kind.format('B')}[VA]", "complex", _d("AC power on B phase in three-phase system")))
        out.append((f"{kind.format('C')}[VA]", "complex", _d("AC power on C phase in three-phase system")))
    return tuple(out)

def _pi_props() -> tuple[tuple[str,str,dict[str,Any]],...]:
    out: list[tuple[str,str,dict[str,Any]]] = []
    names = (("ep", "The real current error"), ("eq", "The reactive current error"),
        ("delta_ep", "The change in real current error"), ("delta_eq", "The change in reactive current error"),
        ("md", "The d-axis current modulation"), ("mq", "The q-axis current modulation"),
        ("delta_md", "The change in d-axis current modulation"), ("delta_mq", "The change in q-axis current modulation"))
    for key, what in names:
        out.append((f"{key}A", "double", _d(f"DELTAMODE: {what} for phase A or triplex phase.")))
        out.append((f"{key}B", "double", _d(f"DELTAMODE: {what} for phase B.")))
        out.append((f"{key}C", "double", _d(f"DELTAMODE: {what} for phase C.")))
    out.append(("IdqA", "complex", _d("DELTAMODE: The dq-axis current for phase A or triplex phase.")))
    out.append(("IdqB", "complex", _d("DELTAMODE: The dq-axis current for phase B.")))
    out.append(("IdqC", "complex", _d("DELTAMODE: The dq-axis current for phase C.")))
    return tuple(out)

TRIP = keywords(("NONE", 0), ("OVER_FREQUENCY_HIGH", 1), ("OVER_FREQUENCY_LOW", 2), ("UNDER_FREQUENCY_HIGH", 3),
    ("UNDER_FREQUENCY_LOW", 4), ("UNDER_VOLTAGE_LOW", 5), ("UNDER_VOLTAGE_MID", 6), ("UNDER_VOLTAGE_HIGH", 7),
    ("OVER_VOLTAGE_LOW", 8), ("OVER_VOLTAGE_HIGH", 9))
"""`IEEE_1547_trip_method` keywords"""

FQ = "FOUR QUADRANT MODEL: "
MP = "MULTIPOINT EFFICIENCY MODEL: "
DM = "DELTAMODE: "

class Inverter: # pylint: disable=too-many-public-methods
    """Class `inverter`; see the module documentation"""

    NAME = "inverter"
    """gridlabd class name"""

    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|AUTOLOCK"
    """Pass configuration"""

    EVENTS = ("init", "presync", "sync", "postsync")
    """Event handlers of the class"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = (
        ("inverter_type", "enumeration", prop("LEGACY MODEL: Sets efficiencies and other parameters; if using four_quadrant_control_mode, set this to FOUR_QUADRANT",
            keywords=keywords(("TWO_PULSE", TWO_PULSE), ("SIX_PULSE", SIX_PULSE), ("TWELVE_PULSE", TWELVE_PULSE), ("PWM", PWM), ("FOUR_QUADRANT", FOUR_QUADRANT)))),
        ("four_quadrant_control_mode", "enumeration", prop(f"{FQ}Activates various control modes", "CONSTANT_PF",
            keywords=keywords(("NONE", FQM_NONE), ("CONSTANT_PQ", FQM_CONSTANT_PQ), ("CONSTANT_PF", FQM_CONSTANT_PF), ("VOLT_VAR", FQM_VOLT_VAR),
                ("VOLT_VAR_FREQ_PWR", FQM_VOLT_VAR_FREQ_PWR), ("LOAD_FOLLOWING", FQM_LOAD_FOLLOWING), ("GROUP_LOAD_FOLLOWING", FQM_GROUP_LF), ("VOLTAGE_SOURCE", FQM_VSI)))),
        ("pf_reg", "enumeration", prop("Activate (or not) power factor regulation in four_quadrant_control_mode", "EXCLUDED",
            keywords=keywords(("INCLUDED", INCLUDED), ("INCLUDED_ALT", INCLUDED_ALT), ("EXCLUDED", EXCLUDED)))),
        ("generator_status", "enumeration", prop("describes whether the generator is online or offline", keywords=keywords(("OFFLINE", OFFLINE), ("ONLINE", ONLINE)))),
        ("generator_mode", "enumeration", prop("LEGACY MODEL: Selects generator control mode when using legacy model; in non-legacy models, this should be SUPPLY_DRIVEN.", "UNKNOWN",
            keywords=keywords(("UNKNOWN", UNKNOWN), ("CONSTANT_V", CONSTANT_V), ("CONSTANT_PQ", CONSTANT_PQ), ("CONSTANT_PF", CONSTANT_PF), ("SUPPLY_DRIVEN", SUPPLY_DRIVEN)))),
        ("inverter_convergence_criterion", "double", _d("The maximum change in error threshold for exitting deltamode.", "0.001")),
        ("V_In[V]", "complex", _d("DC voltage")),
        ("I_In[A]", "complex", _d("DC current")),
        ("VA_In[VA]", "complex", _d("DC power")),
        ("VA_Out[VA]", "complex", _d("AC power")),
        ("Vdc[V]", "double", _d("LEGACY MODEL: DC voltage", "480 V")),
        *_phase_props(),
        ("P_Out[VA]", "double", _d(f"{FQ}Scheduled real power out in CONSTANT_PQ control mode", "0 VA")),
        ("Q_Out[VAr]", "double", _d(f"{FQ}Schedule reactive power out in CONSTANT_PQ control mode", "0 VAr")),
        ("power_in[W]", "double", _d("LEGACY MODEL: No longer used")),
        ("rated_power[VA]", "double", _d(f"{FQ}The rated power of the inverter")),
        ("rated_battery_power[W]", "double", _d(f"{FQ}The rated power of battery when battery is attached")),
        ("inverter_efficiency", "double", _d(f"{FQ}The efficiency of the inverter")),
        ("battery_soc[pu]", "double", _d(f"{FQ}The state of charge of an attached battery", "-1 pu")),
        ("soc_reserve[pu]", "double", _d(f"{FQ}The reserve state of charge of an attached battery for islanding cases")),
        ("power_factor[unit]", "double", _d(f"{FQ}The power factor used for CONSTANT_PF control mode", "1 unit")),
        ("islanded_state", "bool", _d(f"{FQ}Boolean used to let control modes to act under island conditions", "FALSE")),
        ("nominal_frequency[Hz]", "double", prop(default="60 Hz")),
        ("Pref", "double", _d(f"{DM}The real power reference.")),
        ("Qref", "double", _d(f"{DM}The reactive power reference.")),
        ("kpd", "double", _d(f"{DM}The d-axis integration gain for the current modulation PI controller.")),
        ("kpq", "double", _d(f"{DM}The q-axis integration gain for the current modulation PI controller.")),
        ("kid", "double", _d(f"{DM}The d-axis proportional gain for the current modulation PI controller.")),
        ("kiq", "double", _d(f"{DM}The q-axis proportional gain for the current modulation PI controller.")),
        ("kdd", "double", _d(f"{DM}The d-axis differentiator gain for the current modulation PID controller")),
        ("kdq", "double", _d(f"{DM}The q-axis differentiator gain for the current modulation PID controller")),
        *_pi_props(),
        ("Tfreq_delay", "double", _d(f"{DM}The time constant for delayed frequency seen by the inverter")),
        ("inverter_droop_fp", "bool", _d(f"{DM}Boolean used to indicate whether inverter f/p droop is included or not", "FALSE")),
        ("R_fp", "double", _d(f"{DM}The droop parameter of the f/p droop", "0.0001")),
        ("Tvol_delay", "double", _d(f"{DM}The time constant for delayed voltage seen by the inverter")),
        ("inverter_droop_vq", "bool", _d(f"{DM}Boolean used to indicate whether inverter q/v droop is included or not", "FALSE")),
        ("R_vq", "double", _d(f"{DM}The droop parameter of the v/q droop")),
        ("Tp_delay", "double", _d(f"{DM}The time constant for delayed real power seen by the VSI droop controller")),
        ("Tq_delay", "double", _d(f"{DM}The time constant for delayed reactive power seen by the VSI droop controller")),
        ("VSI_Rfilter[pu]", "complex", _d("VSI filter resistance (p.u.)", "0.03+0.3j pu")),
        ("VSI_Xfilter[pu]", "complex", _d("VSI filter inductance (p.u.)", "0.3+0j pu")),
        ("VSI_mode", "enumeration", prop("VSI MODEL: Selects VSI mode for either isochronous or droop one", "VSI_ISOCHRONOUS",
            keywords=keywords(("VSI_ISOCHRONOUS", 0), ("VSI_DROOP", 1)))),
        ("VSI_freq", "double", _d("VSI frequency", "60")),
        ("ki_Vterminal", "double", _d(f"{DM}The integrator gain for the VSI terminal voltage modulation", "0.01")),
        ("kp_Vterminal", "double", _d(f"{DM}The proportional gain for the VSI terminal voltage modulation", "0.1")),
        ("enable_ramp_rates_real", "bool", _d(f"{DM}Boolean used to indicate whether inverter ramp rate is enforced or not", "FALSE")),
        ("max_ramp_up_real[W/s]", "double", _d(f"{DM}The real power ramp up rate limit", "1e9 W/s")),
        ("max_ramp_down_real[W/s]", "double", _d(f"{DM}The real power ramp down rate limit", "1e9 W/s")),
        ("enable_ramp_rates_reactive", "bool", _d(f"{DM}Boolean used to indicate whether inverter ramp rate is enforced or not", "FALSE")),
        ("max_ramp_up_reactive[VAr/s]", "double", _d(f"{DM}The reactive power ramp up rate limit", "1e9 VAr/s")),
        ("max_ramp_down_reactive[VAr/s]", "double", _d(f"{DM}The reactive power ramp down rate limit", "1e9 VAr/s")),
        ("dynamic_model_mode", "enumeration", prop(f"{DM}Underlying model to use for deltamode control", "PI", keywords=keywords(("PID", 0), ("PI", 1)))),
        ("enable_1547_checks", "bool", _d(f"{DM}Enable IEEE 1547-2003 disconnect checking", "FALSE")),
        ("reconnect_time[s]", "double", _d(f"{DM}Time delay after IEEE 1547-2003 violation clears before resuming generation", "300 s")),
        ("inverter_1547_status", "bool", _d(f"{DM}Indicator if the inverter is curtailed due to a 1547 violation or not", "TRUE")),
        ("IEEE_1547_version", "enumeration", prop(f"{DM}Version of IEEE 1547 to use to populate defaults", "IEEE1547A",
            keywords=keywords(("NONE", 0), ("IEEE1547", 1), ("IEEE1547A", 2)))),
        ("over_freq_high_cutout[Hz]", "double", _d(f"{DM}OF2 set point for IEEE 1547a", "62 Hz")),
        ("over_freq_high_disconenct_time[s]", "double", _d(f"{DM}OF2 clearing time for IEEE1547a", "0.16 s")),
        ("over_freq_low_cutout[Hz]", "double", _d(f"{DM}OF1 set point for IEEE 1547a", "60.5 Hz")),
        ("over_freq_low_disconenct_time[s]", "double", _d(f"{DM}OF1 clearing time for IEEE 1547a", "2 s")),
        ("under_freq_high_cutout[Hz]", "double", _d(f"{DM}UF2 set point for IEEE 1547a", "59.5 Hz")),
        ("under_freq_high_disconenct_time[s]", "double", _d(f"{DM}UF2 clearing time for IEEE1547a", "2 s")),
        ("under_freq_low_cutout[Hz]", "double", _d(f"{DM}UF1 set point for IEEE 1547a", "57 Hz")),
        ("under_freq_low_disconenct_time[s]", "double", _d(f"{DM}UF1 clearing time for IEEE 1547a", "0.16 s")),
        ("under_voltage_low_cutout[pu]", "double", _d("Lowest voltage threshold for undervoltage", "0.45 pu")),
        ("under_voltage_middle_cutout[pu]", "double", _d("Middle-lowest voltage threshold for undervoltage", "0.6 pu")),
        ("under_voltage_high_cutout[pu]", "double", _d("High value of low voltage threshold for undervoltage", "0.88 pu")),
        ("over_voltage_low_cutout[pu]", "double", _d("Lowest voltage value for overvoltage", "1.1 pu")),
        ("over_voltage_high_cutout[pu]", "double", _d("High voltage value for overvoltage", "1.2 pu")),
        ("under_voltage_low_disconnect_time[s]", "double", _d("Lowest voltage clearing time for undervoltage", "0.16 s")),
        ("under_voltage_middle_disconnect_time[s]", "double", _d("Middle-lowest voltage clearing time for undervoltage", "1 s")),
        ("under_voltage_high_disconnect_time[s]", "double", _d("Highest voltage clearing time for undervoltage", "2 s")),
        ("over_voltage_low_disconnect_time[s]", "double", _d("Lowest voltage clearing time for overvoltage", "1 s")),
        ("over_voltage_high_disconnect_time[s]", "double", _d("Highest voltage clearing time for overvoltage", "0.16 s")),
        ("IEEE_1547_trip_method", "enumeration", prop(f"{DM}Reason for IEEE 1547 disconnect - which threshold was hit", "NONE", keywords=TRIP)),
        ("phases", "set", prop("The phases the inverter is attached to", keywords=keywords(("A", 0x01), ("B", 0x02), ("C", 0x04), ("N", 0x08), ("S", 0x70)))),
        ("use_multipoint_efficiency", "bool", _d(f"{FQ}boolean to used the multipoint efficiency curve for the inverter when solar is attached", "FALSE")),
        ("inverter_manufacturer", "enumeration", prop(f"{MP}the manufacturer of the inverter to setup up pre-existing efficiency curves", "NONE",
            keywords=keywords(("NONE", NONE), ("FRONIUS", FRONIUS), ("SMA", SMA), ("XANTREX", XANTREX)))),
        ("maximum_dc_power", "double", _d(f"{MP}the maximum dc power point for the efficiency curve", "-1")),
        ("maximum_dc_voltage", "double", _d(f"{MP}the maximum dc voltage point for the efficiency curve", "-1")),
        ("minimum_dc_power", "double", _d(f"{MP}the minimum dc power point for the efficiency curve", "-1")),
        ("c_0", "double", _d(f"{MP}the first coefficient in the efficienty curve", "-1")),
        ("c_1", "double", _d(f"{MP}the second coefficient in the efficienty curve", "-1")),
        ("c_2", "double", _d(f"{MP}the third coefficient in the efficienty curve", "-1")),
        ("c_3", "double", _d(f"{MP}the fourth coefficient in the efficienty curve", "-1")),
        ("sense_object", "object", _d(f"{FQ}name of the object the inverter is trying to mitigate the load on (node/link) in LOAD_FOLLOWING")),
        ("max_charge_rate[W]", "double", _d(f"{FQ}maximum rate the battery can be charged in LOAD_FOLLOWING")),
        ("max_discharge_rate[W]", "double", _d(f"{FQ}maximum rate the battery can be discharged in LOAD_FOLLOWING")),
        ("charge_on_threshold[W]", "double", _d(f"{FQ}power level at which the inverter should try charging the battery in LOAD_FOLLOWING")),
        ("charge_off_threshold[W]", "double", _d(f"{FQ}power level at which the inverter should cease charging the battery in LOAD_FOLLOWING")),
        ("discharge_on_threshold[W]", "double", _d(f"{FQ}power level at which the inverter should try discharging the battery in LOAD_FOLLOWING")),
        ("discharge_off_threshold[W]", "double", _d(f"{FQ}power level at which the inverter should cease discharging the battery in LOAD_FOLLOWING")),
        ("excess_input_power[W]", "double", _d(f"{FQ}Excess power at the input of the inverter that is otherwise just lost, or could be shunted to a battery")),
        ("charge_lockout_time[s]", "double", _d(f"{FQ}Lockout time when a charging operation occurs before another LOAD_FOLLOWING dispatch operation can occur")),
        ("discharge_lockout_time[s]", "double", _d(f"{FQ}Lockout time when a discharging operation occurs before another LOAD_FOLLOWING dispatch operation can occur")),
        ("pf_reg_activate", "double", _d(f"{FQ}Lowest acceptable power-factor level below which power-factor regulation will activate.", "-2")),
        ("pf_reg_deactivate", "double", _d(f"{FQ}Lowest acceptable power-factor above which no power-factor regulation is needed.", "-1")),
        ("pf_target", "double", _d(f"{FQ}Desired power-factor to maintain (signed) positive is inductive", "-2")),
        ("pf_reg_high", "double", _d(f"{FQ}Upper limit for power-factor - if exceeds, go full reverse reactive", "-2")),
        ("pf_reg_low", "double", _d(f"{FQ}Lower limit for power-factor - if exceeds, stop regulating - pf_target_var is below this", "-2")),
        ("pf_reg_activate_lockout_time[s]", "double", _d(f"{FQ}Mandatory pause between the deactivation of power-factor regulation and it reactivation", "-1 s")),
        ("disable_volt_var_if_no_input_power", "bool", prop(default="FALSE")),
        ("delay_time[s]", "double", prop(default="-1 s")),
        ("max_var_slew_rate[VAr/s]", "double", prop()),
        ("max_pwr_slew_rate[W/s]", "double", prop()),
        ("volt_var_sched", "char1024", prop()),
        ("freq_pwr_sched", "char1024", prop()),
        ("charge_threshold[W]", "double", _d(f"{FQ}Level at which all inverters in the group will begin charging attached batteries. Regulated minimum load level.", "-1 W")),
        ("discharge_threshold[W]", "double", _d(f"{FQ}Level at which all inverters in the group will begin discharging attached batteries. Regulated maximum load level.", "-1 W")),
        ("group_max_charge_rate[W]", "double", _d(f"{FQ}Sum of the charge rates of the batteries involved in the group load-following.", "-1 W")),
        ("group_max_discharge_rate[W]", "double", _d(f"{FQ}Sum of the discharge rates of the batteries involved in the group load-following.", "-1 W")),
        ("group_rated_power[W]", "double", _d(f"{FQ}Sum of the inverter power ratings of the inverters involved in the group power-factor regulation.", "-1 W")),
        ("V_base[V]", "double", _d(f"{FQ}The base voltage on the grid side of the inverter. Used in VOLT_VAR control mode.")),
        *((f"{x}{k}[pu]", "double", _d(f"{FQ}{'voltage' if x == 'V' else 'VAR'} point {k} in volt/var curve. Used in VOLT_VAR control mode.", "-2 pu"))
            for k in "1234" for x in "VQ"),
        ("volt_var_control_lockout[s]", "double", _d("FOUR QUADRANT QUADRANT MODEL: the lockout time between volt/var actions.", "-1 s")),
    )
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order, with the defaults of `inverter::create()`"""

    @classmethod
    def register(cls, module:Any) -> Any:
        """Register the class for `module` with its properties and event
        handlers"""
        return register(cls, module)

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=too-many-branches,too-many-statements,too-many-locals,unused-argument
        """`inverter::init()`: `False` fails, 2 defers"""
        out = msg(model, name)
        parent = ref(model, name, "parent")
        if parent is None:
            raise Throw("cannot initialize an inverter without a parent")
        from .solar import initialized # pylint: disable=import-outside-toplevel
        if not initialized(model, parent):
            out.verbose("init() deferring initialization")
            return INIT_DEFER
        st = object_state(model, name)
        st.update({"last_current": [0j]*4, "last_power": [0j]*4, "I_Out": [0j]*3, "p_max": -1.0})
        deltamode = bool(object_flags(model, name) & OF_DELTAMODE)
        if isa(model, parent, "meter"):
            st["parent_kind"] = "meter"
        elif isa(model, parent, "triplex_meter"):
            st["parent_kind"] = "triplex_meter"
            for prop_ in ("voltage_12", "current_1", "current_12", "power_12", "prerotated_current_12", "measured_voltage_1"):
                if model.objects[parent].oclass.find_property(prop_) is None:
                    pobj = model.objects[parent]
                    raise Throw(f"{label(model, parent, 'unnamed object')} ({pobj.oclass.name}:{pobj.id}) does not implement triplex_meter variable {prop_} for {label(model, name)} (inverter:{object_id(model, name)})")
        else:
            raise Throw("Inverter must have a meter or triplex meter as it's parent")
        if model.objects[parent].oclass.find_property("service_status") is None:
            raise Throw("Inverter failed to map powerflow status variable")
        pspec = model.objects[parent].oclass.find_property("phases")
        if pspec is None or pspec.ptype != "set":
            raise Throw("Unable to map phases property - ensure the parent is a meter or triplex_meter")
        phases = get_int(model, parent, "phases")
        model.objects[name]["phases"] = model.get_property(parent, "phases")
        if phases & 0x10:
            nphases = 1
        elif phases & 0x07 == 0x07:
            nphases = 3
        elif phases & 0x03 == 0x03 or phases & 0x05 == 0x05 or phases & 0x06 == 0x06:
            nphases = 2
        elif phases & 0x07:
            nphases = 1
        else:
            raise Throw("Invalid phase configuration specified!")
        st["number_of_phases_out"] = nphases
        st["phases"] = phases
        itype = get_int(model, name, "inverter_type")
        gen_mode = get_int(model, name, "generator_mode")
        if gen_mode == UNKNOWN and itype != FOUR_QUADRANT:
            out.warning("Inverter control mode is not specified! Using default: CONSTANT_PF")
            set_int(model, name, "generator_mode", CONSTANT_PF)
        if get_int(model, name, "generator_status") == UNKNOWN:
            out.warning("Inverter status is unknown! Using default: ONLINE")
            set_int(model, name, "generator_status", ONLINE)
        if itype == UNKNOWN:
            out.warning("Inverter type is unknown! Using default: PWM")
            itype = PWM
            set_int(model, name, "inverter_type", PWM)
        inv_eta = get_double(model, name, "inverter_efficiency")
        efficiency = inv_eta
        p_rated = get_double(model, name, "rated_power")
        multipoint = bool(get_int(model, name, "use_multipoint_efficiency"))
        fqm = get_int(model, name, "four_quadrant_control_mode")
        if itype in (SIX_PULSE, TWELVE_PULSE, PWM):
            if inv_eta == 0:
                efficiency = 0.9 if itype == PWM else 0.8
                out.warning(f"inverter_efficiency unspecified--defaulted to {efficiency:.2f} for this inverter type")
        elif itype == FOUR_QUADRANT:
            if inv_eta == 0:
                efficiency = 0.9
                out.warning(f"inverter_efficiency unspecified--defaulted to {efficiency:.2f} for this inverter type")
            if inv_eta == 0:
                inv_eta = 0.9
            elif inv_eta < 0:
                inv_eta = 0.9
                out.warning(f"inverter_efficiency must be positive--defaulting to {inv_eta:.2f}")
            if p_rated == 0:
                p_rated = 25000
                out.warning(f"rated_power must be non-zero--defaulting to {p_rated/1000:.1f} kW")
            bp_rated = get_double(model, name, "rated_battery_power")
            if nphases in (1, 2, 3):
                bp_rated = nphases*p_rated/inv_eta
            set_double(model, name, "rated_battery_power", bp_rated)
            if not multipoint and st["p_max"] == -1:
                st["p_max"] = bp_rated*inv_eta
            if fqm in NOT_PORTED:
                raise Throw(f"four_quadrant_control_mode {NOT_PORTED[fqm]} is not supported yet")
            if get_int(model, name, "pf_reg") != EXCLUDED:
                raise Throw("pf_reg (power-factor regulation) is not supported yet")
            set_double(model, name, "inverter_efficiency", inv_eta)
            set_double(model, name, "rated_power", p_rated)
        else:
            raise Throw("Invalid inverter type specified!")
        if efficiency <= 0 or efficiency > 1:
            raise Throw(f"The efficiency specified for inverter:{label(model, name, '(null)')} is invalid")
        st["efficiency"] = efficiency
        if multipoint:
            result = cls._init_multipoint(model, name, st, nphases)
            if result is not True:
                return result
        if get_int(model, name, "enable_1547_checks"):
            raise Throw("enable_1547_checks (IEEE 1547 checks) is not supported yet")
        enabled = model.globals.isdefined(f"{MODULE}::enable_subsecond_models") and \
            str(model.globals.get(f"{MODULE}::enable_subsecond_models")).upper() in ("TRUE", "1")
        if deltamode:
            if not enabled:
                out.warning(f"inverter:{label(model, name)} indicates it wants to run deltamode, but the module-level flag is not set!")
            else:
                raise Throw("deltamode is not supported yet")
        elif enabled:
            out.warning(f"inverter:{object_id(model, name)} {label(model, name, 'Unnamed')} - Deltamode is enabled for the module, but not this inverter!")
        bspec = model.objects[parent].oclass.find_property("bustype")
        if bspec is None or bspec.ptype != "enumeration":
            raise Throw(f"inverter:{label(model, name)} failed to map bustype variable from {label(model, parent)}")
        if not model.globals.isdefined("powerflow::current_frequency"):
            raise Throw(f"inverter:{label(model, name)} - Failed to map frequency checking variable from powerflow for deltamode")
        set_complex(model, name, "VA_Out", complex(get_double(model, name, "P_Out"), get_double(model, name, "Q_Out")))
        st["parent"] = parent
        return True

    @classmethod
    def _init_multipoint(cls, model:Any, name:str, st:dict[str,Any], nphases:int) -> bool: # pylint: disable=too-many-branches,too-many-return-statements
        """Multipoint efficiency defaults (gridlabd `inverter::init()`)"""
        out = msg(model, name)
        values = {key: get_double(model, name, prop_) for key, prop_ in MULTIPOINT}
        p_rated = get_double(model, name, "rated_power")
        maker = get_int(model, name, "inverter_manufacturer")
        if maker == NONE:
            if values["p_dco"] < 0:
                out.error("no maximum dc power was given for the inverter.")
                return False
            if values["v_dco"] < 0:
                out.error("no maximum dc voltage was given for the inverter.")
                return False
            if values["p_so"] < 0:
                out.error("no minimum dc power was given for the inverter.")
                return False
            if p_rated <= 0:
                out.error("no rated per phase power was given for the inverter.")
                return False
            st["p_max"] = nphases*p_rated
            for key in ("c_o", "c_1", "c_2", "c_3"):
                if values[key] == -1:
                    values[key] = 0
        elif maker in MANUFACTURERS:
            preset = MANUFACTURERS[maker]
            for key in ("p_dco", "v_dco", "p_so"):
                if values[key] < 0:
                    values[key] = preset[key]
            for key in ("c_o", "c_1", "c_2", "c_3"):
                if values[key] == -1:
                    values[key] = preset[key]
            if st["p_max"] < 0:
                st["p_max"] = preset["p_max"]
                set_double(model, name, "rated_power", st["p_max"]/nphases)
        for key, prop_ in MULTIPOINT:
            set_double(model, name, prop_, values[key])
        if st["p_max"] > values["p_dco"]:
            out.error("The maximum dc power into the inverter cannot be less than the maximum ac power out.")
            return False
        if values["p_so"] > values["p_dco"]:
            out.error("The maximum dc power into the inverter cannot be less than the minimum dc power.")
            return False
        return True

    #
    # Synchronization
    #
    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`inverter::presync()`: the legacy types clear their output
        currents"""
        if get_int(model, name, "inverter_type") != FOUR_QUADRANT:
            for x in "ABC":
                set_complex(model, name, f"phase{x}_I_Out", 0j)
        return TS_NEVER

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`inverter::sync()`: compute the output and post it to the parent"""
        st = object_state(model, name)
        parent = st["parent"]
        phases = st["phases"]
        if get_int(model, name, "generator_status") == OFFLINE:
            for x in "ABC":
                set_complex(model, name, f"power_{x}", 0j)
            set_double(model, name, "P_Out", 0)
            set_double(model, name, "Q_Out", 0)
            set_complex(model, name, "VA_Out", 0j)
            last = st["last_power"]
            if phases & 0x10:
                last[3] = 0j
            else:
                set_double(model, name, "power_in", 0)
                for k in range(3):
                    if phases & PHASE_BITS[k]:
                        last[k] = 0j
            st["last_current"] = [0j]*4 # difference 3
            return TS_NEVER
        if _in_service(model, parent) and get_int(model, name, "inverter_1547_status"):
            volts = _voltages(model, parent, phases)
            for k, x in enumerate("ABC"):
                set_complex(model, name, f"phase{x}_V_Out", volts[k])
            if get_int(model, name, "inverter_type") != FOUR_QUADRANT:
                cls._sync_legacy(model, name, st, volts)
            else:
                cls._sync_four_quadrant(model, name, st, volts)
        elif _in_service(model, parent):
            cls._repost(model, name, st)
        else:
            st["last_current"] = [0j]*4
            st["last_power"] = [0j]*4
        return TS_NEVER

    @classmethod
    def _repost(cls, model:Any, name:str, st:dict[str,Any]) -> None:
        """Post the last values again (an inverter curtailed by IEEE 1547)"""
        parent = st["parent"]
        triplex = st["phases"] & 0x10
        if get_int(model, name, "inverter_type") != FOUR_QUADRANT:
            if triplex:
                post(model, parent, "current_12", st["last_current"][3])
            else:
                for k, x in enumerate("ABC"):
                    post(model, parent, f"current_{x}", st["last_current"][k])
        elif triplex:
            post(model, parent, "power_12", st["last_power"][3])
        else:
            for k, x in enumerate("ABC"):
                post(model, parent, f"power_{x}", st["last_power"][k])

    @classmethod
    def _sync_legacy(cls, model:Any, name:str, st:dict[str,Any], volts:list[complex]) -> None: # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """Legacy types (`inverter::sync()`, `inverter_type` other than
        `FOUR_QUADRANT`)"""
        out = msg(model, name)
        parent = st["parent"]
        phases = st["phases"]
        nphases = st["number_of_phases_out"]
        mode = get_int(model, name, "generator_mode")
        if mode == CONSTANT_PQ:
            raise Throw("Constant PQ mode not supported at this time")
        if mode == CONSTANT_V:
            raise Throw("Constant V mode not supported at this time")
        if mode == SUPPLY_DRIVEN:
            raise Throw("SUPPLY_DRIVEN mode for inverters not supported at this time")
        currents = [get_complex(model, name, f"phase{x}_I_Out") for x in "ABC"]
        if mode != CONSTANT_PF:
            cls._post_currents(model, parent, st, [currents[0], currents[1], currents[2]], sign=1)
            return
        efficiency = st["efficiency"]
        v_in = get_complex(model, name, "V_In")
        va_in = v_in * get_complex(model, name, "I_In").conjugate()
        set_complex(model, name, "VA_In", va_in)
        va_out = get_complex(model, name, "VA_Out")
        if not get_int(model, name, "use_multipoint_efficiency"):
            va_out = va_in * efficiency
        else:
            va_out = cls._multipoint(model, name, st, va_in, v_in, va_out)
        set_complex(model, name, "VA_Out", va_out)
        pf = get_double(model, name, "power_factor")
        smag = abs(va_out)
        power = complex(smag*abs(pf), fdiv(pf, abs(pf))*smag*math.sin(cacos(pf)))
        if phases & 0x10:
            set_complex(model, name, "power_A", power)
            currents[0] = (power/volts[0]).conjugate() if abs(volts[0]) != 0.0 else 0j
            set_complex(model, name, "phaseA_I_Out", currents[0])
            st["last_current"][3] = -currents[0]
            post(model, parent, "current_12", -currents[0])
            return
        if nphases == 3:
            for k, x in enumerate("ABC"):
                set_complex(model, name, f"power_{x}", power/3)
                currents[k] = ((power/3)/volts[k]).conjugate() if abs(volts[k]) != 0.0 else 0j
        elif nphases == 2:
            for k, x in enumerate("ABC"):
                if phases & PHASE_BITS[k] and abs(volts[k]) != 0:
                    set_complex(model, name, f"power_{x}", power/2)
                    currents[k] = ((power/2)/volts[k]).conjugate()
                else:
                    currents[k] = 0j
        else:
            for k, x in enumerate("ABC"):
                if phases & PHASE_BITS[k] and abs(volts[k]) != 0:
                    set_complex(model, name, f"power_{x}", power)
                    currents[k] = (power/volts[k]).conjugate()
                    break
            else:
                out.warning("None of the phases specified have voltages!")
                currents = [0j, 0j, 0j]
        for k, x in enumerate("ABC"):
            set_complex(model, name, f"phase{x}_I_Out", currents[k])
        cls._post_currents(model, parent, st, [-c for c in currents], sign=1)

    @staticmethod
    def _post_currents(model:Any, parent:str, st:dict[str,Any], values:list[complex], sign:int) -> None:
        """`pLine_I[k] += value; last_current[k] = value`"""
        for k, x in enumerate("ABC"):
            post(model, parent, f"current_{x}", sign*values[k])
            st["last_current"][k] = sign*values[k]

    @classmethod
    def _multipoint(cls, model:Any, name:str, st:dict[str,Any], va_in:complex, v_in:complex, va_out:complex) -> complex: # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        """Multipoint efficiency output (the CEC model of the legacy
        `CONSTANT_PF` mode); `VA_Out`'s imaginary part is kept"""
        p_dco, v_dco, p_so = (get_double(model, name, x) for x in ("maximum_dc_power", "maximum_dc_voltage", "minimum_dc_power"))
        c_o, c_1, c_2, c_3 = (get_double(model, name, x) for x in ("c_0", "c_1", "c_2", "c_3"))
        if abs(va_in) <= p_so:
            return 0j
        if abs(v_in) > v_dco:
            msg(model, name).warning("The dc voltage is greater than the specified maximum for the inverter. Efficiency model may be inaccurate.")
        c1 = p_dco*(1+c_1*(v_in.real-v_dco))
        c2 = p_so*(1+c_2*(v_in.real-v_dco))
        c3 = c_o*(1+c_3*(v_in.real-v_dco))
        p_max = st["p_max"]
        value = (((p_max/(c1-c2))-c3*(c1-c2))*(va_in.real-c2)+c3*(va_in.real-c2)*(va_in.real-c2))
        return complex(value, va_out.imag)

    @classmethod
    def _sync_four_quadrant(cls, model:Any, name:str, st:dict[str,Any], volts:list[complex]) -> None: # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """`FOUR_QUADRANT` type (`inverter::sync()`)"""
        out = msg(model, name)
        parent = st["parent"]
        phases = st["phases"]
        nphases = st["number_of_phases_out"]
        efficiency = st["efficiency"]
        p_max = st["p_max"]
        inv_eta = get_double(model, name, "inverter_efficiency")
        fqm = get_int(model, name, "four_quadrant_control_mode")
        v_in = get_complex(model, name, "V_In")
        va_in = v_in * get_complex(model, name, "I_In").conjugate()
        set_complex(model, name, "VA_In", va_in)
        battery = 0j
        if phases & 0x10:
            battery = get_complex(model, name, "power_A")
        else:
            for k, x in enumerate("ABC"):
                if phases & PHASE_BITS[k]:
                    battery += get_complex(model, name, f"power_{x}")
        if not get_int(model, name, "use_multipoint_efficiency"):
            va_eff = va_in.real * efficiency
            p_in_local = abs(va_in.real)
        else:
            mp = cls._multipoint(model, name, st, va_in, v_in, 0j)
            va_eff = mp.real
            p_in_local = 0.0 if abs(va_in) <= get_double(model, name, "minimum_dc_power") else abs(va_in.real)
        va_eff += abs(battery)
        va_out = get_complex(model, name, "VA_Out")
        p_in = get_double(model, name, "power_in")
        if fqm == FQM_CONSTANT_PF:
            pf = get_double(model, name, "power_factor")
            if pf != 0.0:
                real = va_eff if abs(va_in) > 0.0 else 0.0
                if pf < 0:
                    imag = (va_eff/math.sqrt(pf*pf))*csqrt(1.0-(pf*pf))
                else:
                    imag = (va_eff/math.sqrt(pf*pf))*-1.0*csqrt(1.0-(pf*pf))
                va_out = complex(real, imag)
            else:
                va_out = complex(0.0, va_eff)
        elif fqm == FQM_CONSTANT_PQ:
            p_out = get_double(model, name, "P_Out")
            q_out = get_double(model, name, "Q_Out")
            set_double(model, name, "Pref", p_out)
            set_double(model, name, "Qref", q_out)
            temp = complex(p_out, q_out)
            soc = get_double(model, name, "battery_soc")
            reserve = get_double(model, name, "soc_reserve")
            if soc >= 1.0 and temp.real < 0 and soc != -1:
                out.warning(f"inverter:{label(model, name, '(null)')} - battery full - no charging allowed")
                temp = complex(0.0, temp.imag)
            elif soc <= reserve and temp.real > 0 and soc != -1:
                out.warning(f"inverter:{label(model, name, '(null)')} - battery at or below the SOC reserve - no discharging allowed")
                temp = complex(0.0, temp.imag)
            if abs(temp) > p_max:
                if p_max > abs(temp.real):
                    q = math.sqrt((p_max*p_max) - (temp.real*temp.real))
                    va_out = complex(temp.real, -q if temp.imag < 0.0 else q)
                else:
                    va_out = complex(-p_max if temp.real < 0.0 else p_max, 0.0)
            else:
                va_out = temp
            p_in = _p_in(va_out, inv_eta)
        excess = 0.0
        if abs(va_out) > p_max:
            excess = abs(va_out) - p_max
            if fqm == FQM_CONSTANT_PF:
                temp_pf = get_double(model, name, "power_factor")
            else:
                temp_pf = va_out.real/abs(va_out)
            temp = complex(abs(p_max*temp_pf), abs(p_max*csqrt(1.0-(temp_pf*temp_pf))))
            if va_out.real < 0 and va_out.imag < 0:
                va_out = -temp
            elif va_out.real < 0:
                va_out = complex(-temp.real, temp.imag)
            elif va_out.imag < 0:
                va_out = complex(temp.real, -temp.imag)
            else:
                va_out = temp
        set_double(model, name, "excess_input_power", excess)
        if abs(battery) != 0.0:
            soc = get_double(model, name, "battery_soc")
            reserve = get_double(model, name, "soc_reserve")
            if soc == 1.0 and va_out.real < 0 and soc != -1:
                out.warning(f"inverter:{label(model, name, '(null)')} - battery full - no charging allowed")
                va_out = complex(0.0, va_out.imag)
            elif soc <= reserve and va_out.real > 0 and soc != -1:
                out.warning(f"inverter:{label(model, name, '(null)')} - battery at or below the SOC reserve - no discharging allowed")
                va_out = complex(0.0, va_out.imag)
            p_in = _p_in(va_out, inv_eta)
        set_double(model, name, "power_in", p_in)
        set_complex(model, name, "VA_Out", va_out)
        if fqm != FQM_CONSTANT_PQ:
            set_double(model, name, "P_Out", va_out.real)
            set_double(model, name, "Q_Out", va_out.imag)
        last = st["last_power"]
        if phases & 0x10:
            last[3] = -va_out
            set_complex(model, name, "curr_VA_out_A", va_out)
            st["I_Out"][0] = (va_out/volts[0]).conjugate() if abs(volts[0]) > 0.0 else 0j
            post(model, parent, "power_12", last[3])
        else:
            temp = -va_out/nphases
            for k, x in enumerate("ABC"):
                if phases & PHASE_BITS[k]:
                    set_complex(model, name, f"curr_VA_out_{x}", -temp)
                    last[k] = temp
                    st["I_Out"][k] = (-temp/volts[k]).conjugate() if abs(volts[k]) > 0.0 else 0j
                    post(model, parent, f"power_{x}", temp)
        if p_in_local < p_in:
            out.warning("DC maximum power output is less than the real power output from the inverter. A higher DC power rating is recommended. Currently the VSI power output is not limited by the DC power output.")

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`inverter::postsync()`: remove the posted values"""
        st = object_state(model, name)
        parent = st["parent"]
        triplex = st["phases"] & 0x10
        if get_int(model, name, "inverter_type") != FOUR_QUADRANT:
            if triplex:
                post(model, parent, "current_12", -st["last_current"][3])
            else:
                for k, x in enumerate("ABC"):
                    post(model, parent, f"current_{x}", -st["last_current"][k])
        elif triplex:
            post(model, parent, "power_12", -st["last_power"][3])
        else:
            for k, x in enumerate("ABC"):
                post(model, parent, f"power_{x}", -st["last_power"][k])
        return TS_NEVER

def _p_in(va_out:complex, inv_eta:float) -> float:
    """DC power drawn from a battery for an output (`p_in`)"""
    if va_out.real > 0.0:
        return va_out.real/inv_eta
    if va_out.real == 0.0:
        return 0.0
    return va_out.real*inv_eta

def _in_service(model:Any, parent:str) -> bool:
    """`*pMeterStatus == 1` (see difference 2)"""
    return get_text(model, parent, "service_status") != "OUT_OF_SERVICE"

def _voltages(model:Any, parent:str, phases:int) -> list[complex]:
    """`pCircuit_V[0..2]`: `voltage_A` ... `voltage_C` of a meter;
    `voltage_12`, `voltage_2N`, `voltage_1N` of a triplex meter (the
    order of gridlabd's `voltaged[]`)"""
    if phases & 0x10:
        return [get_complex(model, parent, x) for x in ("voltage_12", "voltage_2N", "voltage_1N")]
    return [get_complex(model, parent, f"voltage_{x}") for x in "ABC"]
