"""Players, shapers, and multiplayers"""

import pytest

from arras import exitcodes
from arras.runner import Runner

LOAD = "class load { double power[kW]; complex current[A]; double value; }\n"

def play(helpers, text:str, glm:str, stop:str="2020-01-01 03:00:00", **kwargs) -> tuple[Runner,list[tuple[int,str]]]:
    """Run a player on a `load` object; returns the runner and `power` at
    each committed time"""
    helpers.write("in.player", text)
    m = helpers.model(LOAD + f'object load {{ name "L"; object player {{ name "p"; file "in.player"; {glm} }}; }}', stop=stop, **kwargs)
    values = []
    runner = Runner(model=m, progress=lambda timestamp: values.append((timestamp, m.get_property("L", "power"))))
    return runner, values

def test_absolute_and_relative(helpers):
    """Absolute dates, relative times, epoch seconds, and units of time"""
    runner, values = play(helpers, "# comment\n\n2020-01-01 00:00:00,1\n+1h,2\n1577844000,3\n+30m, 4\n+1d,5\n", "property power;")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert [v for _, v in values[:-1]] == ["1", "2", "3", "4"]
    assert values[3][0] == 1577845800

def test_loop(helpers):
    """Looping replays relative times only"""
    runner, values = play(helpers, "2020-01-01 00:00:00,1\n+1h,2\n", "property power; loop 2;", stop="2020-01-01 06:00:00")
    assert runner.returncode == exitcodes.SUCCESS
    assert [v for _, v in values[:-1]] == ["1", "2", "2", "2"]

def test_units_and_parts(helpers):
    """Values in another unit and parts of a complex property"""
    runner, _ = play(helpers, "2020-01-01 00:00:00,1.5,2,3\n", "property power[MW],current.real,current.imag;")
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert runner.model.get_property("L", "power") == "1500.0 kW"
    assert runner.model.get_property("L", "current").startswith("2.0+3.0")

def test_header(helpers):
    """Properties named by a CSV header"""
    runner, _ = play(helpers, "timestamp,power,value\n2020-01-01 00:00:00,1,2\n", "")
    assert runner.model.get_property("p", "property") == "power,value"
    assert runner.model.get_property("L", "value") == "2"

def test_zone_and_dateformat(helpers):
    """Times with a zone abbreviation, and US dates"""
    runner, values = play(helpers, "2020-01-01 01:00:00 UTC,1\n", "property power;")
    assert values[0][1] == "0.0" and values[1] == (1577840400, "1")
    helpers.write("us.player", "01-02-2020 00:00:00,7\n")
    m = helpers.model(LOAD + 'object load { name "L"; object player { property power; file "us.player"; }; }', stop="2020-01-03 00:00:00")
    m.globals.set("dateformat", "US")
    Runner(model=m)
    assert m.get_property("L", "power") == "7"

def test_fraction(helpers):
    """A time with a fraction of a second is written at the next second"""
    runner, values = play(helpers, "2020-01-01 00:00:00,1\n2020-01-01 00:00:10.5,2\n2020-01-01 01:00:00,3\n", "property power;")
    assert runner.returncode == exitcodes.SUCCESS
    assert (1577836811, "2") in values

def test_no_parent(helpers):
    """A player without a parent plays into its own `value`"""
    helpers.write("in.player", "2020-01-01 00:00:00,4\n")
    m = helpers.model('class player { double value; }\nobject player { name "p"; file "in.player"; }')
    runner = Runner(model=m)
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert m.get_property("p", "value") == "4"

@pytest.mark.parametrize("text, glm, message", [
    ("2020-01-01 00:00:00,1\n", 'property power; file "missing.player";', "Unable to open player file"),
    ("2020-01-01 00:00:00,1\n", "property nothing;", "property 'nothing' not found"),
    ("2020-01-01 00:00:00,1\n", "property power[furlong];", "unable to find unit 'furlong'"),
    ("2020-01-01 00:00:00,1\n", "property power[s];", "unable to convert property 'power' units to 's'"),
    ("2020-01-01 00:00:00,1\n", "property value[kW];", "is unitless, ignoring unit conversion"),
    ("2020-01-01 00:00:00,1\n", "property power,value;", "not enough values on line"),
    ("2020-01-01 00:00:00,x\n", "property power;", "unable to set L.power"),
    ("timestamp\n", "", "CSV header missing required property names"),
    ("", "", "missing either property list of CSV header"),
])
def test_errors(helpers, text, glm, message):
    """Player errors make the run end with `RUNERR`"""
    runner, _ = play(helpers, text, glm)
    assert runner.returncode == exitcodes.RUNERR
    assert any(message in x for x in runner.stderr), runner.stderr

