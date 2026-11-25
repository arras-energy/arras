"""Event handler that stands in for gridlabd `randomvar` refreshes in the
ported autotests (see `data/README.md`)

Objects with `on_sync "python:tape_test_random.sync";` get new values of
their `x` and `y` properties (those the class has), drawn from normal(0,1)
and clipped to `min` and `max` when the class has them, every `refresh`
seconds. The draws come from a Python `random.Random` seeded with the
model's `randomseed` global, so a run is repeatable.
"""

import random
import weakref

from arras.runner import Runner

_STATE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

def sync(name:str, t:int) -> int:
    """Draw new values when the object's refresh time is reached; returns
    the next refresh time"""
    model = Runner.current().model
    state = _STATE.setdefault(model, {"rng": random.Random(model.globals.getvalue("randomseed")), "next": {}})
    oclass = model.objects[name].oclass
    refresh = int(float(model.get_property(name, "refresh").split()[0]))
    next_time = state["next"].get(name, t)
    if t >= next_time:
        for prop in ("x", "y"):
            if oclass.find_property(prop) is not None:
                value = state["rng"].gauss(0, 1)
                if oclass.find_property("min") is not None:
                    value = max(float(model.get_property(name, "min")), min(float(model.get_property(name, "max")), value))
                model.set_property(name, prop, value)
        next_time = t + refresh
        state["next"][name] = next_time
    return next_time
