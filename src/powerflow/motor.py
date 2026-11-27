# pylint: disable=line-too-long
"""Class `motor`: a node with a single-phase or three-phase induction motor

Syntax
------

    object motor {
        phases {A|B|C}[N|S] | ABC[N];
        nominal_voltage <real> V;
        base_power <real> W;
        mechanical_torque <real>;                  // single-phase, pu
        TPIM_rated_mechanical_Load_torque <real>;  // three-phase, pu
        TPIM_initial_status {RUNNING,STATIONARY};
        motor_override {ON,OFF};
        triplex_connection_type {TRIPLEX_1N,TRIPLEX_2N,TRIPLEX_12};
        trip_time <real> s;
        reconnect_time <real> s;
        // the machine parameters (n, Rds, Rqs, Rr, Xm, Xr, Xc_run,
        // Xc_start, Xd_prime, Xq_prime, A_sat, b_sat, H, To_prime,
        // capacitor_speed, rs, rr, lm, lls, llr, friction_coefficient),
        // and the other properties of node
    }

Outputs: `motor_status` (`RUNNING`, `STALLED`, `TRIPPED`, `OFF`) and
`motor_status_number`, `wr` (rotor speed, rad/s, single-phase),
`motor_trip`, and the hidden states (fluxes, currents, torque, power).

Description
-----------

A `motor` is a `node` (gridlabd `PT_INHERIT "node"`) whose motor draws a
current at the node's voltage, as gridlabd's steady-state (QSS) motor
models compute it. A motor with one phase (`A`, `B`, or `C`, or `S` for a
triplex connection) is a single-phase induction motor (SPIM, the
capacitor-run model); a motor with phases `A`, `B`, and `C` is a
three-phase induction motor (TPIM, the sequence model). Before each
solution, and again after it with the solution's voltages, the motor is
expected to do what gridlabd's `motor::sync()` does:

1. read its voltage in per unit of `nominal_voltage` (the phase voltage;
   for a triplex connection line 1 or line 2 to neutral, or line 1 to
   line 2 over twice `nominal_voltage`), and its speed from the node's
   `measured_frequency_X` (`2 pi f` rad/s for the SPIM; for the TPIM the
   mean of the three phases in per unit of `powerflow::nominal_frequency`);
2. at a new time, keep its states; at the same time, restore the states
   of the time's start, so that each solution starts from them;
3. update its protection with the time elapsed since the previous time:
   a stalled, energized motor counts up to `trip_time` and then trips; a
   running or de-energized one counts down, scaled by
   `trip_time / reconnect_time`; a tripped motor reconnects after
   `reconnect_time`;
4. when it is on (`motor_override ON`), energized (speed above 1 rad/s
   or 0.1 pu, voltage above 0.1 pu on each phase) and not tripped: solve
   its steady state (the SPIM iterates its speed until the electrical
   torque meets `mechanical_torque` within `maximum_speed_error`, at most
   `iteration_count` times; the TPIM solves its sequence fluxes and
   iterates its speed toward the load torque) and draw its current
   (`Is base_power / nominal_voltage`, over twice the nominal voltage for a
   line 1 to line 2 connection; the TPIM `I_X base_power /
   nominal_voltage / 3`) as a current fixed in the solution (gridlabd's
   pre-rotated current); otherwise draw none and clear its states;
5. set `motor_status`.

When the current after the solution differs from the one solved with, the
network is solved again.

When it initializes, a motor is expected to initialize as a `node`, then
to fail unless it has one or three of the phases `A`, `B`, `C`; to set
the base current, speed thresholds, and TPIM reactances; and, for a TPIM
starting `STATIONARY`, to start at speed 0 with no load torque, or
`RUNNING`, at speed `sqrt(TPIM_rated_mechanical_Load_torque)` with that
torque.

Caveats
-------

- Deltamode (the dynamic models, the deltamode triggers and exits) is not
  ported; its properties are published and not used.
- The frequency is the node's `measured_frequency_X`, which nothing
  updates outside deltamode, so a motor on a `vfd` runs at the system
  frequency, as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The motor current is solved with the voltages of the same solution;
   gridlabd computes it in `sync()` from the voltages of the previous
   solution, so it lags the voltage by one solution (at the first time,
   it uses the initial voltages).
2. The TPIM speed is in per unit of `powerflow::nominal_frequency`;
   gridlabd divides the frequency by 60 Hz.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/motor.cpp`, `motor.h`
"""

