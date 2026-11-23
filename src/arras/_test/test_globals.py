"""Tests of arras.globals"""

import os
import doctest
import re
import datetime

import pytest

import arras.globals
from arras.globals import Globals, Globalvar, GlobalsError, TS_NEVER, \
    geocode_encode, geocode_decode

@pytest.fixture(name="g")
def fixture_globals():
    """Globals with a fixed random seed, cleaned up after each test"""
    result = Globals(randomseed=1)
    yield result
    result.cleanup()

#
# Defaults
#
def test_count_and_order(g):
    names = list(g)
    assert len(g) == 160
    assert names[:6] == ["version.major", "version.minor", "version.patch",
        "version.build", "version.branch", "version"]
    assert names[-2:] == ["origin", "gitbranch"]
    assert names.index("website") + 1 == names.index("urlbase")

@pytest.mark.parametrize("name,value", [
    ("environment", "batch"),
    ("quiet", "FALSE"),
    ("warn", "TRUE"),
    ("iteration_limit", "100"),
    ("workdir", "."),
    ("dumpfile", "gridlabd.json"),
    ("clock", "INIT"),
    ("starttime", "2000-01-01 00:00:00 UTC"),
    ("stoptime", "NEVER"),
    ("double_format", "%+lg"),
    ("complex_output_format", "DEFAULT"),
    ("strictnames", "TRUE"),
    ("dateformat", "ISO"),
    ("init_sequence", "DEFERRED"),
    ("realtime_metric", "+0"),
    ("technology_readiness_level", "UNKNOWN"),
    ("random_number_generator", "RNG3"),
    ("mainloop_state", "INIT"),
    ("slave_port", "6267"),
    ("module_compiler_flags", "NONE"),
    ("validate", "TSTD|RALL"),
    ("sanitize", "NAMES|POSITIONS"),
    ("sanitize_prefix", "GLD_"),
    ("deltamode_maximumtime", "3600000000000"),
    ("output_message_context", "ALL"),
    ("literal_if", "TRUE"),
    ("validto_context", "SYNC"),
    ("timezone_locale", "UTC"),
    ("glm_save_options", "LEGACY"),
    ("filesave_options", "ALL"),
    ("json_complex_format", "STRING"),
    ("profile_output_format", ""),
    ("country", "US"),
    ("organization", "arras-energy"),
    ("wget_options", "maxsize:100MB;update:newer"),
    ("inline_block_size", str(16*65536)),
    ])
def test_defaults(g, name, value):
    assert g.get(name) == value

def test_types_and_access(g):
    assert g.find("version").ptype == "char1024"
    assert g.find("version").access == "REFERENCE"
    assert g.find("streaming_io").access == "PROTECTED"
    assert g.find("exit_code").ptype == "int16"
    assert g.find("master_port").ptype == "int64"
    assert g.find("dateformat").keywords == {"ISO":0, "US":1, "EURO":2, "ISO8601":3}
    assert g.find("quiet").description == "quiet output status flag"

def test_aliases(g):
    for alias, target in (("test","debugger"), ("website","urlbase"),
            ("curl_options","wget_options")):
        assert g.find(alias) is g.find(target)
    g.set("curl_options","x")
    assert g.get("wget_options") == "x"

def test_folder_defaults_from_environment(monkeypatch):
    monkeypatch.setenv("GLD_ETC","/opt/etc")
    monkeypatch.setenv("GLD_BIN","/opt/bin")
    monkeypatch.setenv("PYTHONPATH","/opt/py")
    g = Globals()
    assert g.get("datadir") == "/opt/etc"
    assert g.get("bindir") == "/opt/bin"
    assert g.get("pythonexec") == "/opt/bin/python3"
    assert g.get("configpath") == "/opt/etc/solver_py.conf"
    assert g.get("pythonpath") == "/opt/py"

def test_tmp_default(monkeypatch):
    monkeypatch.setenv("GLTEMP","/scratch")
    assert Globals().get("tmp") == "/scratch"
    monkeypatch.delenv("GLTEMP")
    monkeypatch.setenv("HOME","/home/user")
    assert Globals().get("tmp") == "/home/user/.gridlabd/tmp"

def test_constructor_overrides():
    g = Globals({"version.branch":"develop"}, threadcount=4, quiet="TRUE")
    assert g.get("version.branch") == "develop"
    assert g["threadcount"] == 4
    assert g["quiet"] is True
    with pytest.raises(GlobalsError):
        Globals(no_such_global=1)