@pytest.mark.parametrize("text, message", [
    ("nonsense\n", "unable to split input string"),
    ("x y,1\n", "unable to parse timestamp"),
])
def test_warnings(helpers, text, message):
    """Lines that cannot be read write warnings"""
    helpers.write("in.player", text)
    m = helpers.model(LOAD + 'object load { object player { property power; file "in.player"; }; }')
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert any(message in x for x in runner.stderr), runner.stderr

def test_default_file(helpers):
    """The default file name is `CLASS-ID.FILETYPE` of the parent"""
    helpers.write("load-0.txt", "2020-01-01 00:00:00,9\n")
    m = helpers.model(LOAD + 'object load { name "L"; object player { property power; }; }')
    Runner(model=m)
    assert m.get_property("L", "power") == "9"

SHAPE = "shape {\n# comment\n* 0-11 * * *,1\n* 12-23 * * *,2\n}\n"

def test_shaper_direct(helpers):
    """A direct shaper writes the value of the hour and runs again each hour
    (values are kept as 0 to 255 of the peak, so 1 is 128/255*2)"""
    helpers.write("shape.txt", SHAPE)
    m = helpers.model('class load { double power; }\nobject load { name "L"; }\nobject shaper { file "shape.txt"; group "class=load"; property "power"; magnitude 3; }',
        start="2020-01-01 10:00:00", stop="2020-01-01 13:00:00")
    values = []
    runner = Runner(model=m, progress=lambda timestamp: values.append(round(float(m.get_property("L", "power")), 4)))
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert values[:4] == [1.0039, 1.0039, 2.0, 2.0]

def test_shaper_events(helpers):
    """A shaper with events starts and ends events of `magnitude`"""
    helpers.write("shape.txt", SHAPE)
    m = helpers.model('class load { double power; }\nobject load:..3 { }\nobject shaper { file "shape.txt"; group "class=load"; property "power"; magnitude 1; events 100; }',
        stop="2020-01-02 00:00:00")
    seen = set()
    runner = Runner(model=m, progress=lambda timestamp: seen.update(m.get_property(x, "power") for x in m.objects if x.startswith("load")))
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr
    assert {"1.0", "0"} <= seen

@pytest.mark.parametrize("text, glm, message", [
    ("shape {\n5 * * * *,1\n}\n", 'group "class=load"; property "power";', "minutes are ignored"),
    ("shape {\n* x * * *,1\n}\n", 'group "class=load"; property "power";', "hours in"),
    ("shape {\n* * * *\n}\n", 'group "class=load"; property "power";', "missing specification"),
    (SHAPE, 'group "class=load"; property "nothing";', "property nothing not found"),
    (SHAPE, 'group "class=load"; property "power"; file "missing.txt";', "shaper file missing.txt"),
])
def test_shaper_errors(helpers, text, glm, message):
    """Shape file and target errors"""
    helpers.write("shape.txt", text)
    glm = glm if "file" in glm else glm + ' file "shape.txt";'
    runner = helpers.run(f'class load {{ double power; char32 name_; }}\nobject load {{ }}\nobject shaper {{ {glm} }}')
    assert runner.returncode == exitcodes.RUNERR
    assert any(message in x for x in runner.stderr), runner.stderr

def test_shaper_warnings(helpers):
    """An empty group or a target that is not a double"""
    helpers.write("shape.txt", SHAPE)
    m = helpers.model('class load { int32 n; }\nobject load { }\nobject shaper { file "shape.txt"; group "class=load"; property "n"; }\n'
        'object shaper { file "shape.txt"; group "class=nothing"; property "n"; }')
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert any("is not a double" in x for x in runner.stderr)
    assert any("is empty" in x for x in runner.stderr)

