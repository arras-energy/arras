"""The `tape` package: docstrings, registration, classes, globals, and file
helpers"""

import doctest
import importlib

import pytest

import tape
from tape import _common, _file, _json
from arras.oclass import Class
from arras.module import Module
from arras.model import Model
from arras.runner import Runner
from arras import exitcodes

MODULES = ["tape", "tape.player", "tape.shaper", "tape.recorder", "tape.multi_recorder",
    "tape.collector", "tape.histogram", "tape.group_recorder", "tape.violation_recorder",
    "tape.metrics_collector", "tape.metrics_collector_writer", "tape.multiplayer"]

CLASSES = ["player", "shaper", "recorder", "multi_recorder", "collector", "histogram",
    "group_recorder", "violation_recorder", "metrics_collector", "metrics_collector_writer",
    "multiplayer"]

@pytest.mark.parametrize("name", MODULES)
def test_doctests(name):
    """The docstring examples give the output shown"""
    result = doctest.testmod(importlib.import_module(name), optionflags=doctest.ELLIPSIS)
    assert result.failed == 0

def test_load():
    """GLM `module tape;` registers the module, its classes in gridlabd's
    order, and its globals"""
    m = Model()
    m.read_glm("module tape;\n")
    assert [x.name for x in tape.classes()] == CLASSES
    assert Module.find("tape") is not None
    assert m.globals.get("tape::gnuplot_path") == "/usr/bin/gnuplot"
    assert m.globals.get("tape::csv_data_only") == "0"
    assert m.globals.get("tape::csv_header_type") == "FULL"
    assert m.globals.get("tape::delta_mode_needed") == "NEVER"
    second = Model()
    second.read_glm("module tape;\n")
    assert [x.name for x in tape.classes()] == CLASSES

@pytest.mark.parametrize("name, value, data_only, header_type", [
    ("csv_header_type", "NAME", "2", "NAME"),
    ("csv_header_type", "NONE", "1", "NONE"),
    ("csv_data_only", "2", "2", "NAME"),
    ("csv_data_only", "1", "1", "NONE"),
])
def test_csv_globals(name, value, data_only, header_type):
    """`csv_data_only` and `csv_header_type` share one value"""
    m = Model()
    m.read_glm(f"module tape {{ {name} {value}; }}\n")
    assert m.globals.get("tape::csv_data_only") == data_only
    assert m.globals.get("tape::csv_header_type") == header_type

def test_classes():
    """Class properties, defaults, keywords, pass configurations, and
    readiness levels follow gridlabd's `tape.cpp` and class files"""
    Model().read_glm("module tape;\n")
    player = Class.find("player", module="tape")
    assert [p.name for p in player.properties()] == ["property", "file", "filetype", "mode", "loop"]
    assert player.find_property("property").default == "(undefined)"
    assert player.find_property("file").has_flag("REQUIRED")
    assert player.trl == _common.TRL_PROVEN
    recorder = Class.find("recorder", module="tape")
    assert [p.name for p in recorder.properties()][:5] == ["trigger", "file", "filetype", "mode", "multifile"]
    assert recorder.find_property("interval").unit == "s"
    assert recorder.find_property("interval").default == "-1 s"
    assert recorder.find_property("flush").default == "-1"
    assert recorder.find_property("property").ptype == "method"
    assert list(recorder.find_property("output").keywords) == ["SVG", "PNG", "PDF", "JPG", "GIF", "EPS", "SCREEN"]
    assert list(recorder.find_property("line_units").keywords) == ["NONE", "ALL", "DEFAULT"]
    assert Class.find("multi_recorder", module="tape").find_property("format").ptype == "char32"
    assert Class.find("histogram", module="tape").trl == _common.TRL_PROTOTYPE
    violation = Class.find("violation_recorder", module="tape")
    assert violation.find_property("violation_flag").keywords["ALLVIOLATIONS"] == 0xFF
    assert len(violation.properties()) == 28
    multiplayer = Class.find("multiplayer", module="tape")
    assert multiplayer.find_property("indexname").default == "timestamp"
    assert list(multiplayer.find_property("on_error").keywords) == ["STOP", "WARN", "IGNORE"]
    assert Class.find("group_recorder", module="tape").find_property("complex_part").keywords["ANG_RAD"] == 5