#
# Set and get
#
@pytest.mark.parametrize("name,text,value,string", [
    ("quiet", "true", True, "TRUE"),
    ("quiet", "0", False, "FALSE"),
    ("threadcount", "8", 8, "8"),
    ("master_port", "-12345678901", -12345678901, "-12345678901"),
    ("realtime_metric", "0.5", 0.5, "+0.5"),
    ("realtime_metric", "NAN", None, "NAN"),
    ("environment", '"quoted value" extra', "quoted value", "quoted value"),
    ("dateformat", "US", "US", "US"),
    ("dateformat", "2", "EURO", "EURO"),
    ("validate", "TALL|RGLM", {"TSTD","TOPT","RGLM"}, "TSTD|TOPT|RGLM"),
    ("validate", "0x0001", {"TRUN"}, "TRUN"),
    ("starttime", "2020-01-01 00:00:00 UTC", 1577836800, "2020-01-01 00:00:00 UTC"),
    ("starttime", "2020-01-01T08:00:00+08:00", 1577836800, "2020-01-01 00:00:00 UTC"),
    ("starttime", "2020-01-01T00:00:00Z", 1577836800, "2020-01-01 00:00:00 UTC"),
    ("starttime", "2020/01/01", 1577836800, "2020-01-01 00:00:00 UTC"),
    ("stoptime", "NEVER", TS_NEVER, "NEVER"),
    ("clock", "INIT", 0, "INIT"),
    ("clock", "1h", 3600, "1.000000h"),
    ("clock", "2d", 172800, "2.000000d"),
    ])
def test_set_from_string(g, name, text, value, string):
    g.set(name,text)
    if value is not None:
        assert g[name] == value
    assert g.get(name) == string

def test_set_definition_form(g):
    g.set("threadcount=3")
    assert g["threadcount"] == 3
    g.set("environment matlab")
    assert g["environment"] == "matlab"
    with pytest.raises(GlobalsError):
        g.set("=3")

def test_set_typed(g):
    g["quiet"] = 1
    assert g["quiet"] is True
    g["validate"] = ["TRUN","RDIR"]
    assert g.get("validate") == "TRUN|RDIR"
    g["starttime"] = datetime.datetime(2021,1,1,tzinfo=datetime.timezone.utc)
    assert g.get("starttime") == "2021-01-01 00:00:00 UTC"
    g["starttime"] = datetime.datetime(2021,1,1)
    assert g.get("starttime") == "2021-01-01 00:00:00 UTC"

def test_set_errors(g):
    with pytest.raises(GlobalsError, match="strict naming"):
        g.set("undefined_name","x")
    for name, value in (("quiet","maybe"), ("threadcount","many"),
            ("exit_code","40000"), ("dateformat","CHINA"),
            ("validate","TSTD|NOPE"), ("realtime_metric","1 kW"),
            ("realtime_metric",""), ("starttime","yesterday"),
            ("clock","3x")):
        with pytest.raises(GlobalsError):
            g.set(name,value)

def test_set_without_strictnames(g):
    g.set("strictnames","FALSE")
    g.set("my_name","my value")
    assert g.find("my_name").ptype == "char1024"
    assert g.get("my_name") == "my value"

def test_char_truncation(g):
    g.set("country","ABCDEFGHIJ")
    assert g.get("country") == "ABCDEFG"

def test_double_format(g):
    g.set("double_format","%.3lf")
    g.set("realtime_metric","0.12345")
    assert g.get("realtime_metric") == "0.123"

def test_double_unit(g):
    g.create("power",1.5,unit="kW")
    assert g.get("power") == "+1.5 kW"
    g.set("power","2 kW")
    assert g["power"] == 2.0
    with pytest.raises(GlobalsError):
        g.set("power","2 MW")
    with pytest.raises(GlobalsError):
        g.create("name","x",unit="kW")

def test_dateformats(g):
    g.set("starttime","2020-03-04 05:06:07 UTC")
    g.set("dateformat","US")
    assert g.get("starttime") == "03-04-2020 05:06:07 UTC"
    g.set("starttime","03/04/2020 05:06:07")
    assert g.get("starttime") == "03-04-2020 05:06:07 UTC"
    g.set("dateformat","EURO")
    assert g.get("starttime") == "04-03-2020 05:06:07 UTC"
    g.set("dateformat","ISO8601")
    assert g.get("starttime") == "2020-03-04T05:06:07-00:00"