def test_multiplayer_errors(helpers):
    """Multiplayer `on_error` cases"""
    helpers.write("data.csv", "timestamp,x,n\n2020-01-01 00:00:00 UTC,1,2,3\n2020-01-01 01:00:00 UTC,abc\n2020-01-01 00:30:00 UTC,1,2\n")
    m = helpers.model('class test { double x[W]; int32 n; }\nobject test { name t; object multiplayer { name mp; file "data.csv"; on_error WARN; }; }', stop="2020-01-01 02:00:00")
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert any("ignoring extra data '3'" in x for x in runner.stderr), runner.stderr
    assert runner.returncode == exitcodes.INIERR
    m = helpers.model('class test { double x[W]; int32 n; }\nobject test { object multiplayer { file "data.csv"; on_error STOP; }; }', stop="2020-01-01 02:00:00")
    runner = Runner(model=m)
    assert runner.returncode == exitcodes.RUNERR
    assert any("extra data '3' at index" in x for x in runner.stderr)
    m = helpers.model('class test { double x[W]; int32 n; }\nobject test { name t; object multiplayer { file "data.csv"; on_error IGNORE; }; }', stop="2020-01-01 02:00:00")
    runner = Runner(model=m)
    assert any("invalid index (out of order)" in x for x in runner.stderr)

@pytest.mark.parametrize("glm, message", [
    ('file "missing.csv";', "file 'missing.csv' not found"),
    ('', "no input file specified"),
    ('file "data.csv"; indexname "time";', "column 'timestamp' is not 'time'"),
    ('file "data.csv"; property "nothing";', "property 'nothing' is not found"),
    ('file "data.csv"; property "x[furlong]";', "unit 'furlong' is not valid"),
    ('file "data.csv"; property "x[s]";', "cannot be converted"),
])
def test_multiplayer_init_errors(helpers, glm, message):
    """Multiplayer initialization errors"""
    helpers.write("data.csv", "timestamp,x\n2020-01-01 00:00:00 UTC,1\n")
    runner = helpers.run(f'class test {{ double x[W]; }}\nobject test {{ object multiplayer {{ {glm} }}; }}')
    assert runner.returncode == exitcodes.INIERR
    assert any(message in x for x in runner.stderr), runner.stderr

def test_multiplayer_complex_and_globals(helpers):
    """A multiplayer without a parent writes globals; complex values"""
    helpers.write("data.csv", "timestamp,z[kVA],g\n2020-01-01 00:00:00 UTC,1+2j,5\n")
    m = helpers.model('class test { complex z[VA]; }\nobject test { name t; object multiplayer { file "data.csv"; property "z[kVA]"; on_error IGNORE; }; }\n'
        'object multiplayer { file "data.csv"; property "z,g"; }')
    m.globals.create("z", "0+0j", ptype="char32")
    m.globals.create("g", "0", ptype="int32")
    runner = Runner(model=m)
    assert m.get_property("t", "z") == "1000.0+2000.0j VA"
    assert m.globals.get("g") == "5"
    assert runner.returncode == exitcodes.SUCCESS, runner.stderr

def test_loop_header(helpers):
    """A looping player skips its CSV header when it starts again"""
    helpers.write("in.player", "timestamp,power\n2020-01-01 00:00:00,1\n+1h,2\n")
    m = helpers.model(LOAD + 'object load { name "L"; object player { file "in.player"; loop 1; }; }', stop="2020-01-01 04:00:00")
    m.globals.set("warn", "TRUE")
    runner = Runner(model=m)
    assert runner.stderr == []
    assert m.get_property("L", "power") == "2"

def test_shaper_calendar(helpers):
    """Shaper months are 1 to 12 and days 1 to 31, as in cron"""
    helpers.write("shape.txt", "shape {\n* * 31 12 *,2\n* * 1-30 1-11 *,1\n}\n")
    m = helpers.model('class load { double power; }\nobject load { name "L"; }\nobject shaper { file "shape.txt"; group "class=load"; property "power"; }',
        start="2020-12-31 12:00:00")
    Runner(model=m)
    assert round(float(m.get_property("L", "power")), 4) == round(2/3, 4)
