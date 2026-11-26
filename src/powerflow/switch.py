# pylint: disable=line-too-long
"""Class `switch`: a switch on each phase of a link

Syntax
------

    object switch {
        phases {A,B,C}[N];
        from <node>;
        to <node>;
        status {CLOSED,OPEN};
        operating_mode {BANKED,INDIVIDUAL};
        phase_A_state {CLOSED,OPEN};    // also phase_B_state, phase_C_state
        switch_impedance <complex> Ohm; // or switch_resistance, switch_reactance
        // and the other properties of link
    }

Description
-----------

A `switch` is a `link` (gridlabd `PT_INHERIT "link"`) with a switch on each
of its phases, each `CLOSED` or `OPEN`. A closed phase is the admittance
`1/switch_impedance`; an open phase connects nothing, and when a switch
opens the phases of a to node that has no other link, those phases are
taken out of the network with voltage 0 (`Link.SWITCH`, as for fuses).

At initialization, `switch_impedance` is resolved as gridlabd's NR solver
does: a negative resistance becomes `powerflow::default_resistance` and a
negative reactance `-default_resistance` (so the default, `-1-1j`, is
`default_resistance*(1-j)`); a zero resistance or reactance becomes
`default_resistance`, with a warning. `switch_resistance` and
`switch_reactance` are the parts of `switch_impedance` (the last one set
wins, as with gridlabd's shared storage), and all three are written back.

Before each solution the switch applies gridlabd's switch logic
(`switch_object::switch_sync_function()`):

- `BANKED` (the default): when `status` changed, every phase follows it;
  otherwise the phases follow the majority of the phase states (more
  than half closed: all closed and `status` `CLOSED`; less than half: all
  open and `status` `OPEN`; exactly half: all follow `status`). At
  initialization a majority keeps `status` and the phases follow
  `status`;
- `INDIVIDUAL`: `status` `OPEN` opens every phase; `CLOSED` lets each
  phase follow its own state.

`Switch.change_switch_state()` is gridlabd's published `change_switch_state`
(used by `fault_check` and `restoration` when they are ported).

When it initializes, a switch is expected to:

1. initialize as a `link`;
2. fail when it, or either node, is split-phase ("triplex/S-phase
   connections unsupported at this time");
3. resolve its impedance and its phase states as above.

Caveats
-------

- The DC method uses the magnitude of the switch impedance (its default
  reactance is negative), as for fuses; the fast-decoupled methods keep
  the sign.
- Reliability (`eventgen`, `fault_check`, faults, `reliability_operation`)
  and deltamode are not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The status a `BANKED` switch compares with is updated after each
   change; gridlabd never updates it outside meshed fault checking, so
   once `status` differs from its initial value gridlabd's banked phases
   follow `status` and ignore later phase-state changes.
2. The impedance is resolved as for NR with every solver method (FBS is
   solved with NR); gridlabd's FBS sets negative parts to 0.

References
----------

- `arras-energy/gridlabd`: `module/powerflow/switch_object.cpp`,
  `switch_object.h`
"""

from typing import Any

import numpy as np

from ._base import prop, keywords
from ._common import (PHASE_S, PHASE_BITS, LS_OPEN, LS_CLOSED, ref, g, msg, object_state, get_int,
    get_complex, set_complex, set_double, text_to_complex, text_to_double, PowerflowError)
from .link import Link
from .fuse import TRL_QUALIFIED

OPEN, CLOSED = 0, 1
"""Phase states"""

INDIVIDUAL, BANKED = 0, 1
"""`operating_mode` values"""

_STATE_KEYWORDS = keywords(("OPEN", OPEN), ("CLOSED", CLOSED))

DEFAULT_IMPEDANCE = complex(-1, -1)
"""`switch_impedance` set by gridlabd's `create()`"""