def test_timezone(g):
    g.set("timezone_locale","America/Los_Angeles")
    g.set("starttime","2020-01-01 00:00:00 UTC")
    assert g.get("starttime") == "2019-12-31 16:00:00 PST"
    g.set("starttime","2020-07-01 00:00:00")
    assert g["starttime"] == 1593586800
    g.set("timezone_locale","Not/AZone")
    assert g.get("starttime").endswith("UTC")

def test_relative_timestamps(g):
    g.set("clock","2020-01-01 00:00:00 UTC")
    g.set("stoptime","+1d")
    assert g.get("stoptime") == "2020-01-02 00:00:00 UTC"
    g.set("pauseat","NOW")
    assert g["pauseat"] == g["clock"]

#
# Create, container, dump, save
#
def test_create(g):
    assert g.create("a",True).ptype == "bool"
    assert g.create("b",1).ptype == "int32"
    assert g.create("c",1.0).ptype == "double"
    assert g.create("d","x").ptype == "char1024"
    assert g.create("e",datetime.datetime(2020,1,1)).ptype == "timestamp"
    var = g.create("mode",ptype="enumeration",keywords={"OFF":0,"ON":1},value="ON")
    assert isinstance(var,Globalvar)
    assert repr(var) == "<Globalvar mode:enumeration=ON>"
    assert g["mode"] == "ON"
    for args, kwargs in ((("a",),{}), (("x",),{"ptype":"float"}),
            (("x",),{"access":"OPEN"}), (("",),{}), (("x"*64,),{})):
        with pytest.raises(GlobalsError):
            g.create(*args,**kwargs)

def test_push(g):
    g.push("pushed","one")
    g.push("pushed","two")
    assert g.get("pushed") == "two"
    assert list(g).count("pushed") == 1

def test_container(g):
    assert "clock" in g and "nothing" not in g
    assert g.isdefined("test")
    assert g.getvalue("nothing") is None
    assert g.get("nothing") is None
    assert g.find("nothing") is None
    with pytest.raises(KeyError):
        _ = g["nothing"]
    assert repr(g) == "<Globals (160 variables)>"

def test_dump(g):
    dump = g.dump()
    assert len(dump) == 160
    assert dump[7] == "environment=batch;"
    assert "website=http://www.gridlabd.org/;" in dump

def test_saveall(g):
    text = g.saveall()
    assert "#ifdef environment\n#define environment=batch\n" \
        "#else\n#set environment=batch\n#endif\n" in text
    g.create("mod::x",1)
    assert "mod::x" not in g.saveall()
    g.set("glm_save_options","MINIMAL")
    assert g.saveall() == ""

#
# Pseudo-globals
#
def test_simple_pseudoglobals(g):
    guid = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}"
    assert re.fullmatch(guid,g.get("GUID"))
    assert g.get("GUID") != g.get("GUID")
    assert g.get("RUN") == g.get("RUN")
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC",g.get("TODAY"))
    assert re.fullmatch(r"\d{8}-\d{6}",g.get("NOW"))
    assert re.fullmatch(r"\d\d/\d\d",g.get("NOW %m/%d"))
    assert 0 <= float(g.get("URAND")) <= 1
    float(g.get("NRAND"))
    assert g.get("PID") == str(os.getpid())
    assert g.get("PYTHON") == "1"
    assert [g.get(x) for x in ("LINUX","APPLE","WINDOWS")].count("1") == 1

def test_seq(g):
    assert g.get("SEQ_A:INIT") == "0"
    assert g.get("SEQ_A:INC") == "1"
    assert g.get("SEQ_A:INC") == "2"
    assert g.get("SEQ_A") == "2"
    assert g.get("SEQ_A:INIT") is None
    assert g.get("SEQ_B:INC") is None
    assert g.get("SEQ_A:BAD") is None

def test_shell_and_python(g):
    assert g.get("SHELL echo 1 2 3") == "1 2 3 "
    assert g.get("PYTHON [1,2,3]") == "[1, 2, 3]"
    g.python_namespace["x"] = 5
    assert g.get("PYTHON x*2") == "10"

