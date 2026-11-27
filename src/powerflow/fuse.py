# pylint: disable=line-too-long
"""Class `fuse`: a link that opens a phase when its current exceeds a limit

Syntax
------

    object fuse {
        phases {A,B,C,N}[|...];
        from <node>;
        to <node>;
        status {CLOSED,OPEN};
        current_limit <real> A;
        mean_replacement_time <real> s;
        repair_dist_type {NONE,EXPONENTIAL};
        fuse_resistance <real> Ohm;
        phase_A_status {GOOD,BLOWN};
        phase_B_status {GOOD,BLOWN};
        phase_C_status {GOOD,BLOWN};
        // and the other properties of link
    }

Description
-----------

`fuse` inherits the properties of `link`. When a fuse initializes, it is
expected to:

1. fail on a split-phase (triplex) circuit;
2. initialize as a `link` (and wait for its nodes when `link` does);
3. fail when `current_limit` is negative, and set it to 9999 A with a
   warning when it is 0;
4. set `mean_replacement_time` to 3600 s with a warning when it is not
   positive, then set `mean_repair_time` to it;
5. set `fuse_resistance` to `powerflow::default_resistance` when it is
   negative (the default, -1 Ohm), or with a warning when it is 0,
   whatever the solver method;
6. when `status` is `OPEN`, set every phase to `BLOWN`.

In the network, each phase the fuse has that is `GOOD` is the admittance
`(1+j)/fuse_resistance`, the admittance gridlabd's NR solver uses
(`From_Y`), with every solver method and no coupling between phases. The
DC method uses the magnitude of the corresponding impedance,
`fuse_resistance/sqrt(2)`, instead of its reactance (`-fuse_resistance/2`,
which would reverse the flow); a `BLOWN` phase, or every phase when `status` is `OPEN`, connects
nothing. A fuse is a switching device: when it disconnects phases of a
node that has no other link, those phases are taken out of the network and
their voltages set to 0, as gridlabd's NR does.

During a run, at each solution:

- before solving, each `BLOWN` phase whose replacement time has come back
  to `GOOD`;
- after solving, each `GOOD` phase whose `current_in_X` magnitude exceeds
  `current_limit` blows (`BLOWN`), with the warnings `Phase X of fuse:NAME
  just blew!- current is I` and `No fault_check object present -
  Newton-Raphson solver may fail!`; the phases that blow in one solution
  share one replacement time: the time plus `mean_replacement_time`, or
  plus a duration drawn from an exponential distribution of that mean when
  `repair_dist_type` is `EXPONENTIAL` (truncated to whole seconds, and
  written to `mean_repair_time`); the time step is then solved again;
- the earliest replacement time is a soft event of the module, with every
  solver method, so the fuse is replaced at that time.

Caveats
-------

- Reliability, faults (`create_fault`, `fix_fault`), and `eventgen` are
  not ported; the published functions of gridlabd's fuse are not
  available.
- A blown fuse that leaves more than one node without a source fails the
  run (no swing bus), as gridlabd's NR fails without `fault_check`, unless
  a `fault_check` that checks on changes (`ONCHANGE` or `ALL`, with
  `reliability_mode` or `grid_association`) takes those nodes out of the
  powerflow.
- The admittance `(1+j)/fuse_resistance` is reproduced from gridlabd,
  although it is not the inverse of the impedance `(1+j)*fuse_resistance`
  that gridlabd's `b_mat` holds.
- The exponential replacement durations come from Python's `random`
  module, seeded with `randomseed` and the object id, so they differ from
  gridlabd's.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A zero `fuse_resistance` is set to `powerflow::default_resistance`, as
   the warning says; gridlabd warns but keeps 0, which makes its matrix
   singular.
2. The earliest replacement time is a soft event with every solver
   method; gridlabd schedules it only with FBS (`fuse::postsync()`), so
   with NR a fuse is replaced at the first time step after its replacement
   time that something else causes.
3. With `FBS` (solved with NR), there is no warning that fuses only work
   for the attached node, since that is an FBS limitation.
4. Fuses work with `FD_XB`, `FD_BX`, and `DC` (gridlabd fails their
   initialization with methods other than FBS and NR, and has neither FD
   nor DC), with NR's admittance; DC uses its impedance magnitude.
5. `fuse_resistance` is checked with every method; gridlabd checks it
   with NR only.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/fuse.cpp`, `fuse.h`,
  `link.cpp` (`NR_init`: switching devices)
"""

import random
from typing import Any

import numpy as np

from ._base import prop, keywords
from ._common import (PHASE_S, PHASE_BITS, LS_OPEN, TS_NEVER, g, msg,
    object_state, get_int, get_double, get_complex, set_double, PowerflowError)
from .link import Link

TRL_QUALIFIED = 8
"""Technology readiness level `TRL_QUALIFIED`"""

BLOWN, GOOD = 0, 1
"""Phase states"""

NONE, EXPONENTIAL = 0, 1
"""Replacement time distributions"""

_STATE_KEYWORDS = keywords(("BLOWN", BLOWN), ("GOOD", GOOD))