class Switch(Link):
    """Behavior of class `switch`"""

    NAME = "switch"
    PARENT = "link"
    TRL = TRL_QUALIFIED
    SWITCH = True
    MAGNITUDE = True
    PROPERTIES = (
        ("phase_A_state", "enumeration", prop("state of phase A switch", "CLOSED", keywords=_STATE_KEYWORDS)),
        ("phase_B_state", "enumeration", prop("state of phase B switch", "CLOSED", keywords=_STATE_KEYWORDS)),
        ("phase_C_state", "enumeration", prop("state of phase C switch", "CLOSED", keywords=_STATE_KEYWORDS)),
        ("operating_mode", "enumeration", prop("switch bank operating mode", "BANKED", keywords=keywords(("INDIVIDUAL", INDIVIDUAL), ("BANKED", BANKED)))),
        ("switch_impedance[Ohm]", "complex", prop("Impedance value of the swtich when closed", "-1-1j Ohm")),
        ("switch_resistance[Ohm]", "double", prop("Resistance portion of impedance value of the switch when it is closed.", "-1 Ohm")),
        ("switch_reactance[Ohm]", "double", prop("Reactance portion of impedance value of the switch when it is closed.", "-1 Ohm")),
    )

    #
    # Initialization
    #
    @classmethod
    def impedance_set(cls, model:Any, name:str) -> complex:
        """`switch_impedance` from it and its parts in the order the object
        set them (the last wins)"""
        value = DEFAULT_IMPEDANCE
        for key, text in model.objects[name].items():
            if key == "switch_impedance":
                value = text_to_complex(text, "Ohm")
            elif key == "switch_resistance":
                value = complex(text_to_double(text, "Ohm"), value.imag)
            elif key == "switch_reactance":
                value = complex(value.real, text_to_double(text, "Ohm"))
        return value

    @classmethod
    def write_impedance(cls, model:Any, name:str, value:complex) -> None:
        """Write the impedance and its parts"""
        set_complex(model, name, "switch_impedance", value)
        set_double(model, name, "switch_resistance", value.real)
        set_double(model, name, "switch_reactance", value.imag)

    @classmethod
    def states(cls, model:Any, name:str) -> list[int]:
        """Phase states A, B, C"""
        return [get_int(model, name, f"phase_{x}_state") for x in "ABC"]

    @classmethod
    def set_states(cls, model:Any, name:str, states:list[int]) -> None:
        """Write the phase states"""
        for x, state in zip("ABC", states):
            model.objects[name][f"phase_{x}_state"] = "CLOSED" if state == CLOSED else "OPEN"

    @classmethod
    def set_status(cls, model:Any, name:str, status:int) -> None:
        """Write `status`"""
        model.objects[name]["status"] = "OPEN" if status == LS_OPEN else "CLOSED"

    @classmethod
    def init_link(cls, model:Any, name:str) -> None:
        """`switch_object::init()` after `link::init()`; raises
        `PowerflowError`"""
        super().init_link(model, name)
        obj = model.objects[name]
        phases = get_int(model, name, "phases") | get_int(model, ref(model, name, "from"), "phases") | get_int(model, ref(model, name, "to"), "phases")
        if phases & PHASE_S == PHASE_S:
            raise PowerflowError(f"switch:{obj.id} - {name} - triplex/S-phase connections unsupported at this time")
        default = float(g(model, "default_resistance") or 1e-4)
        z = cls.impedance_set(model, name)
        real = default if z.real < 0 else z.real
        imag = -default if z.imag < 0 else z.imag
        if real == 0:
            msg(model, name).warning(f"Switch:{name} switch_resistance has been set to zero. This will result singular matrix. Setting to the global default.")
            real = default
        if imag == 0:
            msg(model, name).warning(f"Switch:{name} switch_reactance has been set to zero. This will result singular matrix. Setting to the global default.")
            imag = default
        cls.write_impedance(model, name, complex(real, imag))
        status = get_int(model, name, "status")
        if get_int(model, name, "operating_mode") == BANKED:
            share = cls.closed_share(model, name)
            if share < 0.5:
                status = LS_OPEN
            cls.set_states(model, name, [OPEN if status == LS_OPEN else CLOSED]*3)
        elif status == LS_OPEN:
            cls.set_states(model, name, [OPEN]*3)
        cls.set_status(model, name, status)
        object_state(model, name)["prev_status"] = status

    @classmethod
    def closed_share(cls, model:Any, name:str) -> float:
        """Share of the switch's phases that are closed"""
        phases = get_int(model, name, "phases")
        present = [k for k, bit in enumerate(PHASE_BITS) if phases & bit]
        if not present:
            return 0.0
        states = cls.states(model, name)
        return sum(states[k] == CLOSED for k in present)/len(present)

    #
    # Operation
    #
    @classmethod
    def sync_states(cls, model:Any, name:str) -> None:
        """gridlabd's `switch_sync_function()` (normal mode)"""
        state = object_state(model, name)
        status = get_int(model, name, "status")
        if get_int(model, name, "operating_mode") == BANKED:
            if status == state.get("prev_status", status):
                share = cls.closed_share(model, name)
                if share > 0.5:
                    status = LS_CLOSED
                elif share < 0.5:
                    status = LS_OPEN
            cls.set_states(model, name, [OPEN if status == LS_OPEN else CLOSED]*3)
            cls.set_status(model, name, status)
        elif status == LS_OPEN:
            cls.set_states(model, name, [OPEN]*3)
        state["prev_status"] = status

    @classmethod
    def before_solve(cls, model:Any, name:str, t0:int) -> None:
        """Apply the switch logic"""
        if "prev_status" in object_state(model, name):
            cls.sync_states(model, name)

    @classmethod
    def connected_phases(cls, model:Any, name:str) -> int:
        """The closed phases, or none when `status` is `OPEN`"""
        if get_int(model, name, "status") == LS_OPEN:
            return 0
        phases = get_int(model, name, "phases")
        states = cls.states(model, name)
        return sum(bit for k, bit in enumerate(PHASE_BITS) if phases & bit and states[k] == CLOSED)

    @classmethod
    def admittance(cls, model:Any, name:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
        """`1/switch_impedance` on each closed phase, no shunt"""
        z = cls.impedance(model, name)
        connected = cls.connected_phases(model, name)
        y = np.diag([1/z if connected & bit else 0j for bit in PHASE_BITS])
        return y, -y, -y, y.copy()

    @classmethod
    def impedance(cls, model:Any, name:str) -> complex:
        """The resolved switch impedance (ohms)"""
        return get_complex(model, name, "switch_impedance")

    @classmethod
    def admittance_key(cls, model:Any, name:str) -> tuple:
        """The link's key, the closed phases, and the impedance"""
        return super().admittance_key(model, name) + (cls.connected_phases(model, name), cls.impedance(model, name))

    @classmethod
    def change_switch_state(cls, model:Any, name:str, phase_change:int, state:bool) -> int:
        """gridlabd's published `change_switch_state`: a `BANKED` switch
        opens or closes (`status`); an `INDIVIDUAL` switch opens or closes
        the phases of `phase_change` (bits 4 A, 2 B, 1 C); returns 1"""
        if get_int(model, name, "operating_mode") == BANKED:
            cls.set_switch(model, name, state)
        else:
            states = cls.states(model, name)
            for k, bit in enumerate((4, 2, 1)):
                if phase_change & bit:
                    states[k] = CLOSED if state else OPEN
            cls.set_states(model, name, states)
            cls.sync_states(model, name)
        return 1

    @classmethod
    def set_switch(cls, model:Any, name:str, closed:bool) -> None:
        """gridlabd `set_switch()`: set `status` and, when it changed, every
        phase the switch has"""
        state = object_state(model, name)
        status = LS_CLOSED if closed else LS_OPEN
        cls.set_status(model, name, status)
        if status != state.get("prev_status"):
            phases = get_int(model, name, "phases")
            states = cls.states(model, name)
            for k, bit in enumerate(PHASE_BITS):
                if phases & bit:
                    states[k] = CLOSED if closed else OPEN
            cls.set_states(model, name, states)
            state["prev_status"] = status

__all__ = ["Switch", "OPEN", "CLOSED", "INDIVIDUAL", "BANKED"]
