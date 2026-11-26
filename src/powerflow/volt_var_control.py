# pylint: disable=line-too-long
"""Class `volt_var_control`: integrated volt-VAr control of regulators and
capacitors

Syntax
------

    object volt_var_control {
        control_method {ACTIVE,STANDBY};
        regulator_list "<regulator>[,<regulator>...]";
        capacitor_list "<capacitor>[,<capacitor>...]";
        voltage_measurements "<node>[,<regulator number>][,...]";
        substation_link <link>;
        pf_phase {A,B,C}[|...];
        desired_pf <real>;
        pf_signed {TRUE,FALSE};
        d_max <real>;
        d_min <real>;
        capacitor_delay <real> s;
        regulator_delay <real> s;
        minimum_voltages "<V>[,...]";    // one per regulator, or one for all
        maximum_voltages "<V>[,...]";
        desired_voltages "<V>[,...]";
        max_vdrop "<V>[,...]";
        high_load_deadband "<V>[,...]";
        low_load_deadband "<V>[,...]";
    }

Description
-----------

A `volt_var_control` (IVVC) controls a feeder's regulators and switched
capacitors, as gridlabd's `volt_var_control` does. gridlabd publishes it
without inheriting the `powerflow_object` properties, so it has no
`phases` or `nominal_voltage`.

When it initializes, it is expected to wait for the objects it names to
initialize, then to check `d_max`, `d_min`, and `desired_pf` (signed or
not) and the delays, with gridlabd's errors and warnings; to read the
regulators (each one's delay is its configuration's `time_delay`, else
`regulator_delay`; its tap step up and down is `band_center * regulation`
over `raise_taps` and `lower_taps`), the voltage limits and set points
(one per regulator, one for all, or by default 0.95, 1.05, and 1 times
the regulator's `to` node nominal voltage), and the drop and deadband
settings (by default 1.5, 2, and 1 tap steps); to read the capacitors,
sorted by size (largest first; each one's size is the sum of its
connected phases' `capacitor_X`, its delay its `time_delay`, else
`capacitor_delay`), giving a `MANUAL` capacitor without `pt_phase` its
first connected phase; to read the voltage measurements (a list of nodes
for a single regulator, or pairs of node and regulator number; a
regulator without one measures at its `to` node); and to default
`substation_link` to the first regulator and `pf_phase` to the link's
phases.

During a run, in each `presync` (before the network is solved):

1. when `control_method` changes, an `ACTIVE` controller sets its
   regulators' configurations and its capacitors to `MANUAL` (keeping
   their control modes), a `STANDBY` one restores them; every regulator
   is due at once;
2. when `ACTIVE`, each regulator that is due compares, on its `PT_phase`
   phases, its `to` node voltage `V_to` with the lowest measured voltage
   `V_min`: the set point is `desired + (V_to - V_min)`; above the maximum
   or below the minimum voltage (at `V_to` or `V_min`) it steps down or
   up; otherwise outside the set point plus or minus the deadband (high
   load when the drop exceeds `max_vdrop`, else low load) it steps toward
   the set point, unless the step would cross a limit; `INDIVIDUAL`
   regulators step each phase, `BANK` regulators all three by the first
   `PT_phase` phase; a tap change makes the regulator due again after its
   delay (a soft event).

In each `postsync` (after the network is solved), when `ACTIVE` and no
regulator change is in progress, on the first solution of a time step
and after the capacitor delay: the power factor of the `pf_phase` power
into `substation_link` is compared with `desired_pf`; unsigned, below it,
the first capacitor (largest first) that is closed and whose `d_min`
share of its size exceeds the reactive power opens, or that is open and
whose `d_max` share is below it closes; signed, gridlabd's leading or
lagging rules choose whether to add or remove a capacitor and the
reactive power to correct, falling back to the smallest capacitor; a
switch asks for another solution at once and delays the next switch by
the capacitor's delay.

Caveats
-------

- The regulators and capacitors must not be controlled otherwise while
  the controller is `ACTIVE` (it sets them to `MANUAL`), as in gridlabd.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A phase B set point below the minimum voltage blocks lowering taps
   when one step down would cross the minimum, as on phases A and C;
   gridlabd tests `> minimum` on phase B, which blocks it in the opposite
   case.
2. A banked regulator in the low-load band raises its taps unless the
   upper limit blocks raising; gridlabd tests the lower-limit flag there.
3. A tap limit blocks only the regulator that reaches it; gridlabd's
   `limit_hit` is not reset between banked regulators, so once one
   reaches a limit the later ones of the same pass do not move.
4. A regulator change in progress on any regulator holds off capacitor
   switching; gridlabd keeps only the state of the last regulator it
   processed.
5. `substation_link` defaults to the first regulator, as the warning
   says; gridlabd indexes the regulator list past the regulator it
   checked last (out of range when all are `MANUAL`).
6. A substation power of zero has a power factor of 1; gridlabd divides
   by zero.
7. List items are trimmed of spaces, and a regulator, capacitor, link,
   or node of the wrong class is an error; gridlabd looks up the names as
   written and does not check classes.
8. Every solver method is accepted (FBS is solved with NR, so its
   capacitor switching follows NR's timing); gridlabd accepts only NR and
   FBS.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/volt_var_control.cpp`,
  `volt_var_control.h`
"""

