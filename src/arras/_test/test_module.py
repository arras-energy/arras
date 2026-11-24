"""Tests of arras.module"""

import doctest
import logging

import pytest

import arras.module
from arras.module import Module, ModuleError, SOLVERS, SIMULATIONMODE, \
    TS_NEVER, TS_INVALID, TS_MAX, TS_ZERO, DT_INFINITY, DT_INVALID, \
    DT_SECOND, DT_DEFAULT, SM_INIT, SM_EVENT, SM_DELTA, SM_DELTA_ITER, SM_ERROR
from arras.oclass import Class, ClassError

T0 = 946684800 # 2000-01-01 00:00:00 UTC

@pytest.fixture(autouse=True)
def fixture_reset():
    """Start each test with empty module and class registries"""
    Module.reset()
    Class.reset()
    yield
    Module.reset()
    Class.reset()

class Recorder:
    """Solver factory that records its calls in a shared log"""
    def __init__(self, log:list, name:str):
        self.log = log
        self.name = name
    def __call__(self, hook:str, result):
        def solver(*args):
            self.log.append((self.name, hook, args))
            return result
        return solver

#
# Constants
#
def test_constants():
    assert TS_ZERO == 0
    assert TS_INVALID == -1
    assert TS_NEVER == 9223372036854775807
    assert TS_MAX == 32482080000
    assert DT_SECOND == 10**9
    assert DT_INFINITY == 0xfffffffe
    assert DT_INVALID == 0xffffffff
    assert DT_DEFAULT == 10000000
    assert (SM_INIT, SM_EVENT, SM_DELTA, SM_DELTA_ITER, SM_ERROR) == (0, 1, 2, 3, 255)
    assert SIMULATIONMODE == {"INIT":0, "EVENT":1, "DELTA":2, "DELTA_ITER":3, "ERROR":255}

def test_solver_table():
    assert list(SOLVERS) == ["init", "precommit", "presync", "sync", "postsync",
        "commit", "term", "clockupdate", "deltamode_desired", "preupdate",
        "interupdate", "deltaclockupdate", "postupdate"]
    assert SOLVERS["term"] == ("on_term", "term")
    assert SOLVERS["clockupdate"] == ("clock_update",)
    assert SOLVERS["deltaclockupdate"] == ("deltaClockUpdate",)

#
# Registry
#
def test_register():
    pf = Module("powerflow", 4, 3)
    tape = Module("tape")
    assert (pf.id, pf.name, pf.major, pf.minor) == (0, "powerflow", 4, 3)
    assert (tape.id, tape.major, tape.minor) == (1, 0, 0)
    assert Module.registry == [pf, tape]
    assert repr(pf) == "<Module powerflow>"
    assert Module.find("tape") is tape
    assert Module.find("missing") is None

def test_register_duplicate():
    Module("powerflow")
    with pytest.raises(ModuleError, match="module 'powerflow' is already loaded"):
        Module("powerflow")

@pytest.mark.parametrize("name", ["", None, 3, "power flow", "a.b", "a:b", "a\tb", "x"*1024])
def test_register_bad_name(name):
    with pytest.raises(ModuleError):
        Module(name)

def test_register_name_limit():
    assert Module("x"*1023).name == "x"*1023

@pytest.mark.parametrize("version", [-1, 65536, 1.0, "1", True, None])
def test_register_bad_version(version):
    with pytest.raises(ModuleError, match="version"):
        Module("m", major=version)
    with pytest.raises(ModuleError, match="version"):
        Module("m", minor=version)
    assert not Module.registry

def test_load():
    pf = Module.load("powerflow", 4, 3)
    assert Module.load("powerflow", 9, 9) is pf
    assert (pf.major, pf.minor) == (4, 3)
    assert len(Module.registry) == 1

def test_reset():
    Module("a")
    Module("b")
    Module.reset()
    assert not Module.registry
    assert Module("c").id == 0

def test_reset_keeps_classes():
    Module("powerflow").register_class("node")
    Module.reset()
    assert Class.find("node", module="powerflow") is not None

