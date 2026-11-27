# pylint: disable=line-too-long
"""Class `frequency_gen`: system frequency from the load at a node

Syntax
------

    object frequency_gen {
        parent <node>;
        Frequency_Mode {OFF,AUTO};
        Frequency <real> Hz;       // nominal at initialization
        Deadband <real> Hz;
        Tolerance <real> %;
        M <real> pu.s;
        D <real> %;
        Rated_power <real> W;
        Gov_delay <real> s;
        Ramp_rate <real> W/s;
        Low_Freq_OI <real> Hz;
        High_Freq_OI <real> Hz;
        Num_Resp_Eqs <integer>;
    }

Outputs: `Frequency`, `FreqChange` (Hz/s), `Gen_power` and `Load_power`
(W), `avg24`, `std24`, `avg168`, `std168` (Hz).

Description
-----------

A `frequency_gen` models the frequency of the system that supplies its
parent node, as gridlabd's `frequency_gen` does (published, like it,
without the `powerflow_object` properties): an equivalent generator with
inertia `M`, load damping `D`, a governor delay, and a ramp rate,
answering the changes of the real power the node draws for its loads and
the links it feeds (gridlabd's `current_inj`). The frequency is a sum of
response terms (a persistent constant and, as the load changes, step and
ramp exponentials with time constant `M / D`), in per unit of the
nominal frequency (the `Frequency` at initialization).

After each solution (`postsync`) of an `AUTO` frequency_gen it reads the
load: the first nonzero load sets the generator power; then, while
matched, a load change beyond the deadband (`Deadband / nominal * D *
Rated_power`) starts a step response and the governor delay, a smaller
one shifts the persistent constant; after the delay the generator ramps
toward the load at `Ramp_rate`, adding step responses for load changes
beyond `Tolerance`; once the generator is within the deadband of the
load, the responses collapse into one that returns to the nominal
frequency. Before each solution of a new time (`presync`) it ends the
responses past their end (folding them into the persistent constant),
computes `Frequency` and `FreqChange`, and keeps hourly samples for the
24-hour and 168-hour means and standard deviations. Its soft events are
the next time the frequency crosses `Low_Freq_OI` or `High_Freq_OI`, the
end of the governor delay, and the end of the ramp. The frequency is an
output only: nothing else in the module uses it.

When it initializes, it is expected to fail unless its parent is a node,
to set `Num_Resp_Eqs` to 20 when it is 0, and to fail when `D` is 0.

Caveats
-------

- When all `Num_Resp_Eqs` response terms are in use, a new response is
  dropped with a warning, as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `std168` is the standard deviation of the 168 hourly samples about
   their mean; gridlabd sums only the 24 latest samples and divides by
   167.
2. The governor delay starts inactive; gridlabd does not initialize it.
3. Removing the responses entered at the current time also clears their
   ramp time; gridlabd keeps it.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/frequency_gen.cpp`,
  `frequency_gen.h`
"""

import math
from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import TS_NEVER, isa, ref, msg, object_state, get_int, get_double, get_complex, set_double, set_int, PowerflowError

OFF, AUTO = 0, 1
"""`Frequency_Mode` values"""

MATCHED, GOV_DELAY, GEN_RAMP = range(3)
"""Generator conditions"""

EMPTY, CONSTANT, PERSCONST, SCALAR, EXPONENT, STEPEXP, RAMPEXP, CSTEPEXP = range(8)
"""Response term types (gridlabd `CT_EMPTY`, ...)"""

def _empty() -> dict[str,Any]:
    return {"a": 0.0, "b": 0.0, "delay": 0.0, "type": EMPTY, "start": TS_NEVER, "end": TS_NEVER, "entered": TS_NEVER}