import math
from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import (TS_NEVER, PHASE_A, PHASE_B, PHASE_C, isa, ref, msg, object_state, get_int, get_double, get_complex,
    set_int, PowerflowError)
from .regulator_configuration import MANUAL as REG_MANUAL, BANK
from .capacitor import MANUAL as CAP_MANUAL, CLOSED as CAP_CLOSED, OPEN as CAP_OPEN, Capacitor

STANDBY, ACTIVE = 0, 1
"""`control_method` values"""

BITS = (PHASE_A, PHASE_B, PHASE_C)

DEFER = 2

def _items(text:str) -> list[str]:
    """Comma-separated items (none when the text is empty)"""
    text = str(text or "").strip().strip('"')
    return [] if text == "" else [x.strip() for x in text.split(",")]

def _numbers(text:str) -> list[float]:
    """Comma-separated numbers (gridlabd `dbl_token()`, `strtod()`)"""
    result = []
    for item in _items(text):
        try:
            result.append(float(item))
        except ValueError:
            result.append(0.0)
    return result

def size_sort(sizes:list[float]) -> list[int]:
    """Indexes of the capacitors largest first, as gridlabd's merge sort
    orders them (`size_sorter()`: on equal sizes the right half first)"""
    def merge(index:list[int]) -> list[int]:
        if len(index) <= 1:
            return index
        split = len(index)//2
        left, right = merge(index[:split]), merge(index[split:])
        result = []
        while left and right:
            result.append(left.pop(0) if sizes[left[0]] > sizes[right[0]] else right.pop(0))
        return result + left + right
    return merge(list(range(len(sizes))))