class Fuse(Link):
    """Behavior of class `fuse`"""

    NAME = "fuse"
    PARENT = "link"
    TRL = TRL_QUALIFIED
    SWITCH = True
    MAGNITUDE = True
    PROPERTIES = (
        ("phase_A_status", "enumeration", prop(default="GOOD", keywords=_STATE_KEYWORDS)),
        ("phase_B_status", "enumeration", prop(default="GOOD", keywords=_STATE_KEYWORDS)),
        ("phase_C_status", "enumeration", prop(default="GOOD", keywords=_STATE_KEYWORDS)),
        ("repair_dist_type", "enumeration", prop(default="NONE", keywords=keywords(("NONE", NONE), ("EXPONENTIAL", EXPONENTIAL)))),
        ("current_limit[A]", "double", prop(default="9999 A")),
        ("mean_replacement_time[s]", "double", prop("mean time for replacing fuse when blown", "3600 s")),
        ("fuse_resistance[Ohm]", "double", prop("The resistance value of the fuse when it is not blown.", "-1 Ohm")),
    )

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`fuse::init()` around `link::init()`; raises `PowerflowError`"""
        if get_int(model, name, "phases") & PHASE_S == PHASE_S:
            raise PowerflowError("fuses cannot be placed on triplex circuits")
        super().init_link(model, name)
        out = msg(model, name)
        limit = get_double(model, name, "current_limit")
        if limit < 0:
            raise PowerflowError(f"fuse:{name} has a negative current limit value!")
        if limit == 0:
            set_double(model, name, "current_limit", 9999.0)
            out.warning(f"fuse:{name} has a zero current limit - set to 9999.9 Amps")
        if get_double(model, name, "mean_replacement_time") <= 0:
            out.warning(f"Fuse:{name} has a negative or 0 mean replacement time - defaulting to 1 hour")
            set_double(model, name, "mean_replacement_time", 3600.0)
        set_double(model, name, "mean_repair_time", get_double(model, name, "mean_replacement_time"))
        resistance = get_double(model, name, "fuse_resistance")
        if resistance == 0:
            out.warning(f"Fuse:{name} fuse_resistance has been set to zero. This will result singular matrix. Setting to the global default.")
        if resistance <= 0:
            set_double(model, name, "fuse_resistance", float(g(model, "default_resistance") or 1e-4))
        if get_int(model, name, "status") == LS_OPEN:
            for x in "ABC":
                model.objects[name][f"phase_{x}_status"] = "BLOWN"
        object_state(model, name)["fix_time"] = [TS_NEVER]*3

    @classmethod
    def _good(cls, model:Any, name:str, k:int) -> bool:
        return get_int(model, name, f"phase_{'ABC'[k]}_status") == GOOD

    @classmethod
    def connected_phases(cls, model:Any, name:str) -> int:
        """The phases that are `GOOD`, or none when `status` is `OPEN`"""
        if get_int(model, name, "status") == LS_OPEN:
            return 0
        phases = get_int(model, name, "phases")
        return sum(bit for k, bit in enumerate(PHASE_BITS) if phases & bit and cls._good(model, name, k))

    @classmethod
    def admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """`(1+j)/fuse_resistance` on each connected phase, no shunt"""
        resistance = get_double(model, name, "fuse_resistance")
        connected = cls.connected_phases(model, name)
        y = np.diag([complex(1, 1)/resistance if connected & bit else 0j for bit in PHASE_BITS])
        return y, -y, -y, y.copy()

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        """The link's key, the connected phases, and the resistance"""
        return super().admittance_key(model, name) + (cls.connected_phases(model, name), get_double(model, name, "fuse_resistance"))

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """Replace the blown phases whose replacement time has come"""
        if get_int(model, name, "status") == LS_OPEN:
            for x in "ABC":
                model.objects[name][f"phase_{x}_status"] = "BLOWN"
            return
        fix = object_state(model, name).setdefault("fix_time", [TS_NEVER]*3)
        phases = get_int(model, name, "phases")
        for k, bit in enumerate(PHASE_BITS):
            if fix[k] <= t0 and phases & bit:
                model.objects[name][f"phase_{'ABC'[k]}_status"] = "GOOD"
                fix[k] = TS_NEVER

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """Blow the phases whose current exceeds the limit"""
        state = object_state(model, name)
        fix = state.setdefault("fix_time", [TS_NEVER]*3)
        limit = get_double(model, name, "current_limit")
        connected = cls.connected_phases(model, name)
        out = msg(model, name)
        replacement = None
        for k, bit in enumerate(PHASE_BITS):
            if not connected & bit:
                continue
            current = abs(get_complex(model, name, f"current_in_{'ABC'[k]}"))
            if current > limit:
                model.objects[name][f"phase_{'ABC'[k]}_status"] = "BLOWN"
                out.warning(f"Phase {'ABC'[k]} of fuse:{name} just blew!- current is {current:f}")
                if replacement is None:
                    replacement = t0 + cls._duration(model, name)
                fix[k] = replacement
        if replacement is None:
            return False
        out.warning("No fault_check object present - Newton-Raphson solver may fail!")
        return True

    @classmethod
    def _duration(cls, model:Any, name:str) -> int:
        """Replacement duration (s), also written to `mean_repair_time`"""
        mean = get_double(model, name, "mean_replacement_time")
        if get_int(model, name, "repair_dist_type") == EXPONENTIAL:
            state = object_state(model, name)
            if "rng" not in state:
                seed = int(model.globals.getvalue("randomseed") or 0)
                state["rng"] = random.Random(seed*1000003 + model.objects[name].id)
            duration = state["rng"].expovariate(1.0/mean)
        else:
            duration = mean
        set_double(model, name, "mean_repair_time", duration)
        return int(duration)

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        """The earliest replacement time"""
        fix = [t for t in object_state(model, name).get("fix_time", []) if t != TS_NEVER]
        return min(fix) if fix else None
