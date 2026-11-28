# pylint: disable=line-too-long
"""Class `residential_enduse`: the base of the residential enduse loads

Syntax
------

    object residential_enduse {
        parent <house>;
        shape <loadshape>;
        override {NORMAL,ON,OFF};
        power_state {OFF,ON,UNKNOWN};
        // and the parts of the enduse load:
        constant_power <complex> kVA;
        constant_current <complex> kVA;
        constant_admittance <complex> kVA;
        heatgain_fraction <real> pu;
        breaker_amps <real> A;
        configuration {IS110,IS220};
        ...
    }

Description
-----------

A `residential_enduse` is a load that a `house` supplies through a
circuit of its panel. Its properties are those of the core's `enduse`
structure as `enduse_publish()` publishes them (`load`, `energy`, `power`,
`peak_demand`, `heatgain`, the ZIP fractions and parts, `voltage_factor`,
`breaker_amps`, `configuration`), its `shape`, `override`, and
`power_state`. The classes `house` and `ZIPload` inherit from it.

When it initializes, an enduse is expected to attach its load to a
circuit of its parent's panel when the parent is a `house` (gridlabd's
`attach_enduse` function): a 240 V circuit when `configuration` has
`IS220`, else a 120 V circuit, with `breaker_amps` as the breaker rating.
With a parent that is not a house it warns that the voltage response
cannot be modeled, as gridlabd does, and without a parent it is not
attached. The house then supplies the circuit voltage, from which
`voltage_factor` follows, and adds the load to its panel and to its
parent meter.

Each time step, as gridlabd's core does for every enduse before the
object passes (`enduse_syncall()`), `energy` accumulates `power` over the
time since the last step, `cumulative_heatgain` accumulates `heatgain`,
and `heatgain` is cleared when the time advanced. When the object
synchronizes (bottom-up), a `voltage_factor` outside 0.8 to 1.2 is
reported as a verbose message.

Caveats
-------

- `shape` is published, but loadshapes and schedules are not modeled by
  `arras`; an enduse whose class does not compute its load (such as a
  plain `residential_enduse`) keeps the ZIP parts it is given and draws
  `power = constant_power + constant_current + constant_admittance`
  only when the class computes it (gridlabd's `enduse_sync()` bottom-up
  pass is called by the classes that use a loadshape, which are not
  ported).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/residential/residential_enduse.cpp`,
  `residential_enduse.h`, `residential.h`, `source/enduse.cpp`
- [Residential enduse](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Residential/Residential_enduse.md)
  (`docs/Module/Residential/Residential_enduse.md`)
"""

from typing import Any

from ._base import ResidentialClass, prop, keywords, enduse_properties
from ._common import (TS_NEVER, INIT_DEFER, EUC_IS220, OV_NORMAL, OV_ON, OV_OFF, PS_OFF, PS_ON, PS_UNKNOWN,
    Members, Enduse, enduse_map, msg, isa, parent_of, module_state, object_state, init_failed, sync_failed)

class EnduseMembers(Members):
    """The published members of a residential enduse"""

    MAP = (
        *enduse_map("load"),
        ("re_override", "override", "i"),
        ("power_state", "power_state", "i"),
    )

    def __init__(self, model:Any, name:str):
        super().__init__(model, name)
        self.load = Enduse()
        self.load.curtailment_fraction = 0.0 # object memory is zeroed; enduse_create() does not set it
        self.re_override = OV_NORMAL
        self.power_state = PS_UNKNOWN

class EnduseView(Members):
    """The enduse members of an object, as a house panel reads and writes
    them through its circuit"""

    MAP = enduse_map("load")

    def __init__(self, model:Any, name:str, load:Enduse):
        super().__init__(model, name)
        self.load = load

def view(model:Any, name:str) -> EnduseView:
    """The panel's view of an enduse object (kept in the object's state)"""
    st = object_state(model, name)
    if "view" not in st:
        st["view"] = EnduseView(model, name, st["members"].load if "members" in st else Enduse())
    return st["view"]

