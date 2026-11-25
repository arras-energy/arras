# pylint: disable=line-too-long
"""Class `dcline`: a PYPOWER DC line

Syntax
------

    object pypower.dcline {
        from <bus>;
        to <bus>;
        fbus <integer>;
        tbus <integer>;
        status {IN,OUT};
        Sfrom <complex> MVA;
        Sto <complex> MVA;
        Vfrom <real> pu.V;
        Vto <real> pu.V;
        Pmin <real> MW;
        Pmax <real> MW;
        Qminf <real> MVAr;
        Qmaxf <real> MVAr;
        Qmint <real> MVAr;
        Qmaxt <real> MVAr;
        loss0 <real> MW;
        loss1 <real> MW/MW;
        control {FROM,TO};
    }

The OPF multipliers `mu_Pmin`, `mu_Pmax`, `mu_Qminf`, `mu_Qmaxf`,
`mu_Qmint`, `mu_Qmaxt` ($/MW) are also published, and the module globals
`pypower::default_dcline_loss0` (MW, 0) and
`pypower::default_dcline_loss1` (MW/MW, 0.05).

Description
-----------

A DC line is a row of PYPOWER's dcline table. Given a model, a DC line is
expected to:

1. refuse a `from` or `to` object that is missing or not a pypower bus,
   and take `fbus` and `tbus` from the buses as a branch does;
2. at initialization, when both `Sfrom` and `Sto` have positive real
   parts, infer `loss1` from them (`(Sto.real+loss0)/Sfrom.real`, or the
   reverse when `Sto` is larger) when `loss1` is 0, or warn and fix the
   line output when the given `loss1` differs from it by more than 1e-6;
   when `loss1` is 0 and cannot be inferred, warn and use the default
   loss globals; otherwise fix the line output;
3. fix the line output at each precommit: an `OUT` line carries nothing;
   with `control TO`, `Sfrom = Sto/(1-loss1) + loss0` limited to
   `Pmin..Pmax` (real) and `Qminf..Qmaxf` (imaginary), then
   `Sto = Sfrom (1-loss1) - loss0`; with `control FROM`, the same from the
   other end.

PYPOWER's `runpf()` and `runopf()` ignore DC line data unless its
`toggle_dcline()` extension is enabled, which the module does not do, so
DC lines do not change the solution (as in gridlabd).

Caveats
-------

- With `control FROM`, `Sto` is limited with `Pmin`, `Pmax`, `Qminf`,
  and `Qmaxf`, the limits of the 'from' end, as gridlabd does.
- The OPF multipliers are copied back from the values sent (columns 17 to
  22 of the sent rows, with `mu_Pmin` and `mu_Pmax` swapped), as gridlabd
  does; PYPOWER does not compute them.

References
----------

- `arras-energy/gridlabd`: `module/pypower/dcline.cpp`, `dcline.h`
"""

from typing import Any

from ._base import PypowerClass, prop, keywords, msg
from ._common import (TS_NEVER, MODULE, fdiv, global_value, isa, ref, get_double, get_complex, get_int,
    set_double, set_complex, set_int, notation)
from ._module import ensure_init

DS_OUT, DS_IN = 0, 1
CP_FROM, CP_TO = 0, 1

