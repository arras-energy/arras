# pylint: disable=line-too-long
"""Class `ZIPload`: a load with constant impedance, current, and power parts

Syntax
------

    object ZIPload {
        parent <house>;
        base_power <real> kW;
        power_fraction <real> pu;
        current_fraction <real> pu;
        impedance_fraction <real> pu;
        power_pf <real>;
        current_pf <real>;
        impedance_pf <real>;
        heat_fraction <real>;
        is_240 {TRUE,FALSE};
        breaker_val <real> A;
        multiplier <real>;
        heatgain_only {TRUE,FALSE};
        duty_cycle <real> pu;
        period <real> h;
        phase <real> pu;
        recovery_duty_cycle <real> pu;
        demand_response_mode {TRUE,FALSE};
        number_of_devices <integer>;
        thermostatic_control_range <integer>;
        rate_of_cooling <real> K/h;
        rate_of_heating <real> K/h;
        phi <real>;
        demand_rate <real> 1/h;
        // and the properties of residential_enduse
    }

Description
-----------

A `ZIPload` is a `residential_enduse` whose load is `multiplier *
base_power` (kW), split into constant power, current, and impedance parts
by `power_fraction`, `current_fraction`, and `impedance_fraction`, each at
its own power factor (`power_pf`, `current_pf`, `impedance_pf`; a negative
power factor is leading). When it initializes it is attached to its parent
house's panel on a 120 V circuit, or a 240 V circuit with `is_240`, with
`breaker_val` as the breaker rating.

When it synchronizes (bottom-up), a ZIP load is expected to:

1. in demand response mode, advance the equilibrium population model of
   thermostatic devices (Chassin and Fuller, "On the Equilibrium Dynamics
   of Demand Response in Thermostatic Loads") and take its load from the
   devices that are on;
2. in duty cycle mode (`duty_cycle` between 0 and 1), switch the load on
   for `duty_cycle` of each `period` (hours) from `phase`, with the
   override and recovery logic of gridlabd's `ZIPload::sync()`;
3. set `voltage_factor` from its circuit voltage (240 V or 120 V);
4. while its breaker is closed, set the constant power, current, and
   impedance parts (`constant_power`, `constant_current`,
   `constant_admittance`, kVA at nominal voltage), `power` (their sum),
   `actual_power` (the parts at the circuit voltage), the power factor of
   the total, and `heatgain` (`heat_fraction` of the real power, in
   Btu/h); with `heatgain_only`, no electric load and a heat gain of the
   whole demand; with the breaker open, no load;
5. return the next duty cycle or demand response time.

Caveats
-------

- The demand response model is experimental in gridlabd (it warns at
  initialization) and is ported as written.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A ZIP load without a house parent computes its load as with a closed
   breaker and a voltage factor of 1 (gridlabd dereferences the missing
   circuit).
2. `number_of_devices` and `temperature` are `int16` properties of
   `int64` and `int16` members in gridlabd; `arras` keeps the value
   written to `number_of_devices` whole.

References
----------

- `arras-energy/gridlabd`: `module/residential/zipload.cpp`, `zipload.h`
- [ZIPload](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Residential/Zipload.md)
  (`docs/Module/Residential/Zipload.md`)
"""

import math
from typing import Any

from ._base import prop
from ._common import (TS_NEVER, EUC_IS220, EUC_HEATLOAD, BRK_CLOSED, OV_NORMAL, OV_OFF, BTUPHPKW,
    msg, object_state, sqrt, exp, fdiv)
from .residential_enduse import ResidentialEnduse, EnduseMembers

class ZipMembers(EnduseMembers): # pylint: disable=too-many-instance-attributes
    """The members of a ZIP load"""

    MAP = (
        *EnduseMembers.MAP,
        ("load.heatgain_fraction", "heat_fraction", "d"),
        ("base_power", "base_power", "d"),
        ("power_pf", "power_pf", "d"),
        ("current_pf", "current_pf", "d"),
        ("impedance_pf", "impedance_pf", "d"),
        ("is_240", "is_240", "i"),
        ("breaker_val", "breaker_val", "d"),
        ("actual_power", "actual_power", "c"),
        ("multiplier", "multiplier", "d"),
        ("heatgain_only", "heatgain_only", "i"),
        ("demand_response_mode", "demand_response_mode", "i"),
        ("N", "number_of_devices", "i"),
        ("L", "thermostatic_control_range", "i"),
        ("N_off", "number_of_devices_off", "d"),
        ("N_on", "number_of_devices_on", "d"),
        ("roff", "rate_of_cooling", "d"),
        ("ron", "rate_of_heating", "d"),
        ("x", "temperature", "i"),
        ("phi", "phi", "d"),
        ("eta", "demand_rate", "d"),
        ("nominal_power", "nominal_power", "d"),
        ("duty_cycle", "duty_cycle", "d"),
        ("recovery_duty_cycle", "recovery_duty_cycle", "d"),
        ("period", "period", "d"),
        ("phase", "phase", "d"),
    )

    def __init__(self, model:Any, name:str):
        super().__init__(model, name)
        self.load.name = "ZIPload"
        for member, _, kind in self.MAP[len(EnduseMembers.MAP):]:
            if "." not in member:
                setattr(self, member, {"d": 0.0, "c": 0j, "i": 0}[kind])
        self.next_time = 0
        self.last_time = 0
        self.last_duty_cycle = 0.0
        self.first_pass = 1
        self.drm_on: list[float] = []
        self.drm_off: list[float] = []
        self.non = self.noff = 0.0