#
# Classes
#
def test_register_class():
    pf = Module("powerflow")
    node = pf.register_class("node", passconfig="PRETOPDOWN|BOTTOMUP|POSTTOPDOWN")
    load = pf.register_class("load", passconfig=7)
    assert isinstance(node, Class)
    assert node.module == "powerflow"
    assert node.has_pass("BOTTOMUP")
    assert pf.classes == [node, load]

def test_classes_from_registry():
    pf = Module("powerflow")
    Class("other", module="tape")
    node = Class("node", module="powerflow")
    Class("glmclass")
    assert pf.classes == [node]
    assert not Module("tape2").classes

def test_register_class_errors():
    pf = Module("powerflow")
    pf.register_class("node")
    with pytest.raises(ClassError):
        pf.register_class("node")
    with pytest.raises(ClassError):
        pf.register_class("bad", passconfig="NOPASS")
    # same class name in another module is allowed
    assert Module("other").register_class("node").module == "other"

#
# Solvers
#
def test_set_solver():
    def f(t):
        return t
    pf = Module("powerflow")
    assert not pf.has_solver("sync")
    pf.set_solver("sync", f)
    assert pf.get_solver("sync") is f
    assert pf.get_solver("on_sync") is f
    assert pf.has_solver("on_sync")
    pf.set_solver("clock_update", f)
    pf.set_solver("deltaClockUpdate", f)
    pf.set_solver("term", f)
    assert set(pf.solvers) == {"sync", "clockupdate", "deltaclockupdate", "term"}
    assert pf.get_solver("on_term") is f

def test_set_solver_replace_and_remove():
    pf = Module("powerflow", sync=lambda t: t)
    def g(t):
        return t + 1
    pf.set_solver("on_sync", g)
    assert pf.get_solver("sync") is g
    pf.set_solver("sync", None)
    assert not pf.has_solver("sync")
    pf.set_solver("on_sync", None) # removing an absent solver is allowed
    with pytest.raises(ModuleError, match="hook 'bogus' is not valid"):
        pf.set_solver("bogus", None)

def test_set_solver_errors():
    pf = Module("powerflow")
    with pytest.raises(ModuleError, match="hook 'bogus' is not valid"):
        pf.set_solver("bogus", lambda: None)
    with pytest.raises(ModuleError, match="is not callable"):
        pf.set_solver("sync", 3)
    assert pf.get_solver("bogus") is None

def test_constructor_solvers():
    def f(t):
        return t
    pf = Module("powerflow", on_sync=f, presync=f, clock_update=f)
    assert set(pf.solvers) == {"sync", "presync", "clockupdate"}

def test_constructor_solver_errors():
    with pytest.raises(ModuleError, match="hook 'bogus'"):
        Module("powerflow", bogus=lambda: None)
    with pytest.raises(ModuleError, match="not callable"):
        Module("powerflow", sync="text")
    assert not Module.registry

#
# Event-mode dispatchers
#
def test_initall():
    log = []
    Module("a", init=Recorder(log, "a")("init", True))
    Module("b")
    Module("c", init=Recorder(log, "c")("init", 1))
    assert Module.initall() is True
    assert [x[0] for x in log] == ["a", "c"]

def test_initall_failure(caplog):
    log = []
    Module("a", init=Recorder(log, "a")("init", False))
    Module("b", init=Recorder(log, "b")("init", True))
    with caplog.at_level(logging.ERROR):
        assert Module.initall() is False
    assert "module a on_init() failed" in caplog.text
    assert [x[0] for x in log] == ["a"]

def test_initall_empty():
    assert Module.initall() is True

@pytest.mark.parametrize("hook,dispatch", [
    ("precommit", Module.precommitall),
    ("presync", Module.presyncall),
    ("sync", Module.syncall),
    ("postsync", Module.postsyncall),
    ])