class ResidentialEnduse(ResidentialClass):
    """Behavior of class `residential_enduse`"""

    NAME = "residential_enduse"
    PASSCONFIG = "BOTTOMUP|AUTOLOCK"
    EVENTS = ("init", "sync")
    MEMBERS: type = EnduseMembers
    """Class of the object's members"""

    PROPERTIES = (
        ("shape", "loadshape", prop()),
        *enduse_properties(),
        ("override", "enumeration", prop(None, "NORMAL", keywords=keywords(("NORMAL", OV_NORMAL), ("ON", OV_ON), ("OFF", OV_OFF)))),
        ("power_state", "enumeration", prop(None, "OFF", keywords=keywords(("OFF", PS_OFF), ("ON", PS_ON), ("UNKNOWN", PS_UNKNOWN)))),
    )

    CREATE: dict[str,Any] = {
        "load.breaker_amps": 20.0,
        "load.config": 0,
        "load.heatgain_fraction": 1.0,
        "re_override": OV_NORMAL,
        "power_state": PS_UNKNOWN,
    }
    """Members that the class's `create()` sets (`residential_enduse::create()`),
    applied when the model does not set them; published properties of the
    class itself carry these values as their defaults instead"""

    @classmethod
    def members(cls, model:Any, name:str) -> Any:
        """The object's members (kept in its state)"""
        st = object_state(model, name)
        if "members" not in st:
            st["members"] = cls.MEMBERS(model, name)
        return st["members"]

    @classmethod
    def clock(cls, model:Any, name:str, t:int) -> int:
        """The object's clock as gridlabd keeps it (`obj->clock`): the
        time of its last bottom-up pass, `t` before the first"""
        st = object_state(model, name)
        if "clock" not in st:
            st["clock"] = t
        return st["clock"]

    @classmethod
    def set_clock(cls, model:Any, name:str, t:int) -> None:
        """Set the object's clock"""
        object_state(model, name)["clock"] = t

    #
    # Event handlers
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=unused-argument
        """`init_CLASS()`: `create()` is applied once, then `init()`;
        exceptions are written as `INIT_CATCHALL()` writes them"""
        m = cls.members(model, name)
        m.read()
        st = object_state(model, name)
        if not st.get("created"):
            cls.create(model, name, m)
            st["created"] = True
        try:
            result = cls.init_object(model, name, m)
        except Exception as err: # pylint: disable=broad-exception-caught
            init_failed(model, name, err)
            return False
        m.write()
        if result is True or result == 1:
            module_state(model).initialized.add(name)
            return True
        return result

    @classmethod
    def create(cls, model:Any, name:str, m:Any) -> None:
        """Apply `CREATE` to the members whose properties the model does not
        set"""
        obj = model.objects[name]
        for member, value in cls.CREATE.items():
            props = [p for mem, p, _ in m.MAP if mem == member]
            if not any(obj.get(p) not in (None, "") for p in props):
                m._set(member, value) # pylint: disable=protected-access

    @classmethod
    def init_object(cls, model:Any, name:str, m:Any) -> bool|int:
        """`residential_enduse::init()`: attach the load to the parent's
        panel"""
        parent = parent_of(model, name)
        if parent is not None:
            from .house import House # pylint: disable=import-outside-toplevel
            if isa(model, parent, "house"):
                if parent not in module_state(model).initialized:
                    msg(model, name).verbose(f"{cls.NAME}::init(): deferring initialization on {parent}")
                    return INIT_DEFER
                v = view(model, name)
                v.load = m.load
                object_state(model, name)["house"] = parent
                object_state(model, name)["circuit"] = House.attach(model, parent, name, v, m.load.breaker_amps, (m.load.config & EUC_IS220) != 0)
            else:
                obj, pobj = model.objects[name], model.objects[parent]
                msg(model, name).warning(f"{name} ({obj.oclass.name}:{obj.id}) parent {parent} ({pobj.oclass.name}:{pobj.id}) does not export attach_enduse function so voltage response cannot be modeled")
        msg(model, name).verbose(f"{name} ({model.objects[name].oclass.name}:{model.objects[name].id}) schedule is not specified so the load may be inactive")
        return True

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`sync_CLASS()`: the class's `sync(obj->clock, t)`, then the
        clock is set to `t`"""
        m = cls.members(model, name)
        m.read()
        t0 = cls.clock(model, name, t)
        try:
            t2 = cls.sync_object(model, name, m, t0, t)
        except Exception as err: # pylint: disable=broad-exception-caught
            sync_failed(model, name, err)
            return -1
        m.write()
        cls.set_clock(model, name, t)
        return t2

    @classmethod
    def sync_object(cls, model:Any, name:str, m:Any, t0:int, t1:int) -> int: # pylint: disable=unused-argument
        """`residential_enduse::sync()`"""
        vf = m.load.voltage_factor
        if vf > 1.2 or vf < 0.8:
            msg(model, name).verbose(f"{name} voltage is out of normal +/- 20% range of nominal (vf={vf:.2f})")
        return TS_NEVER

    @classmethod
    def circuit(cls, model:Any, name:str) -> Any:
        """The circuit of the house panel the load is attached to, or
        `None`"""
        return object_state(model, name).get("circuit")

__all__ = ["ResidentialEnduse"]
