# pylint: disable=line-too-long
"""Class `switch_coordinator`: coordinated operation of a set of switches

Syntax
------

    object switch_coordinator {
        connect "<switch>[|<switch>...]";
        arm "<switch>";                 // may be repeated
        disarm "<switch>";
        status {IDLE,ARMED,TOGGLE,DIRECT};
    }

Output: `armed`, the set of armed switches.

Description
-----------

A `switch_coordinator` operates several switches in the same time step,
as gridlabd's `switch_coordinator` does. gridlabd publishes `connect`,
`arm`, and `disarm` as methods; here they are `method` properties, whose
values the coordinator applies when it initializes and, when a value is
written later (by a player, for example), at the next time step
(`precommit`), clearing the property after it applies it:

- `connect` adds each `|`- or `,`-separated switch to the coordinator (at
  most 63), each a keyword of `armed` (gridlabd adds the keywords to the
  class, so all coordinators of a model share them); a name that is not
  an object is warned about and stops the list, one that is not a switch
  is an error;
- `arm` and `disarm` add a connected switch to `armed` or take it out
  (an error when it is not connected); either one turns an `IDLE`
  coordinator `ARMED`.

When `status` is set to `TOGGLE`, the coordinator records the switches'
states before the time step (`precommit`) and, in the sync pass (before
the network is solved), toggles every armed switch; when it is `DIRECT`,
it closes every armed switch and opens every other connected one. Then,
when the time step is committed, it clears `armed` and returns to `IDLE`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The last switch connected can be armed and disarmed; gridlabd's
   keyword search stops before the last keyword, so it reports that the
   last switch is not connected.
2. Up to 63 switches can be operated; gridlabd's error message says 32,
   and its bit masks (`1<<n`, an `int`) do not reach the switches past
   the 31st.
3. Method values are applied from the property values (at initialization
   and when they are written); gridlabd calls the methods as the values
   are set.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/switch_coordinator.cpp`,
  `switch_coordinator.h`
"""

import re
from typing import Any

from ._base import PowerflowClass, prop, keywords
from ._common import TS_NEVER, LS_OPEN, isa, msg, object_state, get_int

IDLE, ARMED, TOGGLE, DIRECT = range(4)
"""`status` values"""

STATUS_NAMES = ("IDLE", "ARMED", "TOGGLE", "DIRECT")

MAX_SWITCHES = 63

METHODS = ("connect", "arm", "disarm")

def _names(text:Any) -> list[str]:
    return [x for x in re.split(r"[|,]", str(text or "").strip().strip('"')) if x.strip()]