class ZIPload(ResidentialEnduse):
    """Behavior of class `ZIPload`"""

    NAME = "ZIPload"
    PARENT = "residential_enduse"
    PASSCONFIG = "BOTTOMUP|AUTOLOCK"
    EVENTS = ("init", "sync")
    MEMBERS = ZipMembers

    PROPERTIES = (
        ("heat_fraction", "double", prop("fraction of ZIPload that is transferred as heat", "0.9")),
        ("base_power[kW]", "double", prop("base real power of the overall load", "0")),
        ("power_pf", "double", prop("power factor for constant power portion", "1")),
        ("current_pf", "double", prop("power factor for constant current portion", "1")),
        ("impedance_pf", "double", prop("power factor for constant impedance portion", "1")),
        ("is_240", "bool", prop("load is 220/240 V (across both phases)", "FALSE")),
        ("breaker_val[A]", "double", prop("Amperage of connected breaker", "1000")),
        ("actual_power[kVA]", "complex", prop("variable to pull actual load as function of voltage")),
        ("multiplier", "double", prop("this variable is used to modify the base power as a function of multiplier x base_power", "1")),
        ("heatgain_only", "bool", prop("allows the zipload to generate heat only (no kW), not activated by default", "FALSE")),
        ("demand_response_mode", "bool", prop("Activates equilibrium dynamic representation of demand response", "FALSE")),
        ("number_of_devices", "int16", prop("Number of devices to model - base power is the total load of all devices")),
        ("thermostatic_control_range", "int16", prop("Range of the thermostat's control operation")),
        ("number_of_devices_off", "double", prop("Total number of devices that are off")),
        ("number_of_devices_on", "double", prop("Total number of devices that are on")),
        ("rate_of_cooling[K/h]", "double", prop("rate at which devices cool down", "-1")),
        ("rate_of_heating[K/h]", "double", prop("rate at which devices heat up", "-1")),
        ("temperature", "int16", prop("temperature of the device's controlled media (eg air temp or water temp)")),
        ("phi", "double", prop("duty cycle of the device", "0.2")),
        ("demand_rate[1/h]", "double", prop("consumer demand rate that prematurely turns on a device or population", "0.2")),
        ("nominal_power", "double", prop("the rated amount of power demanded by devices that are on")),
        ("duty_cycle[pu]", "double", prop("fraction of time in the on state", "-1")),
        ("recovery_duty_cycle[pu]", "double", prop("fraction of time in the on state, while in recovery interval", "-1")),
        ("period[h]", "double", prop("time interval to apply duty cycle", "0")),
        ("phase[pu]", "double", prop("initial phase of load; duty will be assumed to occur at beginning of period", "0")),
    )

    CREATE: dict[str,Any] = {
        **ResidentialEnduse.CREATE,
        "load.power": 0j,
        "load.admittance": 0j,
        "load.current": 0j,
        "load.total": 0j,
        "load.heatgain_fraction": 0.90,
        "load.power_factor": 1.00,
        "load.power_fraction": 1.0,
        "load.current_fraction": 0.0,
        "load.impedance_fraction": 0.0,
        "load.config": 0,
        "load.voltage_factor": 1.0,
    }
    """`ZIPload::create()` on the inherited members"""

    @classmethod
    def init_object(cls, model:Any, name:str, m:Any) -> bool|int: # pylint: disable=too-many-branches,too-many-statements
        """`ZIPload::init()`"""
        from ._common import ResidentialError # pylint: disable=import-outside-toplevel
        if m.demand_response_mode:
            msg(model, name).warning("zipload_init: The demand response zipload is an experimental model at this time.")
            if abs(m.eta) > 1:
                raise ResidentialError("zipload_init: demand_rate (eta) must be between -1 and 1.")
            if m.phi < 0 or m.phi > 1:
                raise ResidentialError("zipload_init: duty_cycle (phi) must be between 0 and 1.")
            if m.L > 0:
                if m.L >= 70:
                    msg(model, name).warning("zipload_init: Using a value for thermostatic_control_range (L) greater than 50 may cause some instabilities.")
            else:
                raise ResidentialError("zipload_init: thermostatic_control_range (L) must be greater than 0.")
            if m.ron == -1 or m.roff == -1:
                if m.phi <= 0.5:
                    m.roff = m.phi/(1 - m.phi)
                    m.ron = 1
                else:
                    m.roff = 1
                    m.ron = (1 - m.phi)/m.phi
                msg(model, name).warning("ron or roff was not set.  Using phi to calculate.  Step changes in demand rates as a function of time will be ignored.")
            else:
                m.phi = m.roff / (m.ron + m.roff)
            if m.roff < 0 or m.ron < 0:
                raise ResidentialError("zipload_init: rate_of_cooling and rate_of_heating must be greater than or equal to 0.")
            m.non = m.noff = 0.0
            test_n = 0.0
            m.drm_on = [0.0]*m.L
            m.drm_off = [0.0]*m.L
            for x in range(m.L):
                if m.eta != 0:
                    m.drm_on[x] = fdiv(m.N * m.eta * (1 - m.phi) * exp(m.eta*(m.L - 0.5 - x)/m.roff), exp(m.eta*m.L/m.roff) - 1)
                    m.drm_off[x] = m.drm_on[x] * m.ron/m.roff
                    test_n += m.drm_on[x] + m.drm_off[x]
                else:
                    m.drm_on[x] = m.N * m.phi/m.L
                    m.drm_off[x] = m.N * (1 - m.phi)/m.L
                    m.non += m.drm_on[x]
                    m.noff += m.drm_off[x]
            m.x = m.L
            if abs(test_n - m.N) != 0:
                m.drm_off[0] += m.N - test_n
        if m.duty_cycle > 1 or m.duty_cycle < 0:
            if m.duty_cycle != -1:
                raise ResidentialError("Value of duty cycle is set to a value outside of 0-1.")
        if m.duty_cycle != -1:
            if m.period <= 0:
                raise ResidentialError("Period is less than or equal to zero.")
            if m.phase < 0 or m.phase > 1:
                raise ResidentialError("Phase is not between zero and one.")
        if m.heatgain_only:
            m.load.config = EUC_HEATLOAD
            m.load.power_fraction = m.load.current_fraction = m.load.impedance_fraction = 0.0
        if m.is_240:
            m.load.config |= EUC_IS220
        m.load.breaker_amps = m.breaker_val
        return super().init_object(model, name, m)

    @classmethod
    def sync_object(cls, model:Any, name:str, m:Any, t0:int, t1:int) -> int: # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        """`ZIPload::sync()`"""
        t2 = TS_NEVER
        if m.demand_response_mode and m.next_time <= t1:
            cls.demand_response(m, t1)
        if m.duty_cycle != -1:
            cls.duty_cycle_mode(m, t1)
        circuit = cls.circuit(model, name)
        if circuit is not None:
            from .house import House # pylint: disable=import-outside-toplevel
            house = House.members(model, circuit_house(model, name))
            v = abs(House.circuit_voltage(model, house, circuit))
            m.load.voltage_factor = v / 240 if m.is_240 else v / 120
        t2 = super().sync_object(model, name, m, t0, t1)
        if circuit is None or circuit.status == BRK_CLOSED:
            demand_power = m.multiplier * m.base_power
            if m.demand_response_mode:
                demand_power = m.nominal_power
            load = m.load
            if not m.heatgain_only:
                def part(fraction:float, pf:float) -> complex:
                    real = demand_power * fraction
                    imag = 0.0 if pf == 0.0 else real * sqrt(1.0/(pf*pf) - 1.0)
                    if pf < 0:
                        imag *= -1.0
                    return complex(real, imag)
                load.power = part(load.power_fraction, m.power_pf)
                load.current = part(load.current_fraction, m.current_pf)
                load.admittance = part(load.impedance_fraction, m.impedance_pf)
                load.total = load.power + load.current + load.admittance
                vf = load.voltage_factor
                m.actual_power = load.power + load.current * vf + load.admittance * vf * vf
                angle = math.atan2(load.total.imag, load.total.real)
                load.power_factor = -1.0 * math.cos(angle) if angle < 0 else math.cos(angle)
                load.heatgain = load.total.real * load.heatgain_fraction * BTUPHPKW
            else:
                load.power = load.current = load.admittance = load.total = 0j
                m.actual_power = 0j
                load.heatgain = demand_power * BTUPHPKW
                return TS_NEVER
        else:
            load = m.load
            load.total = load.power = load.current = load.admittance = 0j
            load.heatgain = 0.0
            load.power_factor = 0.0
        if 0 < m.next_time < t2:
            t2 = m.next_time
        return t2

    @classmethod
    def demand_response(cls, m:Any, t1:int) -> None:
        """The demand response population update of `ZIPload::sync()`"""
        n_on = 0.0
        hold_off = 0.0
        on, off, eta, ron, roff, L = m.drm_on, m.drm_off, m.eta, m.ron, m.roff, m.L # pylint: disable=invalid-name
        for jj in range(L):
            if eta > 0:
                if jj != L - 1:
                    d_on = -ron * on[jj] + eta * off[jj] + ron * on[jj+1]
                else:
                    d_on = -ron * on[jj] + (1 - eta) * off[jj] * roff + eta * off[jj]
                if jj != 0:
                    d_off = -(1 - eta) * off[jj] * roff - eta * off[jj] + (1 - eta) * hold_off * roff
                else:
                    d_off = -(1 - eta) * off[jj] * roff - eta * off[jj] + ron * on[jj]
            else:
                if jj != L - 1:
                    d_on = -ron * (1 + eta) * on[jj] + eta * on[jj] + ron * (1 + eta) * on[jj+1]
                else:
                    d_on = -ron * (1 + eta) * on[jj] + eta * on[jj] + roff * off[jj]
                if jj != 0:
                    d_off = -roff * off[jj] - eta * on[jj] + hold_off * roff
                else:
                    d_off = -roff * off[jj] - eta * on[jj] + ron * (1 + eta) * on[jj]
            hold_off = off[jj]
            on[jj] = on[jj] + d_on
            n_on += on[jj]
            off[jj] = off[jj] + d_off
        m.N_on = n_on
        m.N_off = m.N - n_on
        m.phi = roff / (ron + roff)
        m.nominal_power = fdiv(m.base_power * n_on, m.N)
        rate = roff if ron < roff else ron
        m.next_time = t1 + int(1/rate * 3600)

    @classmethod
    def duty_cycle_mode(cls, m:Any, t1:int) -> None: # pylint: disable=too-many-branches
        """The duty cycle logic of `ZIPload::sync()`"""
        if m.first_pass == 0:
            m.phase = m.phase + (t1 - m.last_time) / (m.period * 3600)
        else:
            m.first_pass = 0
        m.last_time = t1
        period = m.period * 3600
        if m.re_override == OV_NORMAL:
            if m.phase >= 1:
                m.phase = 0
            if t1 >= m.next_time or m.last_duty_cycle != m.duty_cycle:
                if m.duty_cycle > m.phase:
                    m.multiplier = 1
                    m.next_time = int(t1 + period * (m.duty_cycle - m.phase) + 1)
                else:
                    m.multiplier = 0
                    m.next_time = int(t1 + period * (1 - m.phase) + 1)
            m.last_duty_cycle = m.duty_cycle
        elif m.re_override == OV_OFF:
            if m.phase <= 1 and t1 >= m.next_time:
                m.re_override = OV_NORMAL
                m.next_time = int(t1 + period * (1 - math.fmod(m.phase, 1)) + 1)
            elif t1 >= m.next_time or m.next_time == TS_NEVER:
                if m.recovery_duty_cycle > math.fmod(m.phase, 1):
                    m.multiplier = 1
                    m.next_time = int(t1 + period * (m.recovery_duty_cycle - math.fmod(m.phase, 1)) + 1)
                    if m.duty_cycle != 0.0:
                        m.phase -= 1 * m.recovery_duty_cycle / m.duty_cycle * (1 - math.fmod(m.phase, 1))
                    else:
                        m.phase = 0
                else:
                    m.multiplier = 0
                    m.next_time = int(t1 + period * (1 - math.fmod(m.phase, 1)) + 1)
            m.last_duty_cycle = m.duty_cycle
        else:
            if m.multiplier == 1 and m.duty_cycle > m.phase:
                m.last_duty_cycle = m.duty_cycle
            else:
                m.multiplier = 0
                m.next_time = TS_NEVER
                if m.recovery_duty_cycle > 0:
                    m.last_duty_cycle = m.duty_cycle
                else:
                    if m.phase >= 1:
                        m.phase -= 1
                    m.last_duty_cycle = 0

def circuit_house(model:Any, name:str) -> str:
    """Name of the house whose panel an enduse is attached to"""
    return object_state(model, name)["house"]

__all__ = ["ZIPload"]
