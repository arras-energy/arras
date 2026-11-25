# pylint: disable=line-too-long
"""Class `load`: a ZIP load on a bus

Syntax
------

    object pypower.load {
        parent <bus>;
        S <complex> MVA;
        Z <complex> MVA;
        I <complex> MVA;
        P <complex> MVA;
        V <complex> pu.V;
        Vn <real> kV;
        status {OFFLINE,ONLINE,CURTAILED};
        response <real> pu;
        controller "<function>";
    }

Description
-----------

A load adds its demand to its parent bus. Given a model, a load is
expected to:

1. refuse a parent that is not a pypower bus;
2. take `Vn` from the bus's `baseKV` when it is not positive (refusing a
   load whose `Vn` cannot be found), and warn when it differs from
   `baseKV` by more than 0.1%;
3. find its `controller` function in the controllers module
   (`pypower::controllers`), when both are given; a name that is not
   found or not callable is an error;
4. set `S` to `Z+I+P` at initialization when `S` is 0 (times
   `1-response` when `CURTAILED`);
5. at each presync, unless `OFFLINE`, set `S = (Z+I+P)` (times
   `1-response` when `CURTAILED`) and add it to the bus's `Pd` and `Qd`;
6. at each sync, call its controller, if any, as
   `controller(NAME, V=, Z=, I=, P=, S=, status=, response=, t=)`, where
   `V` is the load voltage, `Z` is `|V|/Z` (0 when `Z` is 0), `I` is
   `V conj(I)`, `S` is recomputed as in 5, `status` is the status value,
   and `t` the clock; the controller returns a `dict` of properties to set
   (a value that is not accepted is a warning) and optionally `t`, the
   time of its next call; when it sets properties and gives no `t`, the
   load asks to run again at once; a controller that raises stops the run
   when `pypower::stop_on_failure` is true;
7. at each postsync, set `V` to the bus voltage `Vm*Vn` at angle `Va`
   (0 when `OFFLINE`).

Caveats
-------

- `V` holds the voltage in kV although it is published in `pu.V`, as in
  gridlabd.
- A load without a parent adds its demand nowhere.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The angle of `V` is the bus's `Va` in degrees; gridlabd passes the
   degrees to `SetPolar()` as radians.
2. A load without a parent and without a positive `Vn` fails its
   initialization with an error; gridlabd reads the `baseKV` of the
   missing parent.
3. A controller exception is written as one error line (gridlabd prints
   the Python traceback).

References
----------

- `arras-energy/gridlabd`: `module/pypower/load.cpp`, `load.h`
"""

import cmath
import math
from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import (TS_NEVER, TS_INVALID, object_state, isa, parent_of, get_double, get_complex,
    get_int, set_double, set_complex, runner, notation)
from ._module import ensure_init
from . import _controller

LS_OFFLINE, LS_ONLINE, LS_CURTAILED = 0, 1, 2

def clock(model:Any) -> int:
    """The clock (gridlabd `gl_globalclock`): the start time during
    initialization"""
    now = runner().clock
    if now is None:
        now = model.globals.getvalue("starttime")
    return int(now or 0)

class Load(PypowerClass):
    """Behavior of class `load`"""

    NAME = "load"
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|AUTOLOCK|OBSERVER"
    PROPERTIES = (
        ("S[MVA]", "complex", prop("total load (MVA)")),
        ("Z[MVA]", "complex", prop("constant impedance load (MVA)")),
        ("I[MVA]", "complex", prop("constant current load (MVA)")),
        ("P[MVA]", "complex", prop("constant power load (MVA)")),
        ("V[pu.V]", "complex", prop("bus voltage (V)")),
        ("Vn[kV]", "double", prop("nominal voltage (kV)")),
        ("status", "enumeration", prop("load status",
            keywords=keywords(("OFFLINE", LS_OFFLINE), ("ONLINE", LS_ONLINE), ("CURTAILED", LS_CURTAILED)))),
        ("response[pu]", "double", prop("curtailment response as fractional load reduction")),
        ("controller", "char256", prop("controller python function name")),
    )
    EVENTS = ("init", "presync", "sync", "postsync")

    @classmethod
    def state(cls, model:Any, name:str) -> dict[str,Any]:
        """State of a load: `controller` (function or `None`)"""
        return object_state(model, name, lambda: {"controller": None})

    @classmethod
    def _demand(cls, model:Any, name:str) -> complex:
        total = get_complex(model, name, "Z") + get_complex(model, name, "I") + get_complex(model, name, "P")
        if get_int(model, name, "status") == LS_CURTAILED:
            total *= 1.0 - get_double(model, name, "response")
        return total

    @classmethod
    def _kwargs(cls, model:Any, name:str) -> dict[str,Any]:
        v = get_complex(model, name, "V")
        z = get_complex(model, name, "Z")
        return {"V": v, "Z": complex(abs(v))/z if abs(z) > 0 else 0j,
            "I": v*get_complex(model, name, "I").conjugate(), "P": get_complex(model, name, "P")}

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`load::init()`"""
        if not ensure_init(model):
            return False
        out = msg(model, name)
        state = cls.state(model, name)
        parent = parent_of(model, name)
        if parent is not None and not isa(model, parent, "bus"):
            out.error(f"parent '{parent}' is not a pypower bus object")
            return False
        vn = get_double(model, name, "Vn")
        base_kv = get_double(model, parent, "baseKV") if parent is not None else 0.0
        if vn <= 0.0:
            vn = base_kv
            set_double(model, name, "Vn", vn)
            if vn == 0.0:
                out.error("nominal voltage not specified or inferred from bus")
                return False
        elif base_kv > 0 and abs(vn - base_kv) > vn*1e-3:
            out.warning("nominal voltage Vn differs from bus baseKV by more than 0.1%")
        controller = _controller.find(model, name)
        if controller is False:
            return False
        state["controller"] = controller
        if abs(get_complex(model, name, "S")) == 0:
            set_complex(model, name, "S", cls._demand(model, name), notation(model, name, "Z"))
        return True

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`load::presync()`: add the demand to the bus"""
        if get_int(model, name, "status") == LS_OFFLINE:
            return TS_NEVER
        demand = cls._demand(model, name)
        set_complex(model, name, "S", demand, notation(model, name, "Z"))
        if demand != 0:
            parent = parent_of(model, name)
            if parent is not None:
                set_double(model, parent, "Pd", get_double(model, parent, "Pd") + demand.real)
                set_double(model, parent, "Qd", get_double(model, parent, "Qd") + demand.imag)
        return TS_NEVER

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`load::sync()`: call the controller"""
        controller = cls.state(model, name)["controller"]
        if controller is None:
            return TS_NEVER
        kwargs = cls._kwargs(model, name)
        demand = cls._demand(model, name)
        set_complex(model, name, "S", demand, notation(model, name, "Z"))
        kwargs.update(S=demand, status=get_int(model, name, "status"),
            response=get_double(model, name, "response"), t=float(clock(model)))
        result = _controller.call(model, name, controller, kwargs, t)
        if result is None:
            return TS_INVALID
        t1, nchanges = result
        return t if nchanges > 0 and t1 == TS_NEVER else t1

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`load::postsync()`: the bus voltage"""
        if get_int(model, name, "status") != LS_OFFLINE:
            parent = parent_of(model, name)
            if parent is not None:
                vm, va = get_double(model, parent, "Vm"), get_double(model, parent, "Va")
                set_complex(model, name, "V", cmath.rect(vm*get_double(model, name, "Vn"), math.radians(va)), "d")
        else:
            set_complex(model, name, "V", 0)
        return TS_NEVER