class SwitchCoordinator(PowerflowClass):
    """Behavior of class `switch_coordinator`"""

    NAME = "switch_coordinator"
    TRL = 9 # TRL_PROVEN
    PASSCONFIG = "BOTTOMUP|AUTOLOCK|OBSERVER"
    EVENTS = ("init", "precommit", "sync", "commit")
    PROPERTIES = (
        ("status", "enumeration", prop("switch coordination status", "IDLE",
            keywords=keywords(("IDLE", IDLE), ("ARMED", ARMED), ("TOGGLE", TOGGLE), ("DIRECT", DIRECT)))),
        ("arm", "method", prop("method to arm a switch")),
        ("disarm", "method", prop("method to disarm a switch")),
        ("connect", "method", prop("method to connect switches")),
        ("armed", "set", prop("set of armed switches", flags="OUTPUT", keywords=keywords(("NONE", 0)))),
    )

    #
    # Methods
    #
    @classmethod
    def connect(cls, model:Any, name:str, text:str) -> bool:
        """gridlabd `switch_coordinator::connect()`"""
        out = msg(model, name)
        state = object_state(model, name)
        armed = model.objects[name].oclass.find_property("armed")
        for item in _names(text):
            item = item.strip()
            if item == "NONE":
                continue
            if item not in model.objects:
                out.warning(f"object '{item}' is not found")
                return False
            if not isa(model, item, "switch"):
                out.error(f"object '{item}' is not a switch")
                return False
            if len(state["switches"]) >= MAX_SWITCHES:
                out.error(f"too many switches connected (max {MAX_SWITCHES}) to connect '{item}'")
                return False
            if armed.keywords is not None and item not in armed.keywords:
                armed.keywords[item] = 1 << len(state["switches"])
            state["switches"].append(item)
            out.verbose(f"added switch '{item}' to arming list")
        return True

    @classmethod
    def arm(cls, model:Any, name:str, text:str, armed:bool=True) -> bool:
        """gridlabd `arm()` and `disarm()`"""
        out = msg(model, name)
        state = object_state(model, name)
        what = "arm" if armed else "disarm"
        for item in _names(text):
            item = item.strip()
            if item == "NONE":
                bit = 0
            elif item in state["switches"]:
                bit = 1 << state["switches"].index(item)
            else:
                out.error(f"unable to {what} '{item}', no such device connected")
                return False
            state["armed"] = state["armed"] | bit if armed else state["armed"] & ~bit
            out.verbose(f"{what}ing switch '{item}'")
            if get_int(model, name, "status") == IDLE:
                out.verbose("first switch armed--changing status to ARMED")
                cls.set_status(model, name, ARMED)
            cls.write_armed(model, name)
        return True

    @classmethod
    def set_status(cls, model:Any, name:str, status:int) -> None:
        """Set `status`"""
        model.objects[name]["status"] = STATUS_NAMES[status]

    @classmethod
    def write_armed(cls, model:Any, name:str) -> None:
        """`armed` from the armed bits"""
        state = object_state(model, name)
        names = [x for k, x in enumerate(state["switches"]) if state["armed"] & (1 << k)]
        model.objects[name]["armed"] = "|".join(names) if names else "NONE"

    @classmethod
    def apply_methods(cls, model:Any, name:str) -> bool:
        """Apply the method values written since the last time, and clear
        them"""
        ok = True
        for method in METHODS:
            text = str(model.objects[name].get(method) or "").strip().strip('"')
            if not text:
                continue
            if method == "connect":
                ok = cls.connect(model, name, text) and ok
            else:
                ok = cls.arm(model, name, text, method == "arm") and ok
            model.objects[name][method] = ""
        return ok

    #
    # Events
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """The methods given to the object, then `init()`"""
        object_state(model, name).update(switches=[], armed=0, states=0)
        if not cls.apply_methods(model, name):
            return False
        cls.write_armed(model, name)
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """Methods written since the last time, then `precommit()`: the
        states toggled by `TOGGLE`"""
        state = object_state(model, name)
        if "switches" not in state:
            return TS_NEVER
        cls.apply_methods(model, name)
        if get_int(model, name, "status") == TOGGLE:
            states = state["armed"]
            for k, switch in enumerate(state["switches"]):
                msg(model, name).verbose(f"recording state of '{switch}.status'")
                states ^= 0 if get_int(model, switch, "status") == LS_OPEN else 1 << k
            state["states"] = states
        return TS_NEVER

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`sync()`: operate the switches"""
        state = object_state(model, name)
        if "switches" not in state:
            return TS_NEVER
        out = msg(model, name)
        status = get_int(model, name, "status")
        if status == TOGGLE:
            out.verbose(f"activating toggle scheme with armed={model.objects[name].get('armed')})")
            for k, switch in enumerate(state["switches"]):
                if state["armed"] & (1 << k):
                    model.objects[switch]["status"] = "CLOSED" if state["states"] & (1 << k) else "OPEN"
        elif status == DIRECT:
            out.verbose(f"activating direct scheme with armed={model.objects[name].get('armed')})")
            for k, switch in enumerate(state["switches"]):
                new = "CLOSED" if state["armed"] & (1 << k) else "OPEN"
                old = "OPEN" if get_int(model, switch, "status") == LS_OPEN else "CLOSED"
                if old != new:
                    out.verbose(f"setting state for index[{k}]='{switch}.status' = {old} -> {new}")
                    model.objects[switch]["status"] = new
        else:
            out.verbose(f"no action, status={STATUS_NAMES[status]}")
        return TS_NEVER

    @classmethod
    def commit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`commit()`: back to `IDLE` after switching"""
        state = object_state(model, name)
        if "switches" in state and get_int(model, name, "status") in (TOGGLE, DIRECT):
            state["armed"] = 0
            cls.write_armed(model, name)
            cls.set_status(model, name, IDLE)
            msg(model, name).verbose("switching done--changing status to IDLE")
        return TS_NEVER

__all__ = ["SwitchCoordinator"]