def test_earliest(hook, dispatch):
    assert dispatch(T0) == TS_NEVER
    log = []
    Module("a", **{hook: Recorder(log, "a")(hook, T0+3600)})
    Module("b")
    Module("c", **{hook: Recorder(log, "c")(hook, TS_NEVER)})
    assert dispatch(T0) == T0+3600
    assert log == [("a", hook, (T0,)), ("c", hook, (T0,))]
    # a soft time keeps its sign and wins when it is earlier
    Module("d", **{hook: Recorder(log, "d")(hook, -(T0+60))})
    assert dispatch(T0) == -(T0+60)
    # a later hard time does not replace an earlier soft time
    Module("e", **{hook: Recorder(log, "e")(hook, T0+120)})
    assert dispatch(T0) == -(T0+60)
    # an earlier hard time does
    Module("f", **{hook: Recorder(log, "f")(hook, T0+30)})
    assert dispatch(T0) == T0+30
    # TS_INVALID (absolute time 1) wins over every other time
    Module("g", **{hook: Recorder(log, "g")(hook, TS_INVALID)})
    assert dispatch(T0) == TS_INVALID

def test_earliest_first_of_equal():
    Module("a", sync=lambda t: -(T0+60))
    Module("b", sync=lambda t: T0+60)
    assert Module.syncall(T0) == -(T0+60)
    Module.reset()
    Module("a", sync=lambda t: T0+60)
    Module("b", sync=lambda t: -(T0+60))
    assert Module.syncall(T0) == T0+60

@pytest.mark.parametrize("result", [None, 1.5, "1", True])
def test_earliest_bad_result(result):
    Module("a", sync=lambda t: result)
    with pytest.raises(ModuleError, match="solver 'sync' returned .*, not a time"):
        Module.syncall(T0)

def test_commitall():
    log = []
    Module("a", commit=Recorder(log, "a")("commit", True))
    Module("b", commit=Recorder(log, "b")("commit", 0))
    Module("c", commit=Recorder(log, "c")("commit", True))
    assert Module.commitall(T0) is False
    assert log == [("a", "commit", (T0,)), ("b", "commit", (T0,)), ("c", "commit", (T0,))]
    Module.reset()
    Module("a", commit=lambda t: True)
    assert Module.commitall(T0) is True
    Module.reset()
    assert Module.commitall(T0) is True

def test_termall():
    log = []
    Module("a", on_term=Recorder(log, "a")("term", None))
    Module("b")
    Module("c", term=Recorder(log, "c")("term", None))
    assert Module.termall() is None
    assert log == [("a", "term", ()), ("c", "term", ())]

def test_clockupdateall():
    assert Module.clockupdateall(T0+3600) == T0+3600
    calls = []
    def make(name, limit):
        def solver(t):
            calls.append((name, t))
            return min(t, limit)
        return solver
    Module("a", clockupdate=make("a", T0+1800))
    Module("b", clockupdate=make("b", T0+600))
    Module("c")
    assert Module.clockupdateall(T0+3600) == T0+600
    # a lowers, b lowers, then both are asked again and neither lowers
    assert calls == [("a", T0+3600), ("b", T0+1800), ("a", T0+600), ("b", T0+600)]

def test_clockupdateall_later_ignored():
    Module("a", clockupdate=lambda t: t + 100)
    assert Module.clockupdateall(T0) == T0

def test_clockupdateall_bad_result():
    Module("a", clockupdate=lambda t: str(t))
    with pytest.raises(ModuleError, match="not a time"):
        Module.clockupdateall(T0)

#
# Deltamode dispatchers
#
def delta_module(name, log, desired=DT_INFINITY, pre=DT_DEFAULT, inter=SM_EVENT,
        clock=None, post=True):
    """Module with every deltamode solver, recording calls in `log`"""
    rec = Recorder(log, name)
    solvers = {
        "deltamode_desired": rec("deltamode_desired", desired),
        "preupdate": rec("preupdate", pre),
        "interupdate": rec("interupdate", inter),
        "postupdate": rec("postupdate", post),
    }
    if clock is not None:
        solvers["deltaclockupdate"] = rec("deltaclockupdate", clock)
    return Module(name, **solvers)