class VoltVarControl(PowerflowClass):
    """Behavior of class `volt_var_control`"""

    NAME = "volt_var_control"
    TRL = 0 # TRL_UNKNOWN: gridlabd sets none
    PASSCONFIG = "PRETOPDOWN|POSTTOPDOWN|AUTOLOCK"
    EVENTS = ("init", "presync", "postsync")
    PROPERTIES = (
        ("control_method", "enumeration", prop("IVVC activated or in standby", "ACTIVE", keywords=keywords(("ACTIVE", ACTIVE), ("STANDBY", STANDBY)))),
        ("capacitor_delay[s]", "double", prop("Default capacitor time delay - overridden by local defintions", "5 s")),
        ("regulator_delay[s]", "double", prop("Default regulator time delay - overriden by local definitions", "5 s")),
        ("desired_pf", "double", prop("Desired power-factor magnitude at the substation transformer or regulator", "0.98")),
        ("d_max", "double", prop("Scaling constant for capacitor switching on - typically 0.3 - 0.6", "0.6")),
        ("d_min", "double", prop("Scaling constant for capacitor switching off - typically 0.1 - 0.4", "0.3")),
        ("substation_link", "object", prop("Substation link, transformer, or regulator to measure power factor")),
        ("pf_phase", "set", prop("Phase to include in power factor monitoring", keywords=keywords(("A", PHASE_A), ("B", PHASE_B), ("C", PHASE_C)))),
        ("regulator_list", "char1024", prop("List of voltage regulators for the system, separated by commas")),
        ("capacitor_list", "char1024", prop("List of controllable capacitors on the system separated by commas")),
        ("voltage_measurements", "char1024", prop("List of voltage measurement devices, separated by commas")),
        ("minimum_voltages", "char1024", prop("Minimum voltages allowed for feeder, separated by commas")),
        ("maximum_voltages", "char1024", prop("Maximum voltages allowed for feeder, separated by commas")),
        ("desired_voltages", "char1024", prop("Desired operating voltages for the regulators, separated by commas")),
        ("max_vdrop", "char1024", prop("Maximum voltage drop between feeder and end measurements for each regulator, separated by commas")),
        ("high_load_deadband", "char1024", prop("High loading case voltage deadband for each regulator, separated by commas")),
        ("low_load_deadband", "char1024", prop("Low loading case voltage deadband for each regulator, separated by commas")),
        ("pf_signed", "bool", prop("Set to true to consider the sign on the power factor.  Otherwise, it just maintains the deadband of +/-desired_pf", "FALSE")),
    )

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=unused-argument
        """`volt_var_control::init()` (handler result: `True`, `False`
        after an error, or 2 to defer)"""
        from ._common import runner # pylint: disable=import-outside-toplevel
        try:
            if cls.deferred(model, name):
                return DEFER
            cls.init_vvc(model, name)
        except PowerflowError as err:
            obj = model.objects[name]
            label = name if name != f"{obj.oclass.name}:{obj.id}" else "unnamed"
            runner().error(f"{label} {obj.oclass.name} (id={obj.id}): {err}")
            return False
        return True

    @classmethod
    def deferred(cls, model:Any, name:str) -> bool:
        """`True` until the objects the controller names have initialized"""
        names = _items(model.get_property(name, "regulator_list")) + _items(model.get_property(name, "capacitor_list"))
        link = ref(model, name, "substation_link")
        if link is not None:
            names.append(link)
        return any(x in model.objects and not object_state(model, x).get("initialized") for x in names)

    @classmethod
    def _object(cls, model:Any, name:str, item:str, cname:str, message:str) -> str:
        if item not in model.objects or not isa(model, item, cname):
            raise PowerflowError(message)
        return item

    @classmethod
    def init_vvc(cls, model:Any, name:str) -> None:
        """The checks and lists of `volt_var_control::init()`; raises
        `PowerflowError`"""
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        out = msg(model, name)
        label = f"volt_var_control {name}"
        signed = get_int(model, name, "pf_signed") != 0
        d_max, d_min, desired_pf = (get_double(model, name, x) for x in ("d_max", "d_min", "desired_pf"))
        if signed:
            if d_max <= 0 or d_max > 1:
                raise PowerflowError(f"{label}: d_max must be a number between 0 and 1")
            if desired_pf <= -1 or desired_pf > 1:
                raise PowerflowError(f"{label}: Desired signed power factor is outside the valid range")
        else:
            if d_max <= 0 or d_max > 1 or d_min <= 0 or d_min > 1:
                raise PowerflowError(f"{label}: d_max and d_min must be a number between 0 and 1")
            if d_min >= d_max:
                raise PowerflowError(f"{label}: d_min must be less than d_max")
            if desired_pf < 0:
                raise PowerflowError(f"{label}: Desired power factor is negative.  Should pf_signed be set?")
            if desired_pf > 1:
                raise PowerflowError(f"{label}: Desired power factor is outside the valid range")
        for prop_, what in (("capacitor_delay", "capacitor_delay"), ("regulator_delay", "regulator_delay")):
            value = get_double(model, name, prop_)
            if value < 0:
                raise PowerflowError(f"{label}: {what} must be a positive number!")
            if value < 1:
                out.warning(f"{label}: {what} should be greater than or equal to 1 to prevent convergence issues.")

        # regulators
        regs = _items(model.get_property(name, "regulator_list"))
        if len(regs) == 1 and regs[0] not in model.objects:
            regs = []
        if not regs:
            raise PowerflowError(f"{label}: regulator_list is empty")
        configs, to_nodes, reg_delay, step_up, step_down = [], [], [], [], []
        for item in regs:
            cls._object(model, name, item, "regulator", f"{label}: item {item} in regulator_list not found")
            config = ref(model, item, "configuration")
            configs.append(config)
            to_nodes.append(ref(model, item, "to"))
            delay = get_double(model, config, "time_delay")
            reg_delay.append(delay if delay != 0 else get_double(model, name, "regulator_delay"))
            center, regulation = get_double(model, config, "band_center"), get_double(model, config, "regulation")
            step_up.append(center*regulation/get_int(model, config, "raise_taps"))
            step_down.append(center*regulation/get_int(model, config, "lower_taps"))
        n = len(regs)
        mins, maxs, dess = (_numbers(model.get_property(name, x)) for x in ("minimum_voltages", "maximum_voltages", "desired_voltages"))
        if not len(mins) == len(maxs) == len(dess):
            out.warning(f"{label}: Desired, minimum, and maximum voltages don't match")
            if mins and maxs and dess:
                mins, maxs, dess = mins[:1], maxs[:1], dess[:1]
            else:
                mins = maxs = dess = []
        minimum, maximum, desired = [], [], []
        for k in range(n):
            if len(dess) == n:
                lo, hi, de = mins[k], maxs[k], dess[k]
            elif len(dess) == 1:
                lo, hi, de = mins[0], maxs[0], dess[0]
            else:
                nominal = get_double(model, to_nodes[k], "nominal_voltage")
                lo, hi, de = 0.95*nominal, 1.05*nominal, nominal
            if lo >= hi:
                raise PowerflowError(f"{label}: Minimum voltage limit on regulator {k+1} must be less than the maximum voltage limit of the system")
            if de < lo or de > hi:
                raise PowerflowError(f"{label}: Desired voltage on regulator {k+1} is outside the minimum and maximum set points.")
            minimum.append(lo)
            maximum.append(hi)
            desired.append(de)
        drops, lows, highs = (_numbers(model.get_property(name, x)) for x in ("max_vdrop", "low_load_deadband", "high_load_deadband"))
        if not len(drops) == len(lows) == len(highs):
            out.warning(f"{label}: VDrop, low V BW, and high V BW don't match")
            if drops and lows and highs:
                drops, lows, highs = drops[:1], lows[:1], highs[:1]
            else:
                drops = lows = highs = []
        vdrop, vbw_low, vbw_high = [], [], []
        for k in range(n):
            if len(drops) == n:
                dr, lo, hi = drops[k], lows[k], highs[k]
            elif len(drops) == 1:
                dr, lo, hi = drops[0], lows[0], highs[0]
            else:
                dr, lo, hi = 1.5*step_up[k], 2.0*step_up[k], step_up[k]
            if dr <= 0:
                raise PowerflowError(f"{label}: Maximum expected voltage drop specified for regulator {k+1} should be a positive non-zero number.")
            if lo <= 0:
                raise PowerflowError(f"{label}: Low loading deadband (bandwidth) for regulator {k+1}  must be a positive non-zero number")
            if hi <= 0:
                raise PowerflowError(f"{label}: High loading deadband (bandwidth) for regulator {k+1} must be a positive non-zero number")
            if hi > lo:
                out.warning(f"{label}: Low loading deadband for regulator {k+1} is expected to be larger than the high loading deadband")
            vdrop.append(dr)
            vbw_low.append(lo)
            vbw_high.append(hi)
        if get_int(model, name, "control_method") == ACTIVE:
            prev_mode = STANDBY if any(get_int(model, c, "Control") != REG_MANUAL for c in configs) else ACTIVE
        else:
            prev_mode = STANDBY
        link = ref(model, name, "substation_link")
        if link is None:
            out.warning(f"{label}: A link to monitor power-factor was not specified, using first regulator.")
            link = regs[0]
        elif not isa(model, link, "link"):
            raise PowerflowError(f"{label}: substation_link is not a powerflow link")

        # capacitors
        caps = _items(model.get_property(name, "capacitor_list"))
        if len(caps) == 1 and caps[0] not in model.objects:
            caps = []
        sizes, cap_delay = [], []
        for item in caps:
            cls._object(model, name, item, "capacitor", f"{label}: item {item} in capacitor_list not found")
            connected = get_int(model, item, "phases_connected")
            if connected & 0x100: # PHASE_D
                size = sum(get_double(model, item, f"capacitor_{x}") for x in "ABC")
            else:
                size = sum(get_double(model, item, f"capacitor_{x}") for x, bit in zip("ABC", BITS) if connected & bit)
            sizes.append(size)
            delay = get_double(model, item, "time_delay")
            cap_delay.append(delay if delay != 0 else get_double(model, name, "capacitor_delay"))
        order = size_sort(sizes)
        caps, sizes, cap_delay = [caps[k] for k in order], [sizes[k] for k in order], [cap_delay[k] for k in order]
        for item in caps:
            if get_int(model, item, "control") == CAP_MANUAL and get_int(model, item, "pt_phase") & 0x07 == 0:
                out.warning(f"Capacitor {item} has no pt_phase set, volt_var_control {name} will pick the first phases_connected")
                connected = get_int(model, item, "phases_connected")
                model.objects[item]["pt_phase"] = "A" if connected & PHASE_A else ("B" if connected & PHASE_B else "C")
        if not caps:
            out.warning(f"{label}: No capacitors specified.")

        # measurements
        items = _items(model.get_property(name, "voltage_measurements"))
        measurements: list[list[str]] = [[] for _ in range(n)]
        pairs = n > 1
        if len(items) == 1 and n != 1:
            raise PowerflowError(f"{label}: A measurement is missing a regulator association")
        if n == 1 and len(items) > 1:
            pairs = items[1] not in model.objects
        elif n == 1 and len(items) == 1 and items[0] not in model.objects:
            raise PowerflowError(f"{label}: Measurement {items[0]} is not a valid node!")
        if pairs:
            if len(items) % 2:
                raise PowerflowError(f"{label}: A measurement is missing a regulator association")
            for k in range(len(items)//2):
                node, number = items[2*k], items[2*k+1]
                if len(number) > 2:
                    raise PowerflowError(f"{label}: Measurement list item pair {k+1} is invalid.")
                try:
                    index = int(float(number)) - 1
                except ValueError:
                    index = -1
                if index < 0 or index > n - 1:
                    raise PowerflowError(f"{label}: Measurement list references a nonexistant regulator {index+1}")
                cls._object(model, name, node, "node", f"{label}: measurement object {node} was not found!")
                measurements[index].append(node)
            for k in range(n):
                if not measurements[k]:
                    measurements[k] = [to_nodes[k]]
                    out.warning(f"{label}: No measurement point specified for reg {k+1} - defaulting to load side of regulator")
        else:
            for node in items:
                cls._object(model, name, node, "node", f"{label}: measurement object {node} was not found!")
                measurements[0].append(node)
            if not measurements[0]:
                measurements[0] = [to_nodes[0]]

        if get_int(model, name, "pf_phase") & 0x07 == 0:
            phases = get_int(model, link, "phases") & 0x07
            model.objects[name]["pf_phase"] = "|".join(x for x, bit in zip("ABC", BITS) if phases & bit) or "A"
            out.warning(f"{label}: Power factor monitored phases not set - defaulting to substation_link phases")
        pf_phase = get_int(model, name, "pf_phase") & 0x07
        if get_int(model, link, "phases") & pf_phase != pf_phase:
            raise PowerflowError(f"{label}: Power factor monitored phases mismatch")
        object_state(model, name).update(regs=regs, configs=configs, to_nodes=to_nodes, reg_delay=reg_delay, step_up=step_up, step_down=step_down,
            minimum=minimum, maximum=maximum, desired=desired, vdrop=vdrop, vbw_low=vbw_low, vbw_high=vbw_high, prev_mode=prev_mode,
            link=link, caps=caps, sizes=sizes, cap_delay=cap_delay, measurements=measurements, t_reg=[TS_NEVER]*n, t_cap=0,
            t_update=False, reg_change=False, first_cycle=True, prev_time=0, prev_reg=[REG_MANUAL]*n, prev_cap=[CAP_MANUAL]*len(caps))

    #
    # Regulators (presync)
    #
    @classmethod
    def _decide(cls, state:dict, r:int, k:int, flags:tuple[int,int], data:dict) -> int:
        """Tap change (-1, 0, 1) of phase `k` of regulator `r` (gridlabd's
        decision tree)"""
        down, up = flags
        limit = data["limit"]
        vmin, vto, vset, vdrop, tap = data["vmin"][k], data["vto"][k], data["vset"][k], data["vdrop"][k], data["taps"][k]
        lo, hi = state["minimum"][r], state["maximum"][r]
        step = state["step_up"][r] if tap > 0 else state["step_down"][r]
        if (vmin > hi or vto > hi) and not limit & down:
            return -1
        if (vmin < lo or vto < lo) and not limit & up:
            return 1
        band = state["vbw_high"][r] if vdrop > state["vdrop"][r] else state["vbw_low"][r]
        if vset + band < vto and not limit & down:
            return 0 if vto - step < lo else -1
        if vset - band > vto and not limit & up:
            return 0 if vto + step > hi else 1
        return 0

    @classmethod
    def regulate(cls, model:Any, name:str, r:int, t0:int) -> bool:
        """One due regulator's tap changes; `True` when a tap changed"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        out = msg(model, name)
        reg, config = state["regs"][r], state["configs"][r]
        pt = get_int(model, config, "PT_phase")
        vmin = [999999999999.0]*3
        for node in state["measurements"][r]:
            phases = get_int(model, node, "phases")
            for k in range(3):
                if phases & BITS[k]:
                    vmin[k] = min(vmin[k], abs(get_complex(model, node, f"voltage_{'ABC'[k]}")))
        vto = [abs(get_complex(model, state["to_nodes"][r], f"voltage_{x}")) for x in "ABC"]
        taps = [get_int(model, reg, f"tap_{x}") for x in "ABC"]
        vdrop, vset = [0.0]*3, [state["desired"][r]]*3
        limit = 0
        for k in range(3):
            if not pt & BITS[k]:
                continue
            vdrop[k] = vto[k] - vmin[k]
            vset[k] = state["desired"][r] + vdrop[k]
            step = state["step_up"][r] if taps[k] > 0 else state["step_down"][r]
            if vset[k] > state["maximum"][r]:
                out.warning(f"volt_var_control {name}: The set point for phase {'ABC'[k]} will exceed the maximum allowed voltage!")
                if vto[k] + step > state["maximum"][r]:
                    limit |= 0x10 << k
            elif vset[k] < state["minimum"][r]:
                out.warning(f"volt_var_control {name}: The set point for phase {'ABC'[k]} will exceed the minimum allowed voltage!")
                if vto[k] - step < state["minimum"][r]:
                    limit |= 0x01 << k
        data = {"limit": limit, "vmin": vmin, "vto": vto, "vset": vset, "vdrop": vdrop, "taps": taps}
        raise_taps, lower_taps = get_int(model, config, "raise_taps"), get_int(model, config, "lower_taps")
        changed = False
        state["t_reg"][r] = TS_NEVER
        if get_int(model, config, "control_level") != BANK:
            for k in range(3):
                change = cls._decide(state, r, k, (0x01 << k, 0x10 << k), data) if pt & BITS[k] else 0
                if change > 0 and taps[k] < raise_taps:
                    taps[k] += 1
                    changed = True
                elif change < 0 and taps[k] > -lower_taps:
                    taps[k] -= 1
                    changed = True
                elif change != 0:
                    taps[k] = raise_taps if change > 0 else -lower_taps
        else:
            k = 0 if pt & PHASE_A else (1 if pt & PHASE_B else 2)
            change = cls._decide(state, r, k, (0x01 << k, 0x10 << k), data)
            if change != 0:
                bound = raise_taps if change > 0 else -lower_taps
                at_limit = [taps[j] >= bound if change > 0 else taps[j] <= bound for j in range(3)]
                if any(at_limit):
                    taps = [bound if at_limit[j] else taps[j] for j in range(3)]
                else:
                    taps = [x + change for x in taps]
                    changed = True
        for x, tap in zip("ABC", taps):
            set_int(model, reg, f"tap_{x}", tap)
        if changed:
            state["t_reg"][r] = t0 + int(state["reg_delay"][r])
        return changed

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int:
        """`volt_var_control::presync()`"""
        state = object_state(model, name)
        if "regs" not in state:
            return TS_NEVER
        t_reg = state["t_reg"]
        pending = any(t < x != TS_NEVER for x in t_reg)
        if state["t_update"]:
            state["t_update"] = False
            t_reg[:] = [TS_NEVER]*len(t_reg)
        state["first_cycle"] = t != state["prev_time"]
        state["prev_time"] = t
        method = get_int(model, name, "control_method")
        if method != state["prev_mode"]:
            if method == ACTIVE:
                for k, config in enumerate(state["configs"]):
                    state["prev_reg"][k] = get_int(model, config, "Control")
                    set_int(model, config, "Control", REG_MANUAL)
                for k, cap in enumerate(state["caps"]):
                    state["prev_cap"][k] = get_int(model, cap, "control")
                    set_int(model, cap, "control", CAP_MANUAL)
            else:
                for k, config in enumerate(state["configs"]):
                    set_int(model, config, "Control", state["prev_reg"][k])
                for k, cap in enumerate(state["caps"]):
                    set_int(model, cap, "control", state["prev_cap"][k])
            t_reg[:] = [t]*len(t_reg)
            state["t_update"] = True
            state["prev_mode"] = method
        changed = False
        if method == ACTIVE:
            for r in range(len(state["regs"])):
                if t_reg[r] <= t or t_reg[r] == TS_NEVER:
                    changed |= cls.regulate(model, name, r, t)
        state["reg_change"] = changed or pending or any(t < x != TS_NEVER for x in t_reg)
        due = min(t_reg)
        return TS_NEVER if due == TS_NEVER else -due

    #
    # Capacitors (postsync)
    #
    @classmethod
    def _bank_status(cls, model:Any, cap:str) -> int:
        pt = get_int(model, cap, "pt_phase")
        x = "A" if pt & PHASE_A else ("B" if pt & PHASE_B else "C")
        return get_int(model, cap, f"switch{x}")

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int:
        """`volt_var_control::postsync()`"""
        # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-return-statements
        state = object_state(model, name)
        if "regs" not in state:
            return TS_NEVER
        t_cap = state["t_cap"]
        if get_int(model, name, "control_method") != ACTIVE or state["reg_change"]:
            return -t_cap if t_cap > t else TS_NEVER
        pf_phase = get_int(model, name, "pf_phase")
        power = sum((get_complex(model, state["link"], f"power_in_{x}") for x, bit in zip("ABC", BITS) if pf_phase & bit), 0j)
        react = power.imag
        signed = get_int(model, name, "pf_signed") != 0
        desired_pf = get_double(model, name, "desired_pf")
        pf = abs(power.real)/abs(power) if power != 0 else 1.0
        if signed and react < 0:
            pf = -pf
        add, correction = False, 0.0
        if signed:
            target = abs(power.real*math.sqrt(1/(desired_pf*desired_pf) - 1)) if desired_pf != 0 else 0.0
            if pf < 0:
                if desired_pf > 0:
                    add, correction = (True, -target - react) if -desired_pf > pf else (False, target + react)
                else:
                    add, correction = False, -target + react
            elif desired_pf > 0:
                add, correction = True, target + react
            else:
                add, correction = (True, -target + react) if -desired_pf > pf else (False, -target + react)
            correction = abs(correction)
            check = True
        else:
            check = pf < desired_pf
        if not (check and state["first_cycle"] and t_cap <= t):
            return -t_cap if t_cap > t else TS_NEVER
        d_max, d_min = get_double(model, name, "d_max"), get_double(model, name, "d_min")
        chosen = None
        for k, cap in enumerate(state["caps"]):
            status = cls._bank_status(model, cap)
            size = state["sizes"][k]
            if signed:
                if status == CAP_CLOSED and not add and correction >= size*d_max:
                    chosen = (k, False)
                elif status == CAP_OPEN and add and correction >= size*d_max:
                    chosen = (k, True)
            elif status == CAP_CLOSED:
                if react < size*d_min:
                    chosen = (k, False)
            elif react > size*d_max:
                chosen = (k, True)
            if chosen:
                break
        if chosen is None and signed and (0 < pf < -desired_pf or (pf < 0 and pf < desired_pf)):
            for k in reversed(range(len(state["caps"]))):
                status = cls._bank_status(model, state["caps"][k])
                if status == CAP_CLOSED and not add:
                    chosen = (k, False)
                    break
                if status == CAP_OPEN and add:
                    chosen = (k, True)
                    break
        if chosen is None:
            return TS_NEVER
        k, closed = chosen
        Capacitor.toggle_bank_status(model, state["caps"][k], closed)
        state["t_cap"] = t + int(state["cap_delay"][k])
        return t

__all__ = ["VoltVarControl", "size_sort"]