import cmath
import math
from typing import Any

import numpy as np

from ._base import prop, keywords
from ._common import PHASE_A, PHASE_B, PHASE_C, PHASE_S, g, object_state, get_int, get_double, get_complex, set_complex, set_double, PowerflowError
from .node import Node

RUNNING, STALLED, TRIPPED, OFF = range(4)
"""`motor_status` values"""

STATUS_NAMES = ("RUNNING", "STALLED", "TRIPPED", "OFF")

TPN_1N, TPN_2N, TPN_12 = range(3)
"""`triplex_connection_type` values"""

ALPHA = cmath.rect(1.0, 2*math.pi/3)

SPIM_STATES = ("wr", "electrical_torque", "psi_dr", "psi_qr", "psi_f", "psi_b", "Iqs", "Ids", "If", "Ib", "Is", "Ss")
"""Published SPIM states (gridlabd `SPIMupdateVars()`, with `psi_sat` and
the protection states)"""

TPIM_STATES = ("phips", "phins_cj", "phipr", "phinr_cj", "omgr0", "Ips", "Ipr", "Ins_cj", "Inr_cj")
"""Published TPIM states (gridlabd `TPIMupdateVars()`, with the
protection states)"""

PROTECTION = ("reconnect", "motor_trip", "trip")

def _hidden(name:str, ptype:str, description:str) -> tuple[str,str,dict[str,Any]]:
    return (name, ptype, prop(description, access="HIDDEN"))