def test_method_accumulates():
    """`property` given twice in a GLM object block keeps both lists"""
    m = Model()
    m.read_glm("module tape;\nclass test { double x; double y; }\nobject test { object recorder { name r; property x; property y; }; }\n")
    assert m.get_property("r", "property") == "x,y"

def test_outside_run():
    """Handlers work only during a run"""
    with pytest.raises(tape.TapeError):
        tape.presync("x", 0)

def test_not_tape_object(helpers):
    """A tape handler on another object fails the run"""
    runner = helpers.run('class test { double x; }\nobject test { name "t"; on_presync "python:tape.presync"; }')
    assert runner.returncode == exitcodes.RUNERR
    assert "is not a tape object" in runner.stderr[-1]

def test_unsupported_mode(helpers):
    """Tape modes other than `file` fail as gridlabd does without their module"""
    helpers.write("x.player", "2020-01-01 00:00:00,1\n")
    runner = helpers.run('class test { double x; }\nobject test { object player { property x; file x.player; mode memory; }; }')
    assert runner.returncode == exitcodes.RUNERR
    assert runner.stderr[0].endswith("unable to locate tape_memory.so")

def test_stdout(helpers):
    """File `-` writes to the run's output"""
    runner = helpers.run('class test { double x; }\nobject test { x 1; object recorder { property x; file "-"; }; }')
    assert runner.stdout == ["timestamp,x", "2020-01-01 00:00:00 UTC,+1"]

def test_full_header(helpers, monkeypatch):
    """The `FULL` header lines and the end-of-tape line"""
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("HOST", raising=False)
    helpers.run('class test { double x; }\nobject test { x 1; object recorder { property x; file "out.csv"; trigger ">"; limit 5; }; }', header="FULL")
    rows = helpers.lines("out.csv")
    assert rows[0] == "# file...... out.csv"
    assert rows[1].startswith("# date...... ")
    assert rows[2:] == ["# user...... tester", "# host...... (null)", "# target.... test 0", "# trigger... >",
        "# interval.. -1", "# limit..... 5", "# timestamp,x", "2020-01-01 00:00:00 UTC,+1", "# end of tape"]

def test_header_none(helpers):
    """`csv_header_type NONE`: rows only"""
    helpers.run('class test { double x; }\nobject test { x 1; object recorder { property x; file "out.csv"; }; }', header="NONE")
    assert helpers.lines("out.csv") == ["2020-01-01 00:00:00 UTC,+1"]

def test_keep_clean(helpers):
    """`csv_keep_clean` flushes every row (the header line is flushed with
    the first row)"""
    m = helpers.model('class test { double x; }\nobject test { x 1; object recorder { name r; property x; file "out.csv"; interval 3600; }; }', stop="2020-01-01 03:00:00")
    m.globals.set("tape::csv_keep_clean", "1")
    seen = []
    Runner(model=m, progress=lambda timestamp: seen.append(len(helpers.lines("out.csv"))))
    assert seen[:3] == [0, 2, 3]

def test_hexfloat():
    """C `%a` formats"""
    assert _common.hexfloat(1.0, 4) == "0x1.0000p+0"
    assert _common.hexfloat(-2.5) == "-0x1.4p+1"
    assert _common.hexfloat(1500.0, 1) == "0x1.7p+10"
    assert _common.hexfloat(1.99999, 0) == "0x2p+0"
    assert _common.hexfloat(0.0, None, True) == "0X0P+0"
    assert _common.hexfloat(float("inf")) == "inf"
    assert _common.cprintf("%+.2a|%d%%", 2.0, 5) == "+0x1.00p+1|5%"

