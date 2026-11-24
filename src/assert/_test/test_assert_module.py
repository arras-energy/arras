"""Tests of the `assert` package: loading, class registration, handlers"""

import doctest
import importlib

import pytest

from arras import exitcodes
from arras.oclass import Class
from arras.module import Module
from arras.model import Model, ModelError, module_entry_point
from arras.runner import Runner

assert_module = importlib.import_module("assert")

def test_doctests():
    """Module docstring examples"""
    for name in ("assert", "assert.g_assert", "assert.double_assert", "assert.complex_assert",
            "assert.enum_assert", "assert.int_assert"):
        result = doctest.testmod(importlib.import_module(name))
        assert result.failed == 0, name
        assert result.attempted > 0, name

def test_entry_point():
    """The package is the `arras.modules` entry point of module assert"""
    assert module_entry_point("assert") is assert_module.load
    assert module_entry_point("no_such_module") is None

def test_load():
    """Loading the module registers its classes, module, and global"""
    model = Model()
    model.load_module("assert")
    assert [x.name for x in assert_module.classes()] == ["assert", "double_assert", "complex_assert", "enum_assert", "int_assert"]
    assert sorted(model.classes) == sorted(x.name for x in assert_module.classes())
    module = Module.find("assert")
    assert [x.name for x in module.classes] == [x.name for x in assert_module.classes()]
    assert model.globals.find("assert::message_flags").ptype == "set"
    assert model.globals.find("assert::message_flags").keywords == {"QUIET": 0x10000, "WARNING": 0x20000, "DEBUG": 0x40000, "VERBOSE": 0x80000}
    for oclass in assert_module.classes():
        assert oclass.trl == 9
        assert oclass.passconfig == 0x0600
        assert oclass.get_event("init") == "python:assert.init"
        assert oclass.get_event("commit") == "python:assert.commit"
    # a second model loads the module again without registering twice
    other = Model()
    other.load_module("assert")
    assert len(assert_module.classes()) == 5
    assert other.globals.isdefined("assert::message_flags")

def test_modhelp():
    """Classes print as gridlabd --modhelp prints them"""
    Model().load_module("assert")
    assert Class.find("assert", module="assert").modhelp() == (
        "class assert {\n"
        "\tenumeration {ERROR=3, FALSE=2, TRUE=1, INIT=0, NONE=0} status; // desired outcome of assert test\n"
        "\tchar1024 target; // (REQUIRED) the target property to test\n"
        "\tchar32 part; // the target property part to test\n"
        "\tenumeration {outside=7, inside=6, !==3, >==2, >=5, <==1, <=4, ===0} relation; // (REQUIRED) the relation to use for the test\n"
        "\tchar1024 value; // (REQUIRED) the value to compare with for binary tests\n"
        "\tchar1024 within; // the bounds within which the value must bed compared\n"
        "\tchar1024 lower; // the lower bound to compare with for interval tests\n"
        "\tchar1024 upper; // the upper bound to compare with for interval tests\n"
        "\tchar1024 group; // a target group specification to use instead of parent object\n"
        "\ttimestamp start; // time to start assertion\n"
        "\ttimestamp stop; // time to stop assertion\n"
        "\tdouble hold[s]; // a duration over which the assertion must be violated before failing\n"
        "}\n\n")
    assert Class.find("int_assert", module="assert").modhelp() == (
        "class int_assert {\n"
        "\tenumeration {ASSERT_NONE=3, ASSERT_FALSE=2, ASSERT_TRUE=1} status;\n"
        "\tenumeration {ONCE_DONE=2, ONCE_TRUE=1, ONCE_FALSE=0} once;\n"
        "\tenumeration {WITHIN_RATIO=1, WITHIN_VALUE=0} within_mode;\n"
        "\tint32 value;\n"
        "\tint32 within;\n"
        "\tchar1024 target;\n"
        "}\n\n")