class FrequencyGen(PowerflowClass):
    """Behavior of class `frequency_gen`"""

    NAME = "frequency_gen"
    TRL = 6 # TRL_DEMONSTRATED
    PASSCONFIG = "PRETOPDOWN|POSTTOPDOWN|AUTOLOCK"
    EVENTS = ("init", "presync", "postsync", "commit")
    PROPERTIES = (
        ("Frequency_Mode", "enumeration", prop("Frequency object operations mode", "AUTO", keywords=keywords(("OFF", OFF), ("AUTO", AUTO)))),
        ("Frequency[Hz]", "double", prop("Instantaneous frequency value", "60 Hz")),
        ("FreqChange[Hz/s]", "double", prop("Frequency change from last timestep")),
        ("Deadband[Hz]", "double", prop("Frequency deadband of the governor", "0.01 Hz")),
        ("Tolerance[%]", "double", prop("% threshold a power difference must be before it is cared about", "0.01 %")),
        ("M[pu.s]", "double", prop("Inertial constant of the system", "10 pu.s")),
        ("D[%]", "double", prop("Load-damping constant", "0.75 %")),
        ("Rated_power[W]", "double", prop("Rated power of system (base power)", "100000000 W")),
        ("Gen_power[W]", "double", prop("Mechanical power equivalent")),
        ("Load_power[W]", "double", prop("Last sensed load value")),
        ("Gov_delay[s]", "double", prop("Governor delay time", "5 s")),
        ("Ramp_rate[W/s]", "double", prop("Ramp ideal ramp rate", "10000000 W/s")),
        ("Low_Freq_OI[Hz]", "double", prop("Low frequency setpoint for GFA devices", "59.95 Hz")),
        ("High_Freq_OI[Hz]", "double", prop("High frequency setpoint for GFA devices", "60.02 Hz")),
        ("avg24[Hz]", "double", prop("Average of last 24 hourly instantaneous measurements")),
        ("std24[Hz]", "double", prop("Standard deviation of last 24 hourly instantaneous measurements")),
        ("avg168[Hz]", "double", prop("Average of last 168 hourly instantaneous measurements")),
        ("std168[Hz]", "double", prop("Standard deviation of last 168 hourly instantaneous measurements")),
        ("Num_Resp_Eqs", "int32", prop("Total number of equations the response can contain", "20")),
    )

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`frequency_gen::init()`"""
        from .node import init_failed # pylint: disable=import-outside-toplevel
        try:
            cls.init_gen(model, name)
        except PowerflowError as err:
            init_failed(model, name, err)
            return False
        return True

    @classmethod
    def init_gen(cls, model:Any, name:str) -> None:
        """The parameters of `frequency_gen::init()`; raises
        `PowerflowError`"""
        nominal = get_double(model, name, "Frequency")
        parent = ref(model, name, "parent")
        if parent is None or not isa(model, parent, "node"):
            raise PowerflowError("Parented object needs to be a node of some sort.")
        if get_int(model, name, "Num_Resp_Eqs") == 0:
            set_int(model, name, "Num_Resp_Eqs", 20)
        count = get_int(model, name, "Num_Resp_Eqs")
        equations = [_empty() for _ in range(count)]
        equations[0]["type"] = PERSCONST
        damping = get_double(model, name, "D")
        if damping == 0:
            raise PowerflowError("The load-damping constant for the frequency_gen object must be non-zero!")
        inertia = get_double(model, name, "M")
        band = get_double(model, name, "Deadband")
        base = get_double(model, name, "Rated_power")
        tau = inertia/damping
        object_state(model, name).update(eqs=equations, nominal=nominal, damping=damping, base=base,
            f_low=get_double(model, name, "Low_Freq_OI"), f_high=get_double(model, name, "High_Freq_OI"),
            p_delta=band/nominal*damping*base, k=1.0/damping, tau=tau, inv_t=-1.0/tau,
            eight_tau=int(tau*8.0), tol=get_double(model, name, "Tolerance")/100.0, ramp=get_double(model, name, "Ramp_rate"),
            gov_delay_s=get_double(model, name, "Gov_delay"), prev_load=0.0, prev_gen=0.0, cond=MATCHED, next_cond=MATCHED,
            ramp_up=False, lockout=False, prev_time=0, next_time=0, dt=0, passes=0, stored=[0.0]*168, loc=0, track=0,
            gov_active=False, gov_delay=0)

    #
    # Response terms
    #
    @classmethod
    def _add(cls, model:Any, name:str, term:dict[str,Any], t0:int) -> bool:
        """Put a term in the first empty slot, or warn"""
        eqs = object_state(model, name)["eqs"]
        for index, eq in enumerate(eqs):
            if eq["type"] == EMPTY:
                eqs[index] = {**_empty(), **term}
                return True
        msg(model, name).warning(f"Failed to process frequency deviation at time {t0}")
        return False

    @classmethod
    def _step(cls, state:dict, power_diff:float, t0:int) -> dict[str,Any]:
        return {"a": power_diff*state["k"], "b": state["inv_t"], "type": STEPEXP, "start": t0, "entered": t0, "end": t0 + state["eight_tau"]}

    @classmethod
    def _ramp(cls, state:dict, rate:float, time_work:float, t0:int, extra:int) -> dict[str,Any]:
        return {"a": rate/state["base"]*state["k"], "b": state["inv_t"], "delay": time_work, "type": RAMPEXP,
            "start": t0, "entered": t0, "end": t0 + state["eight_tau"] + extra}

    @staticmethod
    def remove_scheduled(state:dict, t0:int) -> None:
        """gridlabd `RemoveScheduled()`"""
        for index, eq in enumerate(state["eqs"]):
            if eq["entered"] == t0:
                state["eqs"][index] = _empty()

    @staticmethod
    def _ramp_value(eq:dict, dt:float, always:bool) -> float:
        work = (math.exp(eq["b"]*dt) - 1.0)*(-1.0/eq["b"]) + dt
        if always or dt >= eq["delay"] + 1:
            other = math.exp(eq["b"]*(dt - eq["delay"]))/eq["b"] - 1.0/eq["b"] + eq["delay"] - dt
        else:
            other = 0.0
        return work + other

    @classmethod
    def updatetime(cls, state:dict, t0:int, dt_val:int, freq:float) -> tuple[int,float,float]:
        """gridlabd `updatetime()`: the frequency at `t0`, its change over
        `dt_val` from `freq`, and the next time it crosses a limit"""
        # pylint: disable=too-many-branches
        calced = 1.0
        for eq in state["eqs"]:
            kind = eq["type"]
            active = eq["start"] <= t0 < eq["end"]
            dt = float(t0 - eq["start"]) if active else 0.0
            if kind == PERSCONST:
                calced += eq["a"]
            elif not active or kind == EMPTY:
                continue
            elif kind == CONSTANT:
                calced += eq["a"]
            elif kind == SCALAR:
                calced += eq["a"]*dt
            elif kind == EXPONENT:
                calced += eq["a"]*math.exp(eq["b"]*dt)
            elif kind == STEPEXP:
                calced += eq["a"]*(1.0 - math.exp(eq["b"]*dt))
            elif kind == RAMPEXP:
                calced += eq["a"]*cls._ramp_value(eq, dt, False)
            elif kind == CSTEPEXP:
                calced += eq["a"]*(1.0 - math.exp(eq["b"]*dt)) + eq["delay"]
        calced *= state["nominal"]
        delta = (calced - freq)/dt_val
        low, high = state["f_low"], state["f_high"]
        if calced < low:
            tnext = t0 + int((low - calced)/delta) if delta > 0 else TS_NEVER
        elif low < calced < high:
            if delta > 0:
                tnext = t0 + int((high - calced)/delta)
            elif delta < 0:
                tnext = t0 + int((low - calced)/delta)
            else:
                tnext = TS_NEVER
        elif calced > high:
            tnext = t0 + int((high - calced)/delta) if delta < 0 else TS_NEVER
        else:
            tnext = TS_NEVER
        if tnext == t0:
            tnext = t0 + 1
        return tnext, calced, delta

    @classmethod
    def pres_updatetime(cls, model:Any, name:str, t0:int, dt_val:int) -> int:
        """gridlabd `pres_updatetime()`: fold the ended terms into the
        persistent constant, then update the frequency"""
        state = object_state(model, name)
        eqs = state["eqs"]
        for index, eq in enumerate(eqs):
            if eq["end"] < t0:
                dt = float(t0 - eq["start"])
                if eq["type"] == STEPEXP:
                    final = eq["a"]*(1.0 - math.exp(eq["b"]*dt))
                elif eq["type"] == RAMPEXP:
                    final = eq["a"]*cls._ramp_value(eq, dt, True)
                else:
                    final = 0.0
                for other in eqs:
                    if other["type"] == PERSCONST:
                        other["a"] += final
                        break
                eqs[index] = _empty()
        tnext, freq, delta = cls.updatetime(state, t0, dt_val, get_double(model, name, "Frequency"))
        set_double(model, name, "Frequency", freq)
        set_double(model, name, "FreqChange", delta)
        return tnext

    #
    # Events
    #
    @classmethod
    def statistics(cls, model:Any, name:str) -> None:
        """Hourly samples, and their 24-hour and 168-hour means and
        standard deviations"""
        state = object_state(model, name)
        stored, loc = state["stored"], state["loc"]
        stored[loc] = get_double(model, name, "Frequency")
        day = [stored[(loc - k) % 168] for k in range(24)]
        avg24 = sum(day)/24.0
        avg168 = sum(stored)/168.0
        set_double(model, name, "avg24", avg24)
        set_double(model, name, "avg168", avg168)
        set_double(model, name, "std24", math.sqrt(sum((x - avg24)**2 for x in day)/23.0))
        set_double(model, name, "std168", math.sqrt(sum((x - avg168)**2 for x in stored)/167.0))
        state["loc"] = (loc + 1) % 168
        state["track"] += 3600

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int:
        """`frequency_gen::presync()`"""
        state = object_state(model, name)
        if "eqs" not in state:
            return TS_NEVER
        if state["prev_time"] == 0:
            state.update(prev_time=t, next_time=TS_NEVER, track=t)
        if get_int(model, name, "Frequency_Mode") != AUTO:
            return TS_NEVER
        state["dt"] = t - state["prev_time"]
        if state["dt"] > 0:
            state["prev_load"] = get_double(model, name, "Load_power")
            state["prev_gen"] = get_double(model, name, "Gen_power")
            state["prev_time"] = t
            state["lockout"] = False
            state["next_time"] = cls.pres_updatetime(model, name, t, state["dt"])
            state["cond"] = state["next_cond"]
            if t - state["track"] > 3600:
                cls.statistics(model, name)
        if not state["gov_active"]:
            state["gov_delay"] = t + int(state["gov_delay_s"])
        elif state["gov_delay"] < state["next_time"] and t != state["gov_delay"] and state["next_cond"] == GOV_DELAY:
            state["next_time"] = state["gov_delay"]
        return TS_NEVER if state["next_time"] == TS_NEVER else -state["next_time"]

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`commit_frequency_gen()`: a new time step's passes"""
        object_state(model, name)["passes"] = 0
        return TS_NEVER

    @classmethod
    def load_power(cls, model:Any, name:str) -> float:
        """Real power (W) the parent draws for its loads and the links it
        feeds (`V conj(current_inj)`)"""
        from ._module import bus_currents # pylint: disable=import-outside-toplevel
        from .node import top_node # pylint: disable=import-outside-toplevel
        parent = ref(model, name, "parent")
        currents = bus_currents(model, parent) or [0j]*3
        top = top_node(model, parent)
        return sum(get_complex(model, top, f"voltage_{x}")*i.conjugate() for x, i in zip("ABC", currents)).real

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int:
        """`frequency_gen::postsync()`"""
        state = object_state(model, name)
        if "eqs" not in state or get_int(model, name, "Frequency_Mode") != AUTO:
            return TS_NEVER
        load = cls.load_power(model, name)
        set_double(model, name, "Load_power", load)
        if state["prev_load"] == 0.0:
            state["prev_load"] = load
            set_double(model, name, "Gen_power", load)
            return TS_NEVER
        state["passes"] += 1
        power_diff = (state["prev_load"] - load)/state["base"]
        condition = state["cond"]
        if condition == MATCHED:
            cls.matched(model, name, t, load, power_diff)
        elif condition == GOV_DELAY:
            cls.governor(model, name, t, load, power_diff)
        else:
            cls.ramping(model, name, t, load, power_diff)
        return TS_NEVER if state["next_time"] == TS_NEVER else -state["next_time"]

    @classmethod
    def _limit_time(cls, state:dict, power_diff:float, t0:int) -> int:
        """Time the step response of `power_diff` crosses a frequency limit"""
        limit = state["f_low"]/state["nominal"] if power_diff < 0 else state["f_high"]/state["nominal"]
        try:
            return int(-1.0*state["tau"]*math.log(1.0 - ((limit - 1.0)/power_diff/state["k"]))) + t0 + 1
        except (ValueError, ZeroDivisionError):
            return TS_NEVER

    @classmethod
    def matched(cls, model:Any, name:str, t0:int, load:float, power_diff:float) -> None:
        """The `MATCHED` condition"""
        state = object_state(model, name)
        if state["passes"] != 1:
            cls.remove_scheduled(state, t0)
            state["gov_active"] = False
        gen = get_double(model, name, "Gen_power")
        if load < gen - state["p_delta"] or load > gen + state["p_delta"]:
            state["next_cond"] = GOV_DELAY
            state["gov_active"] = True
            cls._add(model, name, cls._step(state, power_diff, t0), t0)
            new_f = get_double(model, name, "Frequency") + power_diff/state["damping"]*state["nominal"]
            tupdate = cls._limit_time(state, power_diff, t0) if new_f <= state["f_low"] or new_f > state["f_high"] else TS_NEVER
            state["next_time"] = state["gov_delay"] if state["gov_delay"] < tupdate else tupdate
        else:
            if power_diff != 0.0:
                for eq in state["eqs"]:
                    if eq["type"] == PERSCONST:
                        eq["a"] += power_diff/state["damping"]
                        break
            state["next_cond"] = MATCHED
            state["next_time"] = TS_NEVER

    @classmethod
    def governor(cls, model:Any, name:str, t0:int, load:float, power_diff:float) -> None:
        """The `GOV_DELAY` condition"""
        state = object_state(model, name)
        if state["passes"] != 1:
            cls.remove_scheduled(state, t0)
        if abs(power_diff) > state["tol"]:
            cls._add(model, name, cls._step(state, power_diff, t0), t0)
        freq = get_double(model, name, "Frequency")
        if t0 >= state["gov_delay"]:
            state["next_cond"] = GEN_RAMP
            diff = get_double(model, name, "Gen_power") - load
            state["ramp_up"] = diff <= 0
            time_work = abs(diff)/state["ramp"]
            extra = int(time_work) + 1
            rate = state["ramp"] if state["ramp_up"] else -state["ramp"]
            if cls._add(model, name, cls._ramp(state, rate, time_work, t0, extra), t0):
                tupdate = cls.updatetime(state, t0 + 1, 1, freq)[0]
                state["next_time"] = min(tupdate, t0 + extra)
        else:
            tupdate = cls.updatetime(state, t0 + 1, 1, freq)[0]
            state["next_time"] = min(tupdate, state["gov_delay"])
            state["next_cond"] = GOV_DELAY
            state["gov_active"] = True

    @classmethod
    def ramping(cls, model:Any, name:str, t0:int, load:float, power_diff:float) -> None:
        """The `GEN_RAMP` condition"""
        # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        state = object_state(model, name)
        ramp = state["ramp"]
        gen = get_double(model, name, "Gen_power") + (ramp if state["ramp_up"] else -ramp)*state["dt"]
        set_double(model, name, "Gen_power", gen)
        state["gov_active"] = False
        eqs = state["eqs"]
        freq = get_double(model, name, "Frequency")
        prev_load = state["prev_load"]

        def extend(time_work:float, extra:int) -> bool:
            for eq in eqs:
                if eq["type"] == RAMPEXP and int(eq["delay"]) + eq["start"] > t0:
                    eq["delay"] += time_work
                    eq["end"] += extra
                    state["lockout"] = True
                    return True
            return False

        def cut() -> None:
            for eq in eqs:
                if eq["type"] == RAMPEXP and int(eq["delay"]) + eq["start"] > t0:
                    eq["delay"] = float(t0 - eq["start"])
                    state["lockout"] = True
                    return

        if abs(power_diff) > state["tol"] and not state["lockout"]:
            if state["passes"] != 1:
                cls.remove_scheduled(state, t0)
            cls._add(model, name, cls._step(state, power_diff, t0), t0)
            work = (gen - load)/state["base"]
            if state["ramp_up"]:
                if work < 0:
                    time_work = (load - prev_load)/ramp
                    extra = int(time_work) + 1
                    if not extend(time_work, extra) and time_work > 0:
                        cls._add(model, name, cls._ramp(state, ramp, time_work, t0, extra), t0)
                else:
                    cut()
                    state["ramp_up"] = False
                    time_work = (gen - load)/ramp
                    cls._add(model, name, cls._ramp(state, -ramp, time_work, t0, int(time_work) + 1), t0)
            else:
                if work > 0:
                    time_work = (prev_load - load)/ramp
                    extra = int(time_work) + 1
                    if not extend(time_work, extra) and time_work > 0:
                        cls._add(model, name, cls._ramp(state, -ramp, time_work, t0, extra), t0)
                else:
                    cut()
                    state["ramp_up"] = True
                    time_work = (load - gen)/ramp
                    cls._add(model, name, cls._ramp(state, ramp, time_work, t0, int(time_work) + 1), t0)
            state["next_cond"] = GEN_RAMP
            done = t0 + int(abs(gen - load)/ramp)
            done = t0 + 1 if done <= t0 else done
            tupdate = cls.updatetime(state, t0 + 1, 1, freq)[0]
            state["next_time"] = min(tupdate, done)
            return
        low, high = prev_load - state["p_delta"], prev_load + state["p_delta"]
        if state["ramp_up"]:
            if state["prev_gen"] < low and gen > high and high - low < ramp:
                gen = prev_load
        elif state["prev_gen"] > high and gen < low and high - low < ramp:
            gen = prev_load
        set_double(model, name, "Gen_power", gen)
        if low < gen < high and not state["lockout"]:
            state["next_cond"] = MATCHED
            state["lockout"] = True
            tupdate = t0 + state["eight_tau"]
            work = (state["nominal"] - freq)/state["nominal"]
            collapsed = False
            for index, eq in enumerate(eqs):
                if eq["type"] in (STEPEXP, RAMPEXP):
                    if not collapsed:
                        eqs[index] = {**_empty(), "type": CSTEPEXP, "a": work, "b": state["inv_t"], "delay": -work,
                            "start": t0, "entered": t0, "end": tupdate}
                        collapsed = True
                    else:
                        eqs[index] = _empty()
            state["next_time"] = tupdate
        else:
            steps = int(abs(gen - load)/ramp)
            done = t0 + (steps if steps != 0 else 1)
            tupdate = cls.updatetime(state, t0 + 1, 1, freq)[0]
            state["next_time"] = min(tupdate, done)
            state["next_cond"] = GEN_RAMP

__all__ = ["FrequencyGen"]