class Dcline(PypowerClass):
    """Behavior of class `dcline`"""

    NAME = "dcline"
    PROPERTIES = (
        ("from", "object", prop("'from' bus name", flags="REQUIRED")),
        ("to", "object", prop("'to' bus name", flags="REQUIRED")),
        ("fbus", "int32", prop("'from' bus number", flags="OUTPUT")),
        ("tbus", "int32", prop("'to' bus number", flags="OUTPUT")),
        ("status", "enumeration", prop("initial branch status, IN=1 - in service, OUT=0 - out of service", "IN",
            keywords=keywords(("IN", DS_IN), ("OUT", DS_OUT)))),
        ("Sfrom[MVA]", "complex", prop("MVA flow in at 'from' bus", flags="REQUIRED")),
        ("Sto[MVA]", "complex", prop("MW flow in at 'to' bus", flags="REQUIRED")),
        ("Vfrom[pu.V]", "double", prop("voltage setpoint at 'from' bus (p.u.)", "1 pu.V")),
        ("Vto[pu.V]", "double", prop("voltage setpoint at  'to'  bus (p.u.)", "1 pu.V")),
        ("Pmin[MW]", "double", prop("lower limit on PF (MW flow at 'from' end)")),
        ("Pmax[MW]", "double", prop("upper limit on PF (MW flow at 'from' end)")),
        ("Qminf[MVAr]", "double", prop("lower limit on MVAr injection at 'from' bus")),
        ("Qmaxf[MVAr]", "double", prop("upper limit on MVAr injection at 'from' bus")),
        ("Qmint[MVAr]", "double", prop("lower limit on MVAr injection at  'to'  bus")),
        ("Qmaxt[MVAr]", "double", prop("upper limit on MVAr injection at  'to'  bus")),
        ("loss0[MW]", "double", prop("constant term of linear loss function (MW) on Sfrom")),
        ("loss1[MW/MW]", "double", prop("linear term of linear loss function (MW/MW) w.r.t Sfrom")),
        ("mu_Pmin[$/MW]", "double", prop("Kuhn-Tucker multiplier on lower flow limit at 'from' bus", flags="OUTPUT")),
        ("mu_Pmax[$/MW]", "double", prop("Kuhn-Tucker multiplier on upper flow limit at 'from' bus", flags="OUTPUT")),
        ("mu_Qminf[$/MW]", "double", prop("Kuhn-Tucker multiplier on lower VAr limit at 'from' bus", flags="OUTPUT")),
        ("mu_Qmaxf[$/MW]", "double", prop("Kuhn-Tucker multiplier on upper VAr limit at 'from' bus", flags="OUTPUT")),
        ("mu_Qmint[$/MW]", "double", prop("Kuhn-Tucker multiplier on lower VAr limit at 'to' bus", flags="OUTPUT")),
        ("mu_Qmaxt[$/MW]", "double", prop("Kuhn-Tucker multiplier on upper VAr limit at 'to' bus", flags="OUTPUT")),
        ("control", "enumeration", prop("Control point at which power flow is regulated", "TO",
            keywords=keywords(("FROM", CP_FROM), ("TO", CP_TO)))),
    )
    EVENTS = ("init", "precommit")

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=unused-argument
        """`dcline::init()`"""
        # pylint: disable=too-many-return-statements,too-many-locals
        if not ensure_init(model):
            return False
        out = msg(model, name)
        buses = {}
        for end in ("from", "to"):
            other = ref(model, name, end)
            if other is None:
                out.error(f"{end} bus not specified")
                return False
            if not isa(model, other, "bus"):
                out.error(f"{end} object '{other}' is not a pypower bus")
                return False
            buses[end] = other
        for field, other in (("fbus", buses["from"]), ("tbus", buses["to"])):
            if get_int(model, name, field) == 0:
                number = get_int(model, other, "bus_i")
                if number == 0:
                    return 2
                set_int(model, name, field, number)
        loss0, loss1 = get_double(model, name, "loss0"), get_double(model, name, "loss1")
        loss = calculate_loss(model, name, loss0)
        sfrom, sto = get_complex(model, name, "Sfrom"), get_complex(model, name, "Sto")
        if sfrom.real > 0 and sto.real > 0:
            if loss1 == 0:
                set_double(model, name, "loss1", loss)
            elif abs(loss1-loss) > 1e-6:
                out.warning(f"specified loss function Sto={loss1:.6g}*Sfrom{loss0:+.6g} is inconsistent with Sfrom={sfrom.real:.6g}{sfrom.imag:+.6g}j and Sto={sto.real:.6g}{sto.imag:+.6g}j, fixing line output")
                update(model, name)
        elif loss1 == 0:
            default0 = float(global_value(model, f"{MODULE}::default_dcline_loss0"))
            default1 = float(global_value(model, f"{MODULE}::default_dcline_loss1"))
            out.warning(f"loss1 is not specified and cannot be inferred from initial values of Sfrom and Sto, using default {default1:.6g}*S{default0:+.6g} loss")
            set_double(model, name, "loss0", default0)
            set_double(model, name, "loss1", default1)
        else:
            update(model, name)
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`dcline::precommit()`"""
        update(model, name)
        return TS_NEVER

def calculate_loss(model:Any, name:str, constant:float) -> float:
    """`dcline::calculate_loss()`"""
    sfrom, sto = get_complex(model, name, "Sfrom"), get_complex(model, name, "Sto")
    if sto.real < sfrom.real:
        return fdiv(sto.real+constant, sfrom.real)
    if sfrom.real < sto.real:
        return fdiv(sfrom.real+constant, sto.real)
    return get_double(model, name, "loss1")

def update(model:Any, name:str) -> None:
    """`dcline::update()`"""
    if get_int(model, name, "status") == DS_OUT:
        set_complex(model, name, "Sfrom", 0)
        set_complex(model, name, "Sto", 0)
        return
    loss0, loss1 = get_double(model, name, "loss0"), get_double(model, name, "loss1")
    pmin, pmax = get_double(model, name, "Pmin"), get_double(model, name, "Pmax")
    qmin, qmax = get_double(model, name, "Qminf"), get_double(model, name, "Qmaxf")
    def limit(value:complex) -> complex:
        return complex(min(max(pmin, value.real), pmax), min(max(qmin, value.imag), qmax))
    if get_int(model, name, "control") == CP_TO:
        form = notation(model, name, "Sto")
        sfrom = limit(_div(get_complex(model, name, "Sto"), 1-loss1) + loss0)
        sto = sfrom*(1-loss1) - loss0
    else:
        form = notation(model, name, "Sfrom")
        sto = limit(get_complex(model, name, "Sfrom")*(1-loss1) - loss0)
        sfrom = _div(sto, 1-loss1) + loss0
    set_complex(model, name, "Sfrom", sfrom, form)
    set_complex(model, name, "Sto", sto, form)

def _div(value:complex, divisor:float) -> complex:
    """Division of a complex by a real number as C++ divides doubles"""
    return complex(fdiv(value.real, divisor), fdiv(value.imag, divisor))