def test_cprintf_error():
    """A format that does not fit its arguments"""
    with pytest.raises(tape.TapeError):
        _common.cprintf("%d", "x")

def test_values():
    """Text conversions as the core's `convert_to_*()` functions"""
    assert _common.to_double("") == 0.0
    assert _common.to_double("1.5 MW", "kW") == pytest.approx(1500.0)
    with pytest.raises(tape.TapeError):
        _common.to_double("x")
    with pytest.raises(tape.TapeError):
        _common.to_double("1 kW")
    with pytest.raises(tape.TapeError):
        _common.to_double("1 kW", "s")
    assert _common.to_complex("1+2j") == (complex(1, 2), "j")
    assert _common.to_complex("2+90d")[1] == "d"
    assert abs(_common.to_complex("1+1.5707963267948966r")[0] - 1j) < 1e-12
    assert _common.to_complex("1 kVA", "VA") == (complex(1000, 0), "i")
    with pytest.raises(tape.TapeError):
        _common.to_complex("1+2x")
    with pytest.raises(tape.TapeError):
        _common.to_complex("x")
    assert _common.atoi("12abc") == 12 and _common.atoi("x") == 0
    assert _common.strtok(",a,,b,", ",") == ["a", "b"]
    assert _common.unit_scale("kW", "s") is None

def test_mktime():
    """Local times, zone abbreviations, and fields out of range"""
    m = Model()
    m.globals.set("timezone_locale", "America/Los_Angeles")
    assert _common.mktime(m, (2020, 1, 1, 0, 0, 0)) == 1577865600
    assert _common.mktime(m, (2020, 1, 1, 0, 0, 0), "PST") == 1577865600
    assert _common.mktime(m, (2020, 1, 1, 0, 0, 0), "PDT") == 1577862000
    assert _common.mktime(m, (2020, 1, 1, 0, 0, 0), "UTC") == 1577836800
    assert _common.mktime(m, (2020, 13, 1, 0, 0, 0)) == _common.TS_INVALID
    assert _common.to_timestamp(m, "2020-07-01 00:00:00 PDT") == 1593586800
    with pytest.raises(tape.TapeError):
        _common.to_timestamp(m, "never more")

def test_strtime():
    """Date formats of `gl_strtime()`"""
    m = Model()
    for fmt, text in (("ISO", "2020-01-01 00:00:00 UTC"), ("US", "01-01-2020 00:00:00 UTC"),
            ("EURO", "01-01-2020 00:00:00 UTC"), ("ISO8601", "2020-01-01T00:00:00+00:00")):
        m.globals.set("dateformat", fmt)
        assert _common.strtime(m, 1577836800) == text
    m.globals.set("dateformat", "ISO")
    assert _common.strtime(m, 1577836800, 5) == "2020-01-01 00:00:00.000000005 UTC"

def test_setmap():
    """Cron-like shape fields"""
    assert _file.setmap("*", 3) == {0, 1, 2}
    assert _file.setmap("1-3", 24) == {1, 2, 3}
    assert _file.setmap("22-1", 24) == {22, 23, 0, 1}
    assert _file.setmap("1;5", 24) == {1, 5}
    assert _file.setmap("x", 24) is None

def test_styled_json():
    """jsoncpp `StyledWriter` text"""
    assert _json.styled({}) == "{}\n"
    assert _json.styled({"b": [1.0, 2], "a": "x", "c": []}) == '{\n   "a" : "x",\n   "b" : [ 1.0, 2 ],\n   "c" : []\n}\n'
    assert _json.styled([1.5]*30).startswith("[\n   1.5,\n   1.5,")
    assert _json.styled([[1], {}]) == "[\n   [ 1 ],\n   {}\n]\n"
    assert _json.styled([0.1]*8).startswith("[\n   0.10000000000000001,")
    assert _json.value_text(None) == "null" and _json.value_text(True) == "true"
    assert _json.value_text(float("nan")) == "null" and _json.value_text(float("-inf")) == "-1e+9999"