@pytest.mark.parametrize("cname,props", [
    ("assert", {"status": ("enumeration", "TRUE"), "start": ("timestamp", "INIT"), "stop": ("timestamp", "NEVER"),
        "within": ("char1024", "0"), "upper": ("char1024", "0"), "lower": ("char1024", ""), "hold": ("double", "0.0")}),
    ("double_assert", {"status": ("enumeration", "ASSERT_TRUE"), "once": ("enumeration", "0"), "within_mode": ("enumeration", "0"),
        "value": ("double", "0.0"), "within": ("double", "0.0"), "target": ("char1024", "")}),
    ("complex_assert", {"operation": ("enumeration", "0"), "value": ("complex", "0+0i"), "within": ("double", "0.0")}),
    ("enum_assert", {"status": ("enumeration", "ASSERT_TRUE"), "value": ("int32", "0"), "target": ("char1024", "")}),
    ("int_assert", {"value": ("int32", "0"), "within": ("int32", "0")}),
])
def test_properties(cname, props):
    """Property types and defaults are those gridlabd publishes"""
    Model().load_module("assert")
    oclass = Class.find(cname, module="assert")
    for name, (ptype, default) in props.items():
        assert oclass[name].ptype == ptype, name
        assert oclass[name].default == default, name

def test_message_flags_global(run):
    """The module block sets assert::message_flags"""
    model = Model()
    model.read_glm('module assert { message_flags "VERBOSE|QUIET"; }')
    assert model.globals.get("assert::message_flags") == "QUIET|VERBOSE"

def test_handlers_need_runner():
    """The handlers run only during a simulation"""
    with pytest.raises(assert_module.AssertError, match="only during"):
        assert_module.init("x", 0)

def test_not_assert_class(run):
    """The handlers refuse objects of other classes"""
    runner = run('class test { double x; on_commit "python:assert.commit"; } object test { x 1; }')
    assert runner.returncode == exitcodes.RUNERR
    assert "is not an object of an assert class" in runner.stderr[0]

def test_bad_entry_point(monkeypatch):
    """A failing or broken entry point raises ModelError"""
    import arras.model # pylint: disable=import-outside-toplevel
    def broken(model):
        raise assert_module.AssertError("broken")
    monkeypatch.setattr(arras.model, "module_entry_point", lambda name: broken)
    with pytest.raises(ModelError, match="module 'x': broken"):
        Model().load_module("x")

def test_entry_point_errors(monkeypatch):
    """Entry points that cannot be loaded or are not callable raise
    ModelError"""
    class Entry: # pylint: disable=too-few-public-methods
        value = "pkg:thing"
        def __init__(self, result):
            self.result = result
        def load(self):
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
    import arras.model # pylint: disable=import-outside-toplevel
    monkeypatch.setattr(arras.model.importlib.metadata, "entry_points", lambda **kw: [Entry(ImportError("nope"))])
    with pytest.raises(ModelError, match="cannot be loaded: ImportError: nope"):
        module_entry_point("x")
    monkeypatch.setattr(arras.model.importlib.metadata, "entry_points", lambda **kw: [Entry(42)])
    with pytest.raises(ModelError, match="is not callable"):
        module_entry_point("x")

def test_runner_verbose():
    """Runner.verbose() follows the verbose and quiet globals"""
    model = Model()
    model.read_glm('clock { starttime "2001-01-01 00:00:00 UTC"; stoptime "2001-01-01 00:00:00 UTC"; } class test { double x; } object test { x 1; }')
    runner = Runner(model=model)
    runner.verbose("hidden")
    assert not any("hidden" in x for x in runner.stderr)
    model.globals.set("verbose", True)
    runner.verbose("shown")
    assert runner.stderr[-1] == "VERBOSE [2001-01-01 00:00:00 UTC]: shown"

@pytest.mark.parametrize("ext", ["glm", "json"])
def test_round_trip(tmp_path, ext):
    """A model with assert objects is written and read back, and still runs"""
    import os # pylint: disable=import-outside-toplevel
    data = os.path.join(os.path.dirname(__file__), "data")
    model = Model(os.path.join(data, "test_double_assert_err.glm"))
    file = str(tmp_path / f"model.{ext}")
    model.write(file)
    Class.reset()
    Module.reset()
    copy = Model(file)
    assert "assert" in copy.modules
    runner = Runner(model=copy)
    assert runner.returncode == exitcodes.RUNERR
    assert "temperature 50 not within 1.000000 of given value 55" in runner.stderr[0]