@pytest.mark.parametrize("spec,value", [
    ("RANGE 1,3,1", "1 2 3"),
    ("RANGE,0,1,0.25", "0,0.25,0.5,0.75,1"),
    ("RANGE;5,5,1", "5"),
    ("RANGE:1,10,3", "1:4:7:10"),
    ])
def test_range(g, spec, value):
    assert g.get(spec) == value

def test_range_bad_step(g):
    with pytest.raises(GlobalsError):
        g.get("RANGE,1,2,0")

def test_findfile(g, tmp_path, monkeypatch):
    (tmp_path / "weather.tmy3").write_text("")
    monkeypatch.setenv("GLPATH",str(tmp_path))
    assert g.get("FINDFILE weather.tmy3") == str(tmp_path / "weather.tmy3")
    path = str(tmp_path / "weather.tmy3")
    assert g.get(f"FINDFILE {path}") == path
    assert g.get("FINDFILE missing.tmy3") == ""
    assert g.get("FINDFILE /missing.tmy3") == ""

def test_file_parts(g):
    g.set("strictnames","FALSE")
    g.set("model","/tmp/models/test.glm")
    assert g.get("FILENAME $model") == "test"
    assert g.get("FILEPATH $model") == "/tmp/models"
    assert g.get("FILETYPE $model") == "glm"
    assert g.get("FILENAME name") == "name"
    assert g.get("FILEPATH name") == "."
    assert g.get("FILETYPE name") == ""
    assert g.get("FILENAME $missing") is None
    assert g.get("FILEPATH $missing") is None
    assert g.get("FILETYPE $missing") is None

def test_object_hooks(g):
    assert g.get("FIND class=test") == ""
    assert g.get("object.last") is None
    g.object_finder = lambda criteria: ["my_test","test:1"]
    g.object_last = lambda: "test:2"
    g.object_locator = lambda name: (37.4,-122.2) if name == "my_test" else (99.0,0.0)
    assert g.get("FIND class=test") == "my_test test:1"
    assert g.get("object.last") == "test:2"
    assert g.get("object.find x") is None
    assert g.get("GEOCODE my_test#6") == "9q9hg2"
    assert g.get("GEOCODE bad_object") == ""

def test_geocode(g):
    assert g.get("GEOCODE 37.4,-122.2") == "9q9hg"
    assert g.get("GEOCODE 37.4,-122.2#6") == "9q9hg2"
    assert g.get("GEOCODE 9q9hg2") == "37.40,-122.20"
    assert g.get("GEOCODE 9q9hg2.lat") == "37.40"
    assert g.get("GEOCODE 9q9hg2.lon") == "-122.20"
    assert g.get("GEOCODE 9q9hg2.alt") == ""
    assert g.get("GEOCODE not-a-hash!") == ""

def test_geocode_functions():
    assert geocode_encode(57.64911,10.40744,11) == "u4pruydqqvj"
    assert geocode_decode("u4pruydqqvj") == "57.649111,10.407440"
    assert geocode_decode("U4PRU") == geocode_decode("u4pru")
    assert geocode_decode("u") == "67.500000,22.500000"
    assert geocode_decode("") is None
    assert geocode_decode("u4.x") is None