class Motor(Node):
    """Behavior of class `motor`"""

    NAME = "motor"
    PARENT = "node"
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|UNSAFE_OVERRIDE_OMIT|AUTOLOCK"
    TRL = 1 # TRL_PRINCIPLE
    PROPERTIES = (
        ("base_power[W]", "double", prop("base power", "3500 W")),
        ("n", "double", prop("ratio of stator auxiliary windings to stator main windings", "1.22")),
        ("Rds[ohm]", "double", prop("d-axis resistance", "0.0365 ohm")),
        ("Rqs[ohm]", "double", prop("q-asis resistance", "0.0729 ohm")),
        ("Rr[ohm]", "double", prop("rotor resistance", "0.0486 ohm")),
        ("Xm[ohm]", "double", prop("magnetizing reactance", "2.28 ohm")),
        ("Xr[ohm]", "double", prop("rotor reactance", "2.33 ohm")),
        ("Xc_run[ohm]", "double", prop("running capacitor reactance", "-2.779 ohm")),
        ("Xc_start[ohm]", "double", prop("starting capacitor reactance", "-0.7 ohm")),
        ("Xd_prime[ohm]", "double", prop("d-axis reactance", "0.1033 ohm")),
        ("Xq_prime[ohm]", "double", prop("q-axis reactance", "0.1489 ohm")),
        ("A_sat", "double", prop("flux saturation parameter, A", "5.6")),
        ("b_sat", "double", prop("flux saturation parameter, b", "0.7212")),
        ("H", "double", prop("moment of inertia", "0.04")),
        ("To_prime[s]", "double", prop("rotor time constant", "0.1212 s")),
        ("capacitor_speed[%]", "double", prop("percentage speed of nominal when starting capacitor kicks in", "50 %")),
        ("trip_time[s]", "double", prop("time motor can stay stalled before tripping off ", "10 s")),
        ("reconnect_time[s]", "double", prop("time before tripped motor reconnects", "300 s")),
        ("mechanical_torque", "double", prop("mechanical torque applied to the motor", "1.0448")),
        ("iteration_count", "double", prop("maximum number of iterations for steady state model", "1000")),
        ("delta_mode_voltage_trigger[%]", "double", prop("percentage voltage of nominal when delta mode is triggered", "80 %")),
        ("delta_mode_rotor_speed_trigger[%]", "double", prop("percentage speed of nominal when delta mode is triggered", "80 %")),
        ("delta_mode_voltage_exit[%]", "double", prop("percentage voltage of nominal to exit delta mode", "95 %")),
        ("delta_mode_rotor_speed_exit[%]", "double", prop("percentage speed of nominal to exit delta mode", "95 %")),
        ("maximum_speed_error", "double", prop("maximum speed error for the steady state model", "1e-10")),
        ("wr", "double", prop("rotor speed")),
        ("motor_status", "enumeration", prop("the current status of the motor", "RUNNING",
            keywords=keywords(("RUNNING", RUNNING), ("STALLED", STALLED), ("TRIPPED", TRIPPED), ("OFF", OFF)))),
        ("motor_status_number", "int32", prop("the current status of the motor as an integer")),
        ("motor_override", "enumeration", prop("override function to dictate if motor is turned off or on", "ON",
            keywords=keywords(("ON", 0), ("OFF", 1)))),
        ("motor_operation_type", "enumeration", prop("current operation type of the motor - deltamode related", "SINGLE-PHASE",
            keywords=keywords(("SINGLE-PHASE", 0), ("THREE-PHASE", 1)))),
        ("triplex_connection_type", "enumeration", prop("Describes how the motor will connect to the triplex devices", "TRIPLEX_12",
            keywords=keywords(("TRIPLEX_1N", TPN_1N), ("TRIPLEX_2N", TPN_2N), ("TRIPLEX_12", TPN_12)))),
        ("wb[rad/s]", "double", prop("base speed", access="HIDDEN")),
        _hidden("ws", "double", "system speed"),
        _hidden("psi_b", "complex", "backward rotating flux"),
        _hidden("psi_f", "complex", "forward rotating flux"),
        _hidden("psi_dr", "complex", "Rotor d axis flux"),
        _hidden("psi_qr", "complex", "Rotor q axis flux"),
        _hidden("Ids", "complex", "time before tripped motor reconnects"),
        _hidden("Iqs", "complex", "time before tripped motor reconnects"),
        _hidden("If", "complex", "forward current"),
        _hidden("Ib", "complex", "backward current"),
        _hidden("Is", "complex", "motor current"),
        _hidden("Ss", "complex", "motor power"),
        _hidden("electrical_torque", "double", "electrical torque"),
        _hidden("Vs", "complex", "motor voltage"),
        ("motor_trip", "bool", prop("boolean variable to check if motor is tripped", "FALSE")),
        _hidden("trip", "double", "current time in tripped state"),
        _hidden("reconnect", "double", "current time since motor was tripped"),
        ("rs[pu]", "double", prop("stator resistance", "0.01 pu")),
        ("rr[pu]", "double", prop("rotor resistance", "0.005 pu")),
        ("lm[pu]", "double", prop("magnetizing reactance", "3 pu")),
        ("lls[pu]", "double", prop("stator leakage reactance", "0.1 pu")),
        ("llr[pu]", "double", prop("rotor leakage reactance", "0.08 pu")),
        ("TPIM_rated_mechanical_Load_torque", "double", prop("rated mechanical load torque applied to three-phase induction motor", "0.95")),
        ("friction_coefficient", "double", prop("coefficient of speed-dependent torque", "0")),
        ("TPIM_initial_status", "enumeration", prop("initial status of three-phase induction motor: RUNNING or STATIONARY", "RUNNING",
            keywords=keywords(("RUNNING", 0), ("STATIONARY", 1)))),
        ("wsyn", "double", prop("system frequency in pu", "1", access="HIDDEN")),
        _hidden("phips", "complex", "positive sequence stator flux"),
        _hidden("phins_cj", "complex", "conjugate of negative sequence stator flux"),
        _hidden("phipr", "complex", "positive sequence rotor flux"),
        _hidden("phinr_cj", "complex", "conjugate of negative sequence rotor flux"),
        ("omgr0", "double", prop("dc component of rotor speed", "0.97", access="HIDDEN")),
        ("TL", "double", prop("actually applied mechanical torque", "0.95", access="HIDDEN")),
        _hidden("Ias", "complex", "motor phase-a stator current"),
        _hidden("Ibs", "complex", "motor phase-b stator current"),
        _hidden("Ics", "complex", "motor phase-c stator current"),
        _hidden("Smt", "complex", "motor complex power"),
        _hidden("Vas", "complex", "motor phase-a stator-to-ground voltage"),
        _hidden("Vbs", "complex", "motor phase-b stator-to-ground voltage"),
        _hidden("Vcs", "complex", "motor phase-c stator-to-ground voltage"),
        _hidden("Ips", "complex", "positive sequence stator current"),
        _hidden("Ipr", "complex", "positive sequence rotor current"),
        _hidden("Ins_cj", "complex", "conjugate of negative sequence stator current"),
        _hidden("Inr_cj", "complex", "conjugate of negative sequence rotor current"),
        _hidden("Ls", "double", "stator synchronous reactance"),
        _hidden("Lr", "double", "rotor synchronous reactance"),
        _hidden("sigma1", "double", "intermediate variable 1 associated with synch. react."),
        _hidden("sigma2", "double", "intermediate variable 2 associated with synch. react."),
    )

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`node::init()`, then `motor::init()`; raises `PowerflowError`"""
        # pylint: disable=too-many-locals
        super().init_node(model, name)
        phases = get_int(model, name, "phases")
        count = sum(1 for bit in (PHASE_A, PHASE_B, PHASE_C) if phases & bit)
        if count not in (1, 3):
            raise PowerflowError(f"motor:{name} -- only single-phase or three-phase motors are support")
        tpim = count == 3
        model.objects[name]["motor_operation_type"] = "THREE-PHASE" if tpim else "SINGLE-PHASE"
        triplex = not tpim and bool(phases & PHASE_S)
        connected = -1 if triplex or tpim else max(k for k, bit in enumerate((PHASE_A, PHASE_B, PHASE_C)) if phases & bit)
        vnom = get_double(model, name, "nominal_voltage")
        pbase = get_double(model, name, "base_power")
        ttype = get_int(model, name, "triplex_connection_type")
        ibase = pbase/(2.0*vnom) if triplex and ttype == TPN_12 else pbase/vnom
        wb = 2*math.pi*float(g(model, "nominal_frequency") or 60.0)
        set_double(model, name, "wb", wb)
        lm, lls, llr = (get_double(model, name, x) for x in ("lm", "lls", "llr"))
        ls, lr = lls + lm, llr + lm
        for prop_, value in (("Ls", ls), ("Lr", lr), ("sigma1", ls - lm*lm/lr), ("sigma2", lr - lm*lm/ls)):
            set_double(model, name, prop_, value)
        if tpim:
            if get_int(model, name, "TPIM_initial_status") == 1:
                for prop_ in ("delta_mode_voltage_trigger", "delta_mode_rotor_speed_trigger", "delta_mode_voltage_exit", "delta_mode_rotor_speed_exit"):
                    set_double(model, name, prop_, 110.0)
                set_double(model, name, "omgr0", 0.0)
                set_double(model, name, "TL", 0.0)
            else:
                rated = get_double(model, name, "TPIM_rated_mechanical_Load_torque")
                set_double(model, name, "omgr0", math.sqrt(rated))
                set_double(model, name, "TL", rated)
        state = object_state(model, name)
        state.update(mot_tpim=tpim, mot_triplex=triplex, mot_phase=connected, mot_ibase=ibase,
            mot_ibtpim=pbase/vnom/3.0, mot_last=None, mot_delta=0.0, mot_current={}, mot_psi_sat=1.0)
        state["mot_prev"] = cls._states(model, name)

    #
    # States
    #
    @classmethod
    def _names(cls, model:Any, name:str) -> tuple[str,...]:
        return (TPIM_STATES if object_state(model, name)["mot_tpim"] else SPIM_STATES) + PROTECTION

    @classmethod
    def _states(cls, model:Any, name:str) -> dict[str,Any]:
        """The states gridlabd's `*updateVars()` keep"""
        result = {}
        for prop_ in cls._names(model, name):
            ptype = model.objects[name].oclass.find_property(prop_).ptype
            result[prop_] = get_complex(model, name, prop_) if ptype == "complex" else (get_int(model, name, prop_) if ptype == "bool" else get_double(model, name, prop_))
        result["psi_sat"] = object_state(model, name).get("mot_psi_sat", 1.0)
        return result

    @classmethod
    def _restore(cls, model:Any, name:str, values:dict[str,Any]) -> None:
        """gridlabd's `*reinitializeVars()`"""
        for prop_, value in values.items():
            if prop_ == "psi_sat":
                object_state(model, name)["mot_psi_sat"] = value
            elif isinstance(value, complex):
                set_complex(model, name, prop_, value)
            elif prop_ == "motor_trip":
                model.objects[name]["motor_trip"] = "TRUE" if value else "FALSE"
            else:
                set_double(model, name, prop_, value)

    #
    # Model
    #
    @classmethod
    def read_voltage(cls, model:Any, name:str) -> None:
        """gridlabd `updateFreqVolt()`"""
        state = object_state(model, name)
        vnom = get_double(model, name, "nominal_voltage")
        freq = [get_double(model, name, f"measured_frequency_{x}") for x in "ABC"]
        volts = [get_complex(model, name, f"voltage_{x}") for x in "ABC"]
        if state["mot_tpim"]:
            for x, v in zip(("Vas", "Vbs", "Vcs"), volts):
                set_complex(model, name, x, v/vnom)
            set_double(model, name, "wsyn", sum(freq)/float(g(model, "nominal_frequency") or 60.0)/3.0)
            return
        if state["mot_triplex"]:
            ttype = get_int(model, name, "triplex_connection_type")
            if ttype == TPN_1N:
                vs, f = volts[0]/vnom, freq[0]
            elif ttype == TPN_2N:
                vs, f = volts[1]/vnom, freq[1]
            else:
                vs, f = (volts[0] + volts[1])/(2.0*vnom), freq[0]
        else:
            k = state["mot_phase"]
            vs, f = volts[k]/vnom, freq[k]
        set_complex(model, name, "Vs", vs)
        set_double(model, name, "ws", f*2*math.pi)

    @classmethod
    def protection(cls, model:Any, name:str, dt:float) -> None:
        """gridlabd `SPIMUpdateProtection()` and `TPIMUpdateProtection()`"""
        state = object_state(model, name)
        trip_time, reconnect_time = get_double(model, name, "trip_time"), get_double(model, name, "reconnect_time")
        trip, reconnect = get_double(model, name, "trip"), get_double(model, name, "reconnect")
        tripped = get_int(model, name, "motor_trip") != 0
        energized = cls.energized(model, name)
        if state["mot_tpim"]:
            stalled = get_double(model, name, "omgr0") < 0.01
        else:
            stalled = get_double(model, name, "wr") < 1
        def cool(value:float) -> float:
            value -= dt/(reconnect_time/trip_time)
            return max(value, 0.0)
        if get_int(model, name, "motor_override") == 0:
            if stalled and not tripped and energized:
                trip += dt
            elif (not stalled and not tripped) or not energized:
                trip = cool(trip)
        else:
            trip = cool(trip)
        if tripped:
            reconnect += dt
        if trip >= trip_time:
            tripped, trip = True, 0.0
        if reconnect >= reconnect_time:
            tripped, reconnect = False, 0.0
        set_double(model, name, "trip", trip)
        set_double(model, name, "reconnect", reconnect)
        model.objects[name]["motor_trip"] = "TRUE" if tripped else "FALSE"

    @classmethod
    def energized(cls, model:Any, name:str) -> bool:
        """Grid conditions not "collapsed": speed and voltage"""
        if object_state(model, name)["mot_tpim"]:
            return get_double(model, name, "wsyn") > 0.1 and all(abs(get_complex(model, name, x)) > 0.1 for x in ("Vas", "Vbs", "Vcs"))
        return get_double(model, name, "ws") > 1 and abs(get_complex(model, name, "Vs")) > 0.1

    @classmethod
    def spim_steady(cls, model:Any, name:str) -> None:
        """gridlabd `SPIMSteadyState()`"""
        # pylint: disable=too-many-locals,too-many-statements
        p = {x: get_double(model, name, x) for x in ("n", "Rds", "Rqs", "Xm", "Xr", "Xc_run", "Xc_start", "Xd_prime", "Xq_prime",
            "A_sat", "b_sat", "To_prime", "capacitor_speed", "mechanical_torque", "iteration_count", "maximum_speed_error", "wb", "ws", "wr")}
        vs = get_complex(model, name, "Vs")
        vmag = abs(vs)
        wb, ws, wr, n = p["wb"], p["ws"], p["wr"], p["n"]
        cap_speed = p["capacitor_speed"]*wb/100
        xm, xr = p["Xm"], p["Xr"]
        psi_sat, delta, count = 1.0, 1.0, 1
        ids = iqs = psi_f = psi_b = i_f = i_b = 0j
        telec = 0.0
        while abs(delta) > p["maximum_speed_error"] and count < p["iteration_count"]:
            count += 1
            xc = p["Xc_start"] if wr < cap_speed else p["Xc_run"]
            tf = np.array([
                [1j*p["Xd_prime"]*ws/wb + p["Rds"], 0, 1j*xm*ws/(xr*wb), 1j*xm*ws/(xr*wb)],
                [0, 1j*xc*wb/ws + 1j*p["Xq_prime"]*ws/wb + p["Rqs"], -(xm*n*ws)/(xr*wb), (xm*n*ws)/(xr*wb)],
                [xm/2, -1j*xm*n/2, (1j*wr - 1j*ws)*p["To_prime"] - psi_sat, 0],
                [xm/2, 1j*xm*n/2, 0, (1j*wr + 1j*ws)*-p["To_prime"] - psi_sat]], dtype=complex)
            try:
                itf = np.linalg.inv(tf)
            except np.linalg.LinAlgError:
                break
            ids, iqs, psi_f, psi_b = (complex((itf[k, 0] + itf[k, 1])*vmag) for k in range(4))
            i_f = (ids - 1j*n*iqs)*0.5
            i_b = (ids + 1j*n*iqs)*0.5
            telec = (xm/xr)*2*(i_f.imag*psi_f.real - i_f.real*psi_f.imag - i_b.imag*psi_b.real + i_b.real*psi_b.imag)
            delta = telec - p["mechanical_torque"]
            psi = math.sqrt(abs(psi_f)**2 + abs(psi_b)**2)
            psi_sat = 1.0 if psi <= p["b_sat"] else 1 + p["A_sat"]*(psi - p["b_sat"])**2
            wr = wr + delta if wr + delta > 0 else 0.0
        current = (ids + iqs)*cmath.exp(1j*cmath.phase(vs))
        object_state(model, name)["mot_psi_sat"] = psi_sat
        for prop_, value in (("Ids", ids), ("Iqs", iqs), ("psi_f", psi_f), ("psi_b", psi_b), ("If", i_f), ("Ib", i_b),
                ("psi_dr", psi_f + psi_b), ("psi_qr", 1j*psi_f - 1j*psi_b), ("Is", current), ("Ss", vs*current.conjugate())):
            set_complex(model, name, prop_, value)
        set_double(model, name, "electrical_torque", telec)
        set_double(model, name, "wr", wr)

    @classmethod
    def tpim_steady(cls, model:Any, name:str) -> None:
        """gridlabd `TPIMSteadyState()` (its Cramer's rule solves the
        steady state `M x = -E` of the flux equations)"""
        # pylint: disable=too-many-locals
        p = {x: get_double(model, name, x) for x in ("rs", "rr", "lm", "Ls", "Lr", "sigma1", "sigma2", "wsyn", "omgr0", "TL",
            "iteration_count", "maximum_speed_error", "base_power")}
        vas, vbs, vcs = (get_complex(model, name, x) for x in ("Vas", "Vbs", "Vcs"))
        vap = (vas + ALPHA*vbs + ALPHA**2*vcs)/3.0
        van = (vas + ALPHA**2*vbs + ALPHA*vcs)/3.0
        rs, rr, lm, ls, lr, s1, s2, wsyn = p["rs"], p["rr"], p["lm"], p["Ls"], p["Lr"], p["sigma1"], p["sigma2"], p["wsyn"]
        wref = 0.0
        running = get_int(model, name, "TPIM_initial_status") == 0
        omgr0, tl = p["omgr0"], p["TL"]
        if not running:
            omgr0, tl = 0.0, 0.0
        def solve(speed:float) -> tuple[complex,...]:
            m = np.array([
                [-(1j*(wref + wsyn) + rs/s1), 0, rs/s1*lm/lr, 0],
                [0, -(1j*(wref - wsyn) + rs/s1), 0, rs/s1*lm/lr],
                [rr/s2*lm/ls, 0, -(1j*(wref + wsyn - speed) + rr/s2), 0],
                [0, rr/s2*lm/ls, 0, -(1j*(wref - wsyn - speed) + rr/s2)]], dtype=complex)
            e = np.array([vap, van.conjugate(), 0, 0], dtype=complex)
            phips, phins, phipr, phinr = (complex(x) for x in np.linalg.solve(m, -e))
            ips = (phips - phipr*lm/lr)/s1
            ipr = (phipr - phips*lm/ls)/s2
            ins = (phins - phinr*lm/lr)/s1
            inr = (phinr - phins*lm/ls)/s2
            telec = (phips.conjugate()*ips + phins.conjugate()*ins).imag
            return phips, phins, phipr, phinr, ips, ipr, ins, inr, telec
        if running:
            delta, count = 1.0, 1
            values = solve(omgr0)
            while abs(delta) > p["maximum_speed_error"] and count < p["iteration_count"]:
                count += 1
                values = solve(omgr0)
                delta = (values[-1] - tl)/p["iteration_count"]
                omgr0 = omgr0 + delta if omgr0 + delta > 0 else 0.0
        else:
            values = solve(omgr0)
        phips, phins, phipr, phinr, ips, ipr, ins, inr, _ = values
        ias = ips + ins.conjugate()
        ibs = ALPHA**2*ips + ALPHA*ins.conjugate()
        ics = ALPHA*ips + ALPHA**2*ins.conjugate()
        for prop_, value in (("phips", phips), ("phins_cj", phins), ("phipr", phipr), ("phinr_cj", phinr), ("Ips", ips), ("Ipr", ipr),
                ("Ins_cj", ins), ("Inr_cj", inr), ("Ias", ias), ("Ibs", ibs), ("Ics", ics), ("Smt", (vap*ips.conjugate() + van*ins)*p["base_power"])):
            set_complex(model, name, prop_, value)
        set_double(model, name, "electrical_torque", values[-1])
        set_double(model, name, "omgr0", omgr0)
        set_double(model, name, "TL", tl)

    @classmethod
    def state_off(cls, model:Any, name:str) -> None:
        """gridlabd `SPIMStateOFF()` and `TPIMStateOFF()`"""
        if object_state(model, name)["mot_tpim"]:
            for prop_ in ("phips", "phins_cj", "phipr", "phinr_cj", "Ips", "Ipr", "Ins_cj", "Inr_cj"):
                set_complex(model, name, prop_, 0j)
            set_double(model, name, "omgr0", 0.0)
        else:
            for prop_ in ("psi_b", "psi_f", "psi_dr", "psi_qr", "Ids", "Iqs", "If", "Ib", "Is", "Ss"):
                set_complex(model, name, prop_, 0j)
            set_double(model, name, "electrical_torque", 0.0)
            set_double(model, name, "wr", 0.0)

    @classmethod
    def update_status(cls, model:Any, name:str) -> None:
        """gridlabd `SPIMUpdateMotorStatus()` and `TPIMUpdateMotorStatus()`"""
        tpim = object_state(model, name)["mot_tpim"]
        if get_int(model, name, "motor_override") == 1 or not cls.energized(model, name):
            status = OFF
        elif (get_double(model, name, "omgr0") > 0.0) if tpim else (get_double(model, name, "wr") > 1):
            status = RUNNING
        elif get_int(model, name, "motor_trip"):
            status = TRIPPED
        else:
            status = STALLED
        model.objects[name]["motor_status"] = STATUS_NAMES[status]
        model.objects[name]["motor_status_number"] = str(status)

    @classmethod
    def compute(cls, model:Any, name:str, t0:int) -> dict[str,complex]:
        """`motor::presync()` and `motor::sync()` at time `t0`: the
        fixed currents drawn, by accumulator suffix"""
        # pylint: disable=too-many-branches
        state = object_state(model, name)
        last = state["mot_last"]
        if last is None:
            state["mot_last"] = last = t0
        elif t0 > last:
            state["mot_delta"] = float(t0 - last)
        cls.read_voltage(model, name)
        if t0 == last:
            cls._restore(model, name, state["mot_prev"])
        elif t0 > last:
            state["mot_prev"] = cls._states(model, name)
        cls.protection(model, name, state["mot_delta"])
        on = get_int(model, name, "motor_override") == 0 and cls.energized(model, name) and not get_int(model, name, "motor_trip")
        currents: dict[str,complex] = {}
        if state["mot_tpim"]:
            if on:
                cls.tpim_steady(model, name)
                for x, prop_ in zip("ABC", ("Ias", "Ibs", "Ics")):
                    currents[x] = get_complex(model, name, prop_)*state["mot_ibtpim"]
            else:
                cls.state_off(model, name)
        else:
            if on:
                cls.spim_steady(model, name)
                current = get_complex(model, name, "Is")*state["mot_ibase"]
                if state["mot_triplex"]:
                    currents[("A", "B", "C")[get_int(model, name, "triplex_connection_type")]] = current
                else:
                    currents["ABC"[state["mot_phase"]]] = current
            else:
                cls.state_off(model, name)
        cls.update_status(model, name)
        if t0 > state["mot_last"]:
            state["mot_last"] = t0
        return currents

    #
    # Solution hooks
    #
    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]:
        """The motor's fixed currents"""
        terms = dict(super().load_terms(model, name))
        for suffix, value in object_state(model, name).get("mot_current", {}).items():
            terms[("prerotated_current", suffix)] = terms.get(("prerotated_current", suffix), 0j) + value
        return terms

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        object_state(model, name)["mot_current"] = cls.compute(model, name, t0)

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """Solve the motor again with the solution's voltages; `True` when
        its current changed"""
        state = object_state(model, name)
        old = state.get("mot_current", {})
        new = cls.compute(model, name, t0)
        state["mot_current"] = new
        for key in set(old) | set(new):
            a, b = old.get(key, 0j), new.get(key, 0j)
            if abs(a - b) > 1e-6*max(1.0, abs(b)):
                return True
        return False

__all__ = ["Motor"]
