"""Tests of arras.units"""

import os
import math
import doctest

import pytest

import arras.units
from arras.units import Units, Unit, UnitsError, DEFAULT_UNITFILE

@pytest.fixture(name="units")
def fixture_units():
    """Units loaded from the copy of gridlabd's unitfile.txt"""
    return Units(DEFAULT_UNITFILE)

#
# Loading
#
def test_default_file(units):
    assert os.path.isfile(DEFAULT_UNITFILE)
    assert units.file == DEFAULT_UNITFILE
    assert len(units) == 94
    assert list(units.scalars) == ["Y","Z","E","P","T","G","M","k","h","da",
        "d","c","m","u","n","p","f","a","z","y"]
    assert units.scalars["da"] == 1 and units.scalars["y"] == -24
    assert units.constants["c"] == 2.997925e8
    assert units.constants["m"] == 9.10953447e-31

def test_locate(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GLPATH",raising=False)
    assert Units.locate() == DEFAULT_UNITFILE
    folder = tmp_path / "lib"
    folder.mkdir()
    (folder / "unitfile.txt").write_text("unit=0,0,0,0,0,0,1,0,16\n")
    monkeypatch.setenv("GLPATH",f"/nowhere;{folder}")
    assert Units.locate() == str(folder / "unitfile.txt")
    assert len(Units()) == 1
    (tmp_path / "unitfile.txt").write_text("")
    assert Units.locate() == os.path.join(".","unitfile.txt")

def test_missing_file(tmp_path):
    with pytest.raises(UnitsError,match="No such file"):
        Units(str(tmp_path / "missing.txt"))

@pytest.mark.parametrize("name,parameters", [
    ("unit", (0,0,0,0,0,0,1,0,16)),
    ("m", (-1,0,1,0,-1,0,4.121487e01,0,7)),
    ("g", (0,0,0,0,1,0,1.09775094e27,0,10)),
    ("1990$", (0,0,0,0,1,1,1.097751e30,0,7)),
    ("%", (0,0,0,0,0,0,0.01,0,16)),
    ("degC", (2,0,0,-1,1,0,1.686358,-273.14,7)),
    ("N", (3,0,-1,0,2,0,4.121487e01*1.09775094e30/1.235591e10**2,0,7)),
    ("sf", (-2,0,2,0,-2,0,(12*0.0254*4.121487e01)**2,0,7)),
    ])
def test_definitions(units,name,parameters):
    unit = units.find(name)
    assert unit.name == name
    assert unit.dimensions == parameters[:6]
    assert unit.a == pytest.approx(parameters[6],rel=1e-12)
    assert unit.b == parameters[7]
    assert unit.prec == parameters[8]

def test_gridlabd_quirks(units):
    # leading number read as scale and as first term
    assert units.find("pi").a == pytest.approx(3.1415926536**2)
    # '$' ends a derivation
    assert units.find("$").dimensions == (0,)*6 and units.find("$").a == 1996
    assert units.find("CA$").a == 0
    with pytest.raises(ZeroDivisionError):
        units.convert(1,"unit","CA$")
    # 'd' is tried before 'da'
    with pytest.raises(UnitsError):
        units.find("daN")
    # second '^' ignored
    assert units.find("m^2^2").dimensions == units.find("m^2").dimensions
    # offset applied to the imaginary part too
    assert units.convert(0+0j,"degC","K") == complex(273.14,273.14)

#
# Lookup
#
def test_prefixes(units):
    assert "kW" not in units
    assert units.find("kW").a == pytest.approx(1000*units.find("W").a)
    assert "kW" in units
    assert units["mm"].a == pytest.approx(units["m"].a/1000)
    assert units["MBtu"].a == pytest.approx(1e6*units["Btu"].a)

def test_compound(units):
    assert units.find("m/s").compatible(units.find("mph"))
    assert not units.find("m").compatible(units.find("kg"))
    assert units.find("pu.V") == Unit("pu.V",0,0,0,0,0,0,1,0,1)
    assert units.find("1/unit").a == 1
    assert "m/s" in list(units)

@pytest.mark.parametrize("name,match", [
    ("furlong", "unable to find or derive unit 'furlong'"),
    ("m^1", "exponent must be greater than 1"),
    ("m^x", "exponent must be greater than 1"),
    ("*m", "unable to read unit"),
    ("m**2", "unable to read unit"),
    ])
def test_find_errors(units,name,match):
    with pytest.raises(UnitsError,match=match):
        units.find(name)

#
# Conversion
#
@pytest.mark.parametrize("value,from_unit,result,to_unit,precision", Units.TESTS)
def test_unit_test_table(units,value,from_unit,result,to_unit,precision):
    precision = precision if precision else 1e-4
    assert abs(units.convert(value,from_unit,to_unit)-result) <= precision
    assert abs(units.convert(result,to_unit,from_unit)-value) <= precision

@pytest.mark.parametrize("value,from_unit,result,to_unit", [
    (32, "degF", 0, "degC"),
    (1, "kWh", 3412.969283, "Btu"),
    (1, "atm", 14.223343, "psi"),
    (1, "knot", 1.851925, "km/h"),
    (100, "%", 1, "pu"),
    (1, "m^3/s", 2118.88, "cfm"),
    (1, "MVA", 1000, "kVA"),
    (1, "kg*m^2/s^3", 1, "W"),
    ])
def test_convert(units,value,from_unit,result,to_unit):
    assert units.convert(value,from_unit,to_unit) == pytest.approx(result,abs=0.01)

def test_convert_complex(units):
    assert units.convert(12+1j,"kV","V") == pytest.approx(12000+1000j)
    assert isinstance(units.convert(1,"kV","V"),float)

def test_convert_units(units):
    assert units.convert(1,units["km"],units["m"]) == pytest.approx(1000)

def test_convert_same(units):
    assert units.convert(5,"nothing","nothing") == 5

@pytest.mark.parametrize("from_unit,to_unit,match", [
    ("m", "kg", "mismatched units"),
    ("furlong", "m", "could not find unit 'furlong'"),
    ("m", "furlong", "could not find unit 'furlong'"),
    ])
def test_convert_errors(units,from_unit,to_unit,match):
    with pytest.raises(UnitsError,match=match):
        units.convert(1,from_unit,to_unit)

def test_self_test(units):
    lines = []
    assert units.test(lines.append) == 0
    assert lines[0] == "BEGIN: units tests"
    assert lines[-1] == f"END: {len(Units.TESTS)} units tested"
    assert len(lines) == len(Units.TESTS) + 2
    assert units.test() == 0

def test_self_test_failure(tmp_path):
    path = tmp_path / "unitfile.txt"
    path.write_text(open(DEFAULT_UNITFILE,encoding="utf-8").read().replace("hp=746 W","hp=750 W"))
    lines = []
    assert Units(str(path)).test(lines.append) == 1
    assert [x for x in lines if x.startswith("FAILED")] == \
        ["FAILED: incorrect unit conversion 1 hp -> 746 W (got 750 W instead)"]

#
# Definitions and file syntax
#
def test_define(units):
    unit = units.derive("furlong","660 ft")
    assert units.convert(1,"furlong","m") == pytest.approx(201.168)
    assert units.primary("furlong",*unit.parameters) == unit
    with pytest.raises(UnitsError,match="already defined with a different parameter set"):
        units.primary("furlong",0,0,0,0,0,0,1,0,1)
    with pytest.raises(UnitsError,match="derived definition of 'furlong' failed"):
        units.derive("furlong","1 m")
    units.scalar("Ki",3)
    assert units.find("Kim").a == pytest.approx(1000*units["m"].a)

def test_constants(units):
    units.constant("e",1.0)
    assert units.constants["e"] == 1.0
    with pytest.raises(UnitsError,match="constant 'x' is not valid"):
        units.constant("x",1.0)
    with pytest.raises(UnitsError,match="unit already defined"):
        units.constant("m",1.0)

def test_file_syntax(tmp_path,caplog):
    path = tmp_path / "unitfile.txt"
    path.write_text("""; comment
#c=3e8 ; speed of light
#cx
*k=3
*bad
 indented=ignored
u=0,0,0,0,0,0,1,0,16
dozen=12 u ; trailing comment
b=u+5
""")
    units = Units(str(path))
    assert units.constants["c"] == 3e8
    assert list(units) == ["u","dozen","b"]
    assert units.convert(2,"dozen","u") == 24
    assert units.find("b").b == 5
    assert units.convert(0,"b","u") == -5
    assert "constant definition '#cx' is not valid" in caplog.text
    assert "scalar '*bad' is not valid" in caplog.text
    path.write_text("#q=1\n")
    with pytest.raises(UnitsError,match=r"unitfile.txt\(1\): constant 'q' is not valid"):
        Units(str(path))
    path.write_text("u=0,0,0,0,0,0,1,0,16\nbad=@\n")
    with pytest.raises(UnitsError,match=r"\(2\): unit 'bad=@' is not recognized"):
        Units(str(path))
    path.write_text("x=1 nothing\n")
    with pytest.raises(UnitsError,match=r"\(1\): unable to find or derive unit 'nothing'"):
        Units(str(path))
    path.write_text("u=0,0,0,0,0,0,1,0,16\nx=u+u^2\n")
    with pytest.raises(UnitsError,match=r"\^ not allowed after '\+'"):
        Units(str(path))

def test_repr(units):
    assert repr(units).startswith("<Units file=") and repr(units).endswith("units=94>")
    assert repr(units["unit"]) == "<Unit unit=0,0,0,0,0,0,1,0,16>"
    assert math.isclose(units["m"].a,41.21487)

#
# Documentation
#
def test_docstring_examples():
    result = doctest.testmod(arras.units, optionflags=doctest.ELLIPSIS)
    assert result.failed == 0 and result.attempted > 0