def test_deltadesiredall_none():
    assert Module.deltadesiredall() == DT_INFINITY
    Module("event_only", sync=lambda t: t)
    assert Module.deltadesiredall() == DT_INFINITY

def test_deltadesiredall():
    log = []
    delta_module("a", log, desired=DT_INFINITY)
    delta_module("b", log, desired=5000000)
    delta_module("c", log, desired=20000000)
    assert Module.deltadesiredall(flags=3, allowed=True) == 5000000
    assert [x for x in log if x[1] == "deltamode_desired"] == \
        [("a", "deltamode_desired", (3,)), ("b", "deltamode_desired", (3,)),
         ("c", "deltamode_desired", (3,))]

def test_deltadesiredall_zero():
    log = []
    delta_module("a", log, desired=0)
    assert Module.deltadesiredall(allowed=True) == 0

def test_deltadesiredall_not_allowed(caplog):
    log = []
    delta_module("a", log, desired=1000)
    with caplog.at_level(logging.ERROR):
        assert Module.deltadesiredall() == DT_INVALID
    assert "deltamode_allowed is FALSE" in caplog.text
    Module.reset()
    delta_module("a", log, desired=DT_INFINITY)
    assert Module.deltadesiredall() == DT_INFINITY

def test_deltadesiredall_invalid(caplog):
    log = []
    delta_module("a", log, desired=DT_INVALID)
    delta_module("b", log, desired=1000)
    with caplog.at_level(logging.ERROR):
        assert Module.deltadesiredall(allowed=True) == DT_INVALID
    assert "module 'a' return invalid/infinite dt" in caplog.text
    assert [x[0] for x in log] == ["a"]

def test_preupdateall():
    log = []
    assert Module.preupdateall(T0, 0) == DT_DEFAULT
    delta_module("a", log, pre=20000000)
    delta_module("b", log, pre=1000000)
    Module("event_only", preupdate=Recorder(log, "x")("preupdate", 1))
    assert Module.preupdateall(T0, 500) == 1000000
    assert Module.preupdateall(T0, 500, timestep=100) == 100
    assert ("x", "preupdate", (T0, 500)) not in log
    assert ("a", "preupdate", (T0, 500)) in log

@pytest.mark.parametrize("bad", [0, DT_INVALID])
def test_preupdateall_failure(bad, caplog):
    log = []
    delta_module("a", log, pre=bad)
    delta_module("b", log, pre=1000)
    with caplog.at_level(logging.ERROR):
        assert Module.preupdateall(T0, 0) == 0
    assert "delta_preupdate(): module a failed" in caplog.text
    assert not [x for x in log if x[0] == "b"]

def test_interupdateall():
    log = []
    assert Module.interupdateall(T0, 0, DT_DEFAULT, 0) == SM_EVENT
    delta_module("a", log, inter=SM_EVENT)
    assert Module.interupdateall(T0, 0, DT_DEFAULT, 0) == SM_EVENT
    delta_module("b", log, inter=SM_DELTA)
    assert Module.interupdateall(T0, 0, DT_DEFAULT, 0) == SM_DELTA
    delta_module("c", log, inter=SM_DELTA_ITER)
    delta_module("d", log, inter=SM_DELTA)
    delta_module("e", log, inter=SM_INIT) # other values leave the mode
    assert Module.interupdateall(T0, 10, DT_DEFAULT, 2) == SM_DELTA_ITER
    assert ("e", "interupdate", (T0, 10, DT_DEFAULT, 2)) in log

def test_interupdateall_error():
    log = []
    delta_module("a", log, inter=SM_DELTA_ITER)
    delta_module("b", log, inter=SM_ERROR)
    delta_module("c", log, inter=SM_DELTA)
    assert Module.interupdateall(T0, 0, DT_DEFAULT, 0) == SM_ERROR
    assert not [x for x in log if x[0] == "c"]

