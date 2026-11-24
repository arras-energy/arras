"""Event handler that stands in for gridlabd `randomvar` refreshes in the
ported autotests (see `README.md`)

Objects with `on_sync "python:assert_test_random.sync";` get a new
`random_value`, drawn from uniform(0,1), every `refresh` seconds. The draws
come from a Python `random.Random` seeded with the model's `randomseed`
global, so a run is repeatable.
"""

import random
import weakref

from arras.runner import Runner

_STATE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

def sync(name:str, t:int) -> int:
    """Draw a new value when the object's refresh time is reached; returns
    the next refresh time"""
    model = Runner.current().model
    state = _STATE.setdefault(model, {"rng": random.Random(model.globals.getvalue("randomseed")), "next": {}})
    refresh = int(float(model.get_property(name, "refresh").split()[0]))
    next_time = state["next"].get(name, t)
    if t >= next_time:
        model.set_property(name, "random_value", state["rng"].random())
        next_time = t + refresh
        state["next"][name] = next_time
    return next_time

def hourly(name:str, t:int) -> int: # pylint: disable=unused-argument
    """Ask for an event every hour"""
    return t + 3600
