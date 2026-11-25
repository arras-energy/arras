"""Recorders, multi-recorders, collectors, histograms, and group recorders"""

import os

import pytest

from arras import exitcodes
from arras.runner import Runner

TICK = "class ticker { double t; }\nobject ticker { name tick; on_sync \"python:tape_test_ticker.sync\"; }\n"
"""An object that asks for an event every 10 minutes"""

LOAD = "class load { double power[kW]; complex current[A]; enumeration {OFF=0, ON=1} status; set {A=1, B=2, C=4} phases; int32 n; timestamp when; bool flag; char32 label; double t; }\n"

def rows(helpers, file:str) -> list[str]:
    """Rows of a file without comment lines"""
    return [x for x in helpers.lines(file) if not x.startswith("#")]

@pytest.fixture(autouse=True)
def ticker(monkeypatch):
    """A handler that asks for an event every 10 minutes and sets
    `load.power` to the number of minutes"""
    import sys, types # pylint: disable=import-outside-toplevel,multiple-imports
    from arras.runner import Runner as R # pylint: disable=import-outside-toplevel
    def sync(name, t):
        model = R.current().model
        for obj in model.objects:
            if model.objects[obj].oclass.name == "load":
                model.set_property(obj, "power", (t % 3600)//60)
        return t + 600
    monkeypatch.setitem(sys.modules, "tape_test_ticker", types.SimpleNamespace(sync=sync))

def record(helpers, props:str, glm:str="", stop:str="2020-01-01 00:30:00", **kwargs) -> Runner:
    """Run a recorder of a `load` object that a ticker changes"""
    return helpers.run(TICK + LOAD + f'object load {{ name "L"; current 1+1j; status ON; phases AB; n 3; when "2020-01-01 00:00:00"; label "x y"; object recorder {{ name "r"; file "out.csv"; property "{props}"; {glm} }}; }}', stop=stop, **kwargs)

def test_intervals(helpers):
    """Interval -1 (on change), 0 (every pass, from the first time), and
    positive (sampled)"""
    record(helpers, "power", "interval -1;")
    assert rows(helpers, "out.csv")[1:] == [f"2020-01-01 00:{m:02d}:00 UTC,+{m}" for m in (0, 10, 20, 30)]
    record(helpers, "power", "interval 0;")
    assert rows(helpers, "out.csv")[1:] == [f"2020-01-01 00:{m:02d}:00 UTC,+{m}" for m in (0, 10, 20, 30)]
    record(helpers, "power", "interval 1200;", stop="2020-01-01 01:00:00")
    assert rows(helpers, "out.csv")[1:] == ["2020-01-01 00:00:00 UTC,+0", "2020-01-01 00:20:00 UTC,+20", "2020-01-01 00:40:00 UTC,+40", "2020-01-01 01:00:00 UTC,+0"]

def test_types(helpers):
    """Values of each type as `gl_get_value()` writes them"""
    record(helpers, "current,status,phases,n,when,flag,label,current.real,::clock", "interval 600;", stop="2020-01-01 00:10:00")
    assert rows(helpers, "out.csv")[1] == "2020-01-01 00:00:00 UTC,+1+1j,ON,AB,3,2020-01-01 00:00:00 UTC,FALSE,x y,+1,2020-01-01 00:00:00 UTC"

def test_units(helpers):
    """Units in the property list, `line_units`, and `header_units`"""
    record(helpers, "power[W],current[mA]", "interval -1; header_units ALL;", stop="2020-01-01 00:10:00")
    assert rows(helpers, "out.csv")[:3] == ["timestamp,power[W],current[mA]", "2020-01-01 00:00:00 UTC,+0 W,+1000+1000j mA",
        "2020-01-01 00:10:00 UTC,+10000 W,+1000+1000j mA"]
    record(helpers, "power,current", "interval -1; line_units ALL; header_units ALL;", stop="2020-01-01 00:00:00")
    assert rows(helpers, "out.csv") == ["timestamp,power[kW],current[A]", "2020-01-01 00:00:00 UTC,+0 kW,+1+1j A"]
    record(helpers, "power[W],current", "interval -1; line_units NONE; header_units NONE;", stop="2020-01-01 00:10:00")
    assert rows(helpers, "out.csv")[:3] == ["timestamp,power,current", "2020-01-01 00:00:00 UTC,+0", "2020-01-01 00:10:00 UTC,+10000"][:1] + ["2020-01-01 00:00:00 UTC,+0,+1+1j", "2020-01-01 00:10:00 UTC,+10000,+1+1j"]

def test_formats(helpers):
    """Output formats of doubles and complex values"""
    record(helpers, "power[W:2f],current[A:1fi],current[A:1fd],current[A:3gM]", "interval -1;", stop="2020-01-01 00:10:00")
    assert rows(helpers, "out.csv")[2] == "2020-01-01 00:10:00 UTC,10000.00 W,1.0+1.0i A,1.4+45.0d A,1.41 A"

@pytest.mark.parametrize("props, message", [
    ("power[W:2x]", "invalid double/complex format"),
    ("current[A:2f]", "output format part required missing complex specifier"),
    ("power[W:2fi]", "output format part 'i' is not valid"),
    ("n[s:2f]", "property 'n' is unitless"),
    ("nothing", "property or global 'nothing' not found"),
    ("power[furlong]", "unable to find unit 'furlong'"),
    ("power[s]", "unable to convert property 'power' units to 's'"),
])
def test_property_errors(helpers, props, message):
    """Property list errors"""
    runner = record(helpers, props)
    assert runner.returncode == exitcodes.RUNERR
    assert any(message in x for x in runner.stderr), runner.stderr

def test_trigger_limit_format(helpers):
    """A trigger delays the file; a limit of 1 allows one row; seconds as
    timestamps"""
    record(helpers, "power", "interval -1; trigger \">+15\"; limit 1; format TRUE;", stop="2020-01-01 01:00:00")
    assert rows(helpers, "out.csv") == ["timestamp,power", "1577838000,+20"]
    record(helpers, "power", 'interval -1; strftime_format "%H:%M";', stop="2020-01-01 00:10:00")
    assert rows(helpers, "out.csv")[1:] == ["00:00,+0", "00:10,+10"]

def test_interval_checks(helpers):
    """An interval below -1 fails; one below `minimum_timestep` is raised"""
    runner = record(helpers, "power", "interval -5;")
    assert runner.returncode == exitcodes.RUNERR
    m = helpers.model(TICK + LOAD + 'object load { name "L"; object recorder { file "out.csv"; property "power"; interval 60; }; }', stop="2020-01-01 00:30:00")
    m.globals.set("minimum_timestep", "600")
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert any("is less than minimum timestep, setting interval to 600" in x for x in runner.stderr)

def test_no_parent(helpers):
    """A recorder needs a parent"""
    runner = helpers.run('object recorder { file "out.csv"; property "x"; }')
    assert runner.returncode == exitcodes.RUNERR
    assert "lacks a parent object" in runner.stderr[0]

def test_default_file_and_flush(helpers):
    """The default file name, and flushing at a multiple of `flush`"""
    runner = helpers.run(TICK + LOAD + 'object load { object recorder { property "power"; flush 1200; interval -1; }; }', stop="2020-01-01 00:30:00")
    assert runner.returncode == exitcodes.SUCCESS
    assert rows(helpers, "load-1.txt")[0] == "timestamp,power"

def test_multifile(helpers):
    """Multi-run files add this run's columns to the previous runs'"""
    for _ in range(2):
        record(helpers, "power", 'interval 600; multifile "multi.csv";', stop="2020-01-01 00:30:00")
    text = helpers.lines("multi.csv")
    assert text[9:] == ["# property.. power", "# repetition 1", "# timestamp,power(0),power(1)", "2020-01-01 00:00:00 UTC,+0,+0",
        "2020-01-01 00:10:00 UTC,+10,+10", "2020-01-01 00:20:00 UTC,+20,+20", "2020-01-01 00:30:00 UTC,+30,+30"]
    runner = record(helpers, "power", 'interval -1; multifile "multi.csv";')
    assert runner.returncode == exitcodes.RUNERR

def test_multi_recorder(helpers):
    """Multi-recorder items: other objects, the parent, globals, and items
    that are not found"""
    runner = helpers.run(TICK + LOAD + 'object load { name "L"; object multi_recorder { file "out.csv"; property "power,L:current,::clock,L:nothing,X:power"; interval -1; header_units NONE; }; }',
        stop="2020-01-01 00:10:00")
    assert runner.returncode == exitcodes.RUNERR
    assert rows(helpers, "out.csv")[:2] == ["timestamp,power,L:current,::clock,L:nothing,X:power", "2020-01-01 00:00:00 UTC,+0,+0+0i,2020-01-01 00:00:00 UTC"]
    assert any("unable to find object 'X'" in x for x in runner.stderr)

def test_multi_recorder_units(helpers):
    """Multi-recorder units: `line_units NONE` and `header_units ALL`"""
    helpers.run(TICK + LOAD + 'object load { name "L"; object multi_recorder { file "out.csv"; property "power[W],L:power,current[mA]"; interval -1; line_units NONE; header_units ALL; }; }',
        stop="2020-01-01 00:10:00")
    assert rows(helpers, "out.csv")[:3] == ["timestamp,power[W],power[kW],current[mA]", "2020-01-01 00:00:00 UTC,0,0,0+0i",
        "2020-01-01 00:10:00 UTC,10000,10,0+0i"]

def test_multi_recorder_errors(helpers):
    """A multi-recorder with nothing to record"""
    runner = helpers.run('object multi_recorder { file "out.csv"; property "x"; }')
    assert runner.returncode == exitcodes.RUNERR
    assert any("object has no parent for property 'x'" in x for x in runner.stderr)

@pytest.mark.parametrize("prop, value", [
    ("min(power)", "+1"), ("max(power)", "+3"), ("avg(power)", "+2"), ("mean(power)", "+2"),
    ("sum(power)", "+6"), ("prod(power)", "+6"), ("count(power)", "+3"), ("std(power)", "+1"),
    ("var(power)", "+0.666667"), ("mbe(power)", "+0"), ("max(power[W])", "+3000"), ("max|t|", "+2"),
    ("max(current.mag)", "+5"), ("max(current.real)", "+3"), ("max(current.imag)", "+4"),
    ("max(current.ang)", "+53.1301"), ("max(current.arg)", "+0.927295"), ("gamma(power)", "+2.67433"),
])
def test_aggregates(helpers, prop, value):
    """Collector aggregators"""
    runner = helpers.run(LOAD + f'object load {{ power 1; t -2; current 3+4j; }}\nobject load {{ power 2; }}\nobject load {{ power 3; }}\nobject collector {{ group "class=load"; property "{prop}"; file "out.csv"; interval 600; }}',
        stop="2020-01-01 00:20:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert rows(helpers, "out.csv")[1] == f"2020-01-01 00:00:00 UTC,{value}"

@pytest.mark.parametrize("prop, group, message", [
    ("nothing(power)", "class=load", "does not use a known aggregator"),
    ("power", "class=load", "is not valid"),
    ("max(power)", "class=nothing", "failed"),
    ("max(power)", "name=nothing", "results is an empty object list"),
    ("max(nothing)", "class=load", "is not found in the objects"),
    ("max(power.mag)", "class=load", "cannot have part 'mag'"),
    ("max(current)", "class=load", "cannot have part ''"),
    ("max(n)", "class=load", "cannot be aggregated"),
    ("max(t[W])", "class=load", "is unitless and cannot be converted"),
    ("max(power[s])", "class=load", "cannot use units 's'"),
    ("max(power[furlong])", "class=load", "has invalid units"),
    ("skew(power)", "class=load", "skewness aggregation is not implemented"),
])
def test_aggregate_errors(helpers, prop, group, message):
    """Collector aggregate errors"""
    runner = helpers.run(LOAD + f'object load {{ power 1; }}\nobject collector {{ group "{group}"; property "{prop}"; file "out.csv"; interval 600; }}', stop="2020-01-01 00:10:00")
    assert runner.returncode == exitcodes.RUNERR
    assert any(message in x for x in runner.stderr), runner.stderr

def test_collector_options(helpers):
    """Collector default file name, limit, trigger, and `TYPE:FILE`"""
    runner = helpers.run(TICK + LOAD + 'object load { name "L"; }\nobject collector { group "class=load"; property "max(power)"; interval -1; limit 1; }',
        stop="2020-01-01 01:00:00")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert rows(helpers, "class_load.txt") == ["timestamp,max(power)", "2020-01-01 00:00:00 UTC,+0"]
    runner = helpers.run(TICK + LOAD + 'object load { }\nobject collector { group "class=load"; property "max(power)"; interval 600; trigger ">+15"; file "t.csv"; }',
        stop="2020-01-01 01:00:00")
    assert runner.returncode == exitcodes.SUCCESS
    assert rows(helpers, "t.csv") == ["timestamp,max(power)", "2020-01-01 00:20:00 UTC,+20", "2020-01-01 00:30:00 UTC,+30",
        "2020-01-01 00:40:00 UTC,+40", "2020-01-01 00:50:00 UTC,+50"]
    runner = helpers.run(LOAD + 'object load { }\nobject collector { group "class=load"; property "max(power)"; file "memory:x"; }', stop="2020-01-01 00:10:00")
    assert runner.stderr[0].endswith("unable to locate tape_memory.so")

def test_histogram_bins(helpers):
    """Auto-sized bins, a parent, and complex parts"""
    helpers.run(LOAD + 'object load { power 5; current 3+4j; object histogram { property "power"; min 0; max 10; bin_count 2; filename "a.csv"; samplerate 0; countrate 0; }; '
        'object histogram { property "current.mag"; bins "[0-5],(5-10]"; filename "b.csv"; samplerate 0; countrate 0; limit 2; }; }', stop="2020-01-01 00:00:00", header="FULL")
    assert rows(helpers, "a.csv") == ["[0.000000..5.000000),[5.000000..10.000000]", "2020-01-01 00:00:00 UTC,0,1"]
    assert rows(helpers, "b.csv") == ["2020-01-01 00:00:00 UTC,1,0"]

@pytest.mark.parametrize("glm, message", [
    ('property "power"; bins "1-2";', "Histogram has no parent and no group"),
    ('property "power"; group "class=nothing";', "Histogram group could not be parsed"),
    ('property "power"; group "name=nothing";', "Histogram group is an empty set"),
    ('property "nothing"; group "class=load"; bins "1-2";', "unable to find prop 'nothing'"),
    ('property "power"; group "class=load"; bins "x";', "parse_bin failure"),
    ('property "power"; group "class=load";', "Histogram has neither bins or a bin range"),
    ('property "status"; group "class=load"; bins "MAYBE";', "unable to find property 'MAYBE'"),
    ('property "current.foo"; group "class=load"; bins "1-2";', "Unable to resolve complex part"),
])
def test_histogram_errors(helpers, glm, message):
    """Histogram initialization errors"""
    runner = helpers.run(LOAD + f'object load {{ }}\nobject histogram {{ {glm} filename "x.csv"; samplerate 10; countrate 10; }}', stop="2020-01-01 00:10:00")
    assert runner.returncode in (exitcodes.INIERR, exitcodes.RUNERR)
    assert any(message in x for x in runner.stderr), runner.stderr

def test_group_recorder(helpers):
    """Group recorders: every pass, on change, units, and limits"""
    glm = TICK + LOAD + 'object load { name "L1"; }\nobject load { }\n'
    helpers.run(glm + 'object group_recorder { group "class=load"; property "power"; file "a.csv"; interval -1; print_units TRUE; }', stop="2020-01-01 00:20:00")
    assert rows(helpers, "a.csv") == ["timestamp,L1,load:2", "2020-01-01 00:00:00 UTC,+0 kW,+0 kW", "2020-01-01 00:10:00 UTC,+10 kW,+10 kW",
        "2020-01-01 00:20:00 UTC,+20 kW,+20 kW"]
    helpers.run(glm + 'object group_recorder { group "class=load"; property "power"; file "b.csv"; interval 0; flush_interval -1; limit 2; }', stop="2020-01-01 00:20:00")
    assert rows(helpers, "b.csv") == ["timestamp,L1,load:2", "2020-01-01 00:00:00 UTC,+0,+0", "2020-01-01 00:10:00 UTC,+10,+10"]
    assert helpers.lines("b.csv")[-1] == "# end of file"

@pytest.mark.parametrize("glm, code, message", [
    ('property "power"; file "x.csv"; strict TRUE;', exitcodes.INIERR, "no group defined"),
    ('group "class=load"; property "power"; strict TRUE;', exitcodes.INIERR, "no filename defined in strict mode"),
    ('group "class=load"; property "power"; file "x.csv"; interval -2;', exitcodes.INIERR, "invalid write_interval"),
    ('group "class=load"; property "nothing"; file "x.csv";', exitcodes.INIERR, "unable to find property 'nothing'"),
    ('group "name=nothing"; property "power"; file "x.csv"; strict TRUE;', exitcodes.INIERR, "the defined group returned an empty set"),
    ('group "class=nothing"; property "power"; file "x.csv"; strict TRUE;', exitcodes.INIERR, "unable to construct a set"),
    ('group "class=load"; property "power"; file "/nonexistent/x.csv"; strict TRUE;', exitcodes.INIERR, "unable to open file"),
])
def test_group_recorder_errors(helpers, glm, code, message):
    """Group recorder initialization errors"""
    runner = helpers.run(LOAD + f'object load {{ }}\nobject group_recorder {{ {glm} }}', stop="2020-01-01 00:10:00")
    assert runner.returncode == code, runner.stderr
    assert any(message in x for x in runner.stderr), runner.stderr

def test_group_recorder_warnings(helpers):
    """Without `strict`, problems turn the recorder off with a warning"""
    m = helpers.model(LOAD + 'object load { }\nobject group_recorder { property "power"; }\nobject group_recorder { group "class=load"; property "power"; }')
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert any("no group defined" in x for x in runner.stderr)
    assert any("auto-generating 'group_recorder-2.csv'" in x for x in runner.stderr)

def test_end_of_run(helpers):
    """When the run ends, pending samples are written and files are closed
    with their end lines"""
    helpers.run(TICK + LOAD + 'object load { name "L"; }\n'
        'object collector { group "class=load"; property "max(power)"; interval 1200; file "c.csv"; }\n'
        'object multi_recorder { property "L:power"; interval 1200; file "m.csv"; }\n'
        'object histogram { group "class=load"; property "power"; bins "0..100"; samplerate 600; countrate 1200; limit 10; filename "h.csv"; }\n'
        'object group_recorder { group "class=load"; property "power"; file "g.csv"; interval 1200; }', stop="2020-01-01 00:40:00", header="FULL")
    for file, last in (("c.csv", "2020-01-01 00:40:00 UTC,+40"), ("m.csv", "2020-01-01 00:40:00 UTC,+40")):
        text = helpers.lines(file)
        assert text[-2:] == [last, "# end of tape"], file
    assert helpers.lines("h.csv")[-1] == "# end of tape"
    assert helpers.lines("g.csv")[-2:] == ["2020-01-01 00:40:00 UTC,+40", "# end of file"]

def test_multi_recorder_line_units_all(helpers):
    """`line_units ALL` writes each property's own unit"""
    helpers.run(LOAD + 'object load { name "L"; power 2; object multi_recorder { property "power,L:current"; file "out.csv"; line_units ALL; }; }')
    assert rows(helpers, "out.csv")[1] == "2020-01-01 00:00:00 UTC,+2 kW,+0+0i A"

def test_group_recorder_flush_interval(helpers):
    """A positive `flush_interval` flushes the file"""
    m = helpers.model(TICK + LOAD + 'object load { }\nobject group_recorder { group "class=load"; property "power"; file "g.csv"; interval 600; flush_interval 1200; }', stop="2020-01-01 01:00:00")
    seen = []
    Runner(model=m, progress=lambda timestamp: seen.append(len(helpers.lines("g.csv"))))
    assert seen[:3] == [2, 2, 4]