def test_deltaclockupdateall_delta():
    log = []
    delta_module("a", log, clock=SM_DELTA)
    delta_module("b", log) # no deltaclockupdate solver: skipped
    delta_module("c", log, clock=SM_EVENT)
    assert Module.deltaclockupdateall(10.5, 250000000, SM_DELTA) == SM_DELTA
    calls = [x for x in log if x[1] == "deltaclockupdate"]
    assert calls == [("a", "deltaclockupdate", (10.75, 250000000, SM_DELTA)),
                     ("c", "deltaclockupdate", (10.75, 250000000, SM_DELTA))]

def test_deltaclockupdateall_delta_iter(caplog):
    log = []
    delta_module("a", log, clock=SM_DELTA_ITER)
    delta_module("b", log, clock=SM_DELTA)
    with caplog.at_level(logging.ERROR):
        assert Module.deltaclockupdateall(1.0, 1000, SM_DELTA) == SM_EVENT
    assert "too late to reiterate" in caplog.text
    assert not [x for x in log if x[0] == "b"]

def test_deltaclockupdateall_delta_error():
    log = []
    delta_module("a", log, clock=SM_ERROR)
    assert Module.deltaclockupdateall(1.0, 1000, SM_DELTA) == SM_ERROR
    Module.reset()
    delta_module("a", log, clock=SM_INIT)
    assert Module.deltaclockupdateall(1.0, 1000, SM_DELTA) == SM_DELTA

def test_deltaclockupdateall_event():
    log = []
    delta_module("a", log, clock=SM_EVENT)
    delta_module("b", log, clock=SM_INIT)
    delta_module("c", log) # no deltaclockupdate solver: skipped
    assert Module.deltaclockupdateall(10.25, 1000, SM_EVENT) == SM_EVENT
    calls = [x for x in log if x[1] == "deltaclockupdate"]
    assert calls[0] == ("a", "deltaclockupdate", (11.0, 750000000, SM_EVENT))
    Module.reset()
    delta_module("a", log, clock=SM_INIT)
    assert Module.deltaclockupdateall(10.25, 1000, SM_EVENT) == SM_DELTA

@pytest.mark.parametrize("result,message", [
    (SM_DELTA_ITER, "too late to reiterate"),
    (SM_DELTA, "too late to stay in it"),
    (SM_ERROR, None),
    ])
def test_deltaclockupdateall_event_errors(result, message, caplog):
    log = []
    delta_module("a", log, clock=result)
    with caplog.at_level(logging.ERROR):
        assert Module.deltaclockupdateall(10.25, 1000, SM_EVENT) == SM_ERROR
    if message:
        assert message in caplog.text

@pytest.mark.parametrize("mode", [SM_INIT, SM_DELTA_ITER, SM_ERROR])
def test_deltaclockupdateall_other_modes(mode):
    log = []
    delta_module("a", log, clock=SM_ERROR)
    assert Module.deltaclockupdateall(1.0, 1000, mode) == SM_DELTA
    assert not log

def test_postupdateall():
    log = []
    assert Module.postupdateall(T0, 0) is True
    delta_module("a", log, post=True)
    delta_module("b", log, post=False)
    delta_module("c", log, post=True)
    assert Module.postupdateall(T0, 7) is False
    assert [x[0] for x in log if x[1] == "postupdate"] == ["a", "b"]
    Module.reset()
    delta_module("a", log, post=1)
    assert Module.postupdateall(T0, 7) is True

@pytest.mark.parametrize("missing,dispatch", [
    ("preupdate", lambda: Module.preupdateall(T0, 0)),
    ("interupdate", lambda: Module.interupdateall(T0, 0, DT_DEFAULT, 0)),
    ("postupdate", lambda: Module.postupdateall(T0, 0)),
    ])
def test_delta_missing_solver(missing, dispatch):
    log = []
    module = delta_module("a", log)
    module.set_solver(missing, None)
    with pytest.raises(ModuleError, match=f"module 'a' has a deltamode_desired solver but no {missing} solver"):
        dispatch()

#
# Documentation
#
def test_docstring_examples():
    result = doctest.testmod(arras.module, optionflags=doctest.ELLIPSIS)
    assert result.failed == 0 and result.attempted > 0