def test_tmpfile(g, tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR",str(tmp_path))
    name = g.get("TMPFILE py:A")
    assert name == f"{tmp_path}/gridlabd_tmp_localhost_{os.getpid()}_A.py"
    assert os.path.exists(name)
    assert g.get("TMPFILE py:A") == name
    other = g.get("TMPFILE")
    assert other.endswith(".tmp") and other != name
    assert g.get("TMPFILE B").endswith("_B.tmp")
    g.cleanup()
    assert not os.path.exists(name)

def test_random(g):
    assert g.get("RANDOM last") == "1"
    value = float(g.get("RANDOM"))
    assert 0 <= value < 1
    assert g.get("RANDOM last") == g.get("RANDOM last")
    assert 0 <= int(g.get("RANDOM 8")) < 256
    assert g.get("RANDOM last") == g.get("RANDOM last")
    assert 0 <= int(g.get("RANDOM 64")) < 2**64
    for spec in ("uniform(2,3)", "normal(0,1)", "lognormal(0,1)", "exponential(1)",
            "bernoulli(0.5)", "pareto(1,2)", "rayleigh(1)", "weibull(1,2)",
            "gamma(2)", "gamma(2,3)", "beta(2,3)", "triangle(0,1)",
            "degenerate(4)", "sampled(1,2,3)"):
        float(g.get(f"RANDOM {spec}"))
    assert g.get("RANDOM degenerate(4)") == "4"
    assert 2 <= float(g.get("RANDOM uniform(2,3)")) <= 3
    assert g.get("RANDOM sampled(7)") == "7"
    for spec in ("cauchy(0,1)", "uniform(1)", "nonsense", "exponential(0)",
            "pareto(1,0)", "weibull(1,0)", "gamma(1,2,3)", "normal(a,b)"):
        assert g.get(f"RANDOM {spec}") is None

def test_random_is_reproducible():
    a, b = Globals(randomseed=42), Globals()
    b.set("randomseed","42")
    assert [a.get("RANDOM") for _ in range(3)] == [b.get("RANDOM") for _ in range(3)]

#
# Expansions
#
@pytest.fixture(name="e")
def fixture_expansions(g):
    """Globals with an int32 `n=5` and a string `s=hello world`"""
    g.create("n",5)
    g.create("s","hello world")
    return g

@pytest.mark.parametrize("spec,value", [
    ("s:-other", "hello world"),
    ("missing:-other", "other"),
    ("s:+yes", "yes"),
    ("missing:+yes", ""),
    ("s:6", "world"),
    ("s:0:5", "hello"),
    ("missing:2", None),
    ("s/o/0", "hell0 world"),
    ("s//o/0", "hell0 w0rld"),
    ("s/o", "hell world"),
    ("missing/o/0", None),
    ("n+2", "7"),
    ("n-7", "-2"),
    ("n*3", "15"),
    ("n/2", "2"),
    ("n%3", "2"),
    ("n&4", "4"),
    ("n|2", "7"),
    ("n^1", "4"),
    ("~n+0", "-6"),
    ("n&~1", "4"),
    ("n==5", "1"),
    ("n!=5", "0"),
    ("n<>4", "1"),
    ("n<10?small:large", "small"),
    ("n>=10?small:large", "large"),
    ("n<=5?yes", "yes"),
    ("n>5?yes", "0"),
    ("n&1?odd:even", "odd"),
    ("n|~0", "-1"),
    ("n|~0?y:n", "y"),
    ("n&2?y:n", "n"),
    ])
def test_expansion_values(e, spec, value):
    assert e.get(spec) == value
    assert e.get("n") == "5"

def test_expansion_updates(e):
    assert e.get("n++") == "5" and e.get("n") == "6"
    assert e.get("n--") == "6" and e.get("n") == "5"
    assert e.get("++n") == "6"
    assert e.get("--n") == "5"
    assert e.get("n+=10") == "15"
    assert e.get("n-=5") == "10"
    assert e.get("n*=3") == "30"
    assert e.get("n/=4") == "7"
    assert e.get("n%=4") == "3"
    assert e.get("n|=8") == "11"
    assert e.get("n&=~1") == "10"
    assert e.get("n^=3") == "9"
    assert e.get("++s") is None
    assert e.get("s++") is None

def test_expansion_assignments(e):
    assert e.get("m=12") == "12"
    assert e.find("m").ptype == "int32"
    assert e.get("m=13") == "13"
    assert e.get("t=text value") == "text value"
    assert e.find("t").ptype == "char1024"
    assert e.get("t=other") == "other"
    assert e.get("u:=first") == "first"
    assert e.get("u:=second") == "first"

def test_integer_semantics(e):
    e.set("n","-7")
    assert e.get("n/2") == "-3"
    assert e.get("n%2") == "-1"
    e.set("n","2147483647")
    assert e.get("n+1") == "-2147483648"
    with pytest.raises(GlobalsError):
        e.get("n/0")

def test_expand(e):
    assert e.expand("${s} has ${n++} and ${n}") == "hello world has 5 and 6"
    assert e.expand("no expansions") == "no expansions"
    with pytest.raises(GlobalsError):
        e.expand("${missing}")

def test_get_invalid_name(g):
    with pytest.raises(GlobalsError):
        g.get(None)

def test_module_examples():
    result = doctest.testmod(arras.globals, optionflags=doctest.ELLIPSIS)
    assert result.failed == 0 and result.attempted > 0
