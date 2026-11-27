"""Classes `voltdump`, `currdump`, and `billdump`: registration, timing,
formats, groups, and initialization"""
# pylint: disable=missing-function-docstring,line-too-long

import cmath

import pytest

import powerflow
from arras.oclass import Class
from arras.model import Model

VNOM = 2401.7771
FEEDER = f"""
object node {{ name n0; groupid feeder; phases ABCN; nominal_voltage {VNOM}; bustype SWING; }}
object test_line {{ name l01; groupid feeder; phases ABCN; from n0; to n1; length 2000; }}
object meter {{ name n1; phases ABCN; nominal_voltage {VNOM}; }}
object load {{ name ld; parent n1; phases ABCN; nominal_voltage {VNOM}; constant_power_A 100000+50000j; constant_power_B 100000; constant_power_C 100000; }}
"""

@pytest.fixture(name="here", autouse=True)
def fixture_here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path

def lines(path:str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()

def test_registration():
    Model().read_glm("module powerflow;\n")
    volt, curr, bill = (Class.find(x, module="powerflow") for x in ("voltdump", "currdump", "billdump"))
    assert volt.trl == 9 and curr.trl == 0 and bill.trl == 8 and volt.parent is None
    assert volt.find_property("mode").default == "rect" and curr.find_property("mode").default == "RECT"
    assert volt.find_property("maxcount").default == "-1" and curr.find_property("maxcount").default == "1"
    assert curr.find_property("filemode").default == "w" and volt.find_property("runtime").default == "NEVER"
    assert bill.find_property("meter_type").default == "TRIPLEX_METER"

def test_voltdump(helpers):
    """One dump (version 2, rectangular) at the first time"""
    r = helpers.run(FEEDER + 'object voltdump { name vd; filename "volts.csv"; }\n', stop="2020-01-01 01:00:00")
    assert r.returncode == 0, r.stderr
    m = r.model
    rows = lines("volts.csv")
    assert rows[0] == "node_name,datetime,voltA_real,voltA_imag,voltB_real,voltB_imag,voltC_real,voltC_imag"
    assert [x.split(",")[0] for x in rows[1:]] == ["n0", "n1", "ld"]
    v = powerflow.get_complex(m, "n1", "voltage_B")
    fields = rows[2].split(",")
    assert fields[1] == "2020-01-01 00:00:00 UTC"
    assert float(fields[4]) == pytest.approx(v.real, abs=1e-6) and float(fields[5]) == pytest.approx(v.imag, abs=1e-6)
    assert m.get_property("vd", "runcount") == "1" and m.get_property("vd", "version") == "2"

def test_voltdump_polar_group_v1(helpers):
    m = helpers.run(FEEDER + 'object voltdump { name vd; filename "volts.csv"; mode polar; group feeder; version 1; }\n').model
    rows = lines("volts.csv")
    assert rows[0] == "# volts.csv run at 2020-01-01 00:00:00 UTC on 1 nodes"
    assert rows[1] == "node_name,voltA_mag,voltA_angle,voltB_mag,voltB_angle,voltC_mag,voltC_angle"
    v = powerflow.get_complex(m, "n0", "voltage_B")
    assert rows[2].split(",")[0] == "n0" and float(rows[2].split(",")[3]) == pytest.approx(abs(v), abs=1e-6)
    assert float(rows[2].split(",")[4]) == pytest.approx(cmath.phase(v), abs=1e-6)
    assert len(rows) == 3

def test_voltdump_runtime(helpers):
    """A dump at runtime (its sync asks for the event)"""
    r = helpers.run(FEEDER + 'object voltdump { name vd; filename "volts.csv"; runtime "2020-01-01 00:30:00"; }\n', stop="2020-01-01 01:00:00")
    assert r.returncode == 0, r.stderr
    assert lines("volts.csv")[1].split(",")[1] == "2020-01-01 00:30:00 UTC"

def test_voltdump_interval(helpers):
    """Dumps appended at each multiple of the interval, up to maxcount"""
    helpers.run(FEEDER + 'object voltdump { name vd; filename "volts.csv"; interval 600; maxcount 3; }\n', stop="2020-01-01 01:00:00")
    times = [x.split(",")[1] for x in lines("volts.csv") if x.startswith("n0,")]
    assert times == ["2020-01-01 00:00:00 UTC", "2020-01-01 00:10:00 UTC", "2020-01-01 00:20:00 UTC"]

def test_currdump(helpers):
    m = helpers.run(FEEDER + 'object currdump { name cd; filename "currs.csv"; }\n').model
    rows = lines("currs.csv")
    assert rows[0] == "link_name,datetime,currA_real,currA_imag,currB_real,currB_imag,currC_real,currC_imag"
    i = powerflow.get_complex(m, "l01", "current_in_A")
    fields = rows[1].split(",")
    assert fields[0] == "l01" and float(fields[2]) == pytest.approx(i.real, abs=1e-6) and float(fields[3]) == pytest.approx(i.imag, abs=1e-6)

def test_currdump_interval_overwrites(helpers):
    """With the default filemode `w`, each interval dump rewrites the file"""
    helpers.run(FEEDER + 'object currdump { name cd; filename "currs.csv"; interval 600; maxcount 0; mode POLAR; }\n', stop="2020-01-01 00:30:00")
    rows = lines("currs.csv")
    assert len(rows) == 2 and rows[1].split(",")[1] == "2020-01-01 00:30:00 UTC"
    assert rows[0].startswith("link_name,datetime,currA_mag,currA_angle")

def test_billdump(helpers):
    m = helpers.run(FEEDER + 'object billdump { name bd; filename "bills.csv"; meter_type METER; }\n').model
    rows = lines("bills.csv")
    assert rows[0] == "# bills.csv run at 2020-01-01 00:00:00 UTC on 1 meters"
    assert rows[1] == "meter_name,previous_monthly_bill,previous_monthly_energy"
    assert rows[2] == f"n1,{powerflow.get_double(m, 'n1', 'previous_monthly_bill'):f},{powerflow.get_double(m, 'n1', 'previous_monthly_energy'):f}"
    assert m.get_property("bd", "runcount") == "1"

def test_billdump_none(helpers):
    r = helpers.run(FEEDER + 'object billdump { name bd; filename "bills.csv"; }\n')
    assert any("no nodes were found to dump" in x for x in helpers.warnings(r))

def test_init(helpers, here):
    (here / "volts.csv").write_text("old\n")
    r = helpers.run(FEEDER + 'object voltdump { name vd; filename "volts.csv"; runtime "2030-01-01 00:00:00"; }\n')
    assert not (here / "volts.csv").exists() and r.returncode == 0
    r = helpers.run(FEEDER + 'object voltdump { name vd; filename "volts.csv"; interval -1; }\n')
    assert any("negative interval is not permitted" in x for x in helpers.errors(r))
    r = helpers.run(FEEDER + 'object currdump { name cd; filename "currs.csv"; version 3; }\n')
    assert any("format version 3 is invalid" in x for x in helpers.errors(r))
