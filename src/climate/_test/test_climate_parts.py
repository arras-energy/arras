"""Solar angles (against gridlabd's compiled code), the cloud pattern, and
the private helpers"""

import os
import math
import random
import datetime

import pytest

from climate.solar_angles import SolarAngles as SA, SolposData
from climate.cloud import CloudPattern, EMPTY_VALUE, solar_locations
from climate import cloud, _common
from climate._common import sscanf, atoi, atof, Tokenizer, int16, float32, c_round, lerp, qerp, fmt, to_double
from arras.oclass import Class

REFERENCE = os.path.join(os.path.dirname(__file__), "data", "reference", "solar_angles.txt")

def _reference():
    with open(REFERENCE, encoding="utf-8") as fh:
        return [line.split() for line in fh]

@pytest.mark.parametrize("row", [x for x in _reference() if x[0] != "solpos"])
def test_duffie_beckman(row):
    """`SolarAngles` functions give what gridlabd's solar_angles.cpp gives
    (`data/reference/solar_angles_main.cpp`)"""
    day, lat = int(row[0]), float(row[1])
    sol_time = SA.solar_time(10.5, day, -2.0943951, -2.1)
    values = [SA.eq_time(day), SA.declination(day), sol_time, SA.cos_incident(lat, 0.5, 0.3, sol_time, day),
        SA.zenith(day, lat, sol_time), SA.altitude(day, lat, sol_time), SA.elevation(day, lat, sol_time),
        SA.azimuth(day, lat, sol_time), SA.hr_sunrise(day, lat), SA.day_len(day, lat)]
    assert values == pytest.approx([float(x) for x in row[2:]], rel=1e-13, abs=1e-13)

@pytest.mark.parametrize("row", [x for x in _reference() if x[0] == "solpos"])
def test_solpos(row):
    """SOLPOS and the Perez model give what gridlabd's code gives"""
    hour = int(row[1])
    pdat = SolposData()
    SA.S_init(pdat)
    pdat.longitude, pdat.latitude, pdat.timezone = -120.55, 46.5667*math.pi/180, -8
    pdat.year, pdat.daynum, pdat.hour, pdat.minute, pdat.second = 2006, 121 + hour, hour, 30, 0
    pdat.temp, pdat.press, pdat.solcon, pdat.aspect, pdat.tilt = 12.0, 980, 125.0, 3.3, 0.5
    pdat.diff_horz = 0 if hour == 19 else 8.0
    pdat.dir_norm = {12: 60.0, 6: 0.0}.get(hour, 30.0)
    assert SA.S_solpos(pdat) == 0
    values = [pdat.month, pdat.day, pdat.azim, pdat.zenref, pdat.cosinc, pdat.etrn, pdat.etr, pdat.amass,
        pdat.sretr, pdat.ssetr, pdat.perez_horz, pdat.sbcf, pdat.eqntim]
    assert values == pytest.approx([float(x) for x in row[2:15]], rel=1e-12, abs=1e-12)
    if hour != 19: # gridlabd's static SOLPOS data keeps the previous call's Perez values at night
        assert [pdat.perez_F1, pdat.perez_skyclear_idx] == pytest.approx([float(row[15]), int(row[16])])

def test_solpos_branches():
    """Polar night and day, the sun below the horizon, and refraction ranges"""
    for latitude, daynum, hour in ((89.0, 172, 12), (-89.0, 172, 12), (46.0, 10, 2), (0.0, 80, 18)):
        pdat = SolposData()
        SA.S_init(pdat)
        pdat.longitude, pdat.latitude, pdat.timezone = 0.0, math.radians(latitude), 0
        pdat.year, pdat.daynum, pdat.hour, pdat.minute, pdat.second = 2004, daynum, hour, 0, 0
        pdat.diff_horz, pdat.dir_norm = 5.0, 5.0
        SA.S_solpos(pdat)
        assert -9.0 <= pdat.elevref <= 90.0
    assert SA.local_time(SA.solar_time(10.0, 100, 1.0, 1.1), 100, 1.0, 1.1) == pytest.approx(10.0)
    assert SA.incident(0.8, 0.0, 0.0, 12.0, 172) == pytest.approx(math.acos(SA.cos_incident(0.8, 0.0, 0.0, 12.0, 172)))

#
# Cloud pattern
#
@pytest.fixture(name="small")
def fixture_small(monkeypatch):
    """Tiles of 16 pixels"""
    monkeypatch.setattr(cloud, "TILE_SIZE", 16)

def test_pattern_size(small): # pylint: disable=unused-argument
    """The pattern covers the locations with a one-tile border"""
    pattern = CloudPattern([(46.6, -120.5)], random.Random(1))
    assert (pattern.size, pattern.on_screen, pattern.min_index, pattern.max_index) == (49, 16, 16, 32)
    assert pattern.min_lat < 46.6 < pattern.max_lat and pattern.min_lon < -120.5 < pattern.max_lon
    assert all(x != EMPTY_VALUE for row in pattern.cloud for x in row)
    wide = CloudPattern([(46.6, -120.5), (46.62, -120.4)], random.Random(1))
    assert wide.size == (math.ceil(0.1*math.cos(math.radians(46.6))*111.32*1000/20/16) + 2) * 16 + 1
    empty = CloudPattern([], random.Random(1))
    assert empty.min_lat < 0 < empty.max_lat

def test_binary_and_fuzzy(small): # pylint: disable=unused-argument
    """The binary pattern has the sky cover asked for; the fuzzy pattern is
    normalized, with clouds only where the binary pattern has them"""
    pattern = CloudPattern([(46.6, -120.5)], random.Random(2))
    cut = pattern.convert_to_binary_cloud(0.2)
    tile = pattern.tile
    screen = [pattern.binary[i][j] for i in range(tile, 2*tile) for j in range(tile, 2*tile)]
    assert screen.count(0)/len(screen) == pytest.approx(0.4, abs=0.006)
    pattern.convert_to_fuzzy_cloud(EMPTY_VALUE, 40, 400)
    assert all(x == 0 for row in pattern.fuzzy for x in row)
    pattern.convert_to_fuzzy_cloud(cut, 40, 10)
    values = [x for row in pattern.fuzzy for x in row]
    assert min(values) == 0.0 and max(values) == 1.0
    for i in range(pattern.size):
        for j in range(pattern.size):
            if pattern.binary[i][j] != 0:
                assert pattern.fuzzy[i][j] == 0.0
    assert pattern.binary_value(46.6, -120.5) in (0, 1)
    assert 0.0 <= pattern.fuzzy_value(46.6, -120.5) <= 1.0

def test_binary_limits(small): # pylint: disable=unused-argument
    """A full sky is 0.99 cover; the search stops after 100 steps"""
    pattern = CloudPattern([(46.6, -120.5)], random.Random(3))
    pattern.convert_to_binary_cloud(0.9)
    tile = pattern.tile
    screen = [pattern.binary[i][j] for i in range(tile, 2*tile) for j in range(tile, 2*tile)]
    assert screen.count(0)/len(screen) >= 0.98
    flat = CloudPattern([(46.6, -120.5)], random.Random(3))
    flat.cloud = [[1.0]*flat.size for _ in range(flat.size)]
    flat.convert_to_binary_cloud(0.2)
    assert all(x == 0.0 for row in flat.normalized for x in row)

@pytest.mark.parametrize("direction", [0, 45, 90, 135, 180, 225, 270, 315])
def test_update_directions(small, direction): # pylint: disable=unused-argument
    """The pattern moves with the wind from every direction and stays
    defined on screen"""
    pattern = CloudPattern([(46.6, -120.5)], random.Random(4))
    cut = pattern.convert_to_binary_cloud(0.3)
    pattern.convert_to_fuzzy_cloud(cut, 10, 20)
    for _ in range(4):
        pattern.update(60, 3.0, direction, 0.5, 0.3, 10, 20)
        tile = pattern.tile
        assert all(pattern.cloud[i][j] != EMPTY_VALUE for i in range(tile, 2*tile) for j in range(tile, 2*tile))
    pattern.update(60, 0.1, direction, 0.5, 0.3, 10, 20)
    pattern.update(60, 3.0, direction, 2.0, 0.3, 10, 20)

def test_pixel_errors(small): # pylint: disable=unused-argument
    """Locations outside the pattern raise"""
    pattern = CloudPattern([(46.6, -120.5)], random.Random(5))
    with pytest.raises(_common.ClimateError):
        pattern.fuzzy_value(0.0, 0.0)
    with pytest.raises(_common.ClimateError):
        pattern.binary_value(math.nan, 0.0)

def test_solar_locations(helpers):
    """Only `solar` objects with a latitude and a longitude are located"""
    m = helpers.model('''class solar { double x; }
object solar { name a; latitude 46.6; longitude -120.5; }
object solar { name b; latitude 46.6; }
object weather { name w; latitude 1; longitude 2; }''')
    assert solar_locations(m) == [(46.6, -120.5)]

#
# Helpers
#
def test_sscanf():
    """`sscanf()` reads as C does"""
    assert sscanf(" 85010101 -72x", "%*2s%2d%2d%2d %d") == (4, [1, 1, 1, -72])
    assert sscanf("a,b,,c", "%[^','],%[^','],%[^',']") == (2, ["a", "b"])
    assert sscanf("", "%d") == (-1, [])
    assert sscanf("  ", "%d") == (-1, [])
    assert sscanf("x", "%d") == (0, [])
    assert sscanf("1:02", "%hd:%hd:%hd") == (2, [1, 2])
    assert sscanf(" 3.5e2kW", "%lg%3s") == (2, [350.0, "kW"])
    assert sscanf("xy", "%c%c") == (2, ["x", "y"])
    assert sscanf("x", "%2c") == (-1, [])
    assert sscanf("50%", "%d%%") == (1, [50])
    assert sscanf("50x", "%d%%") == (1, [50])
    assert sscanf("ff 17", "%x %o") == (2, [255, 15])
    assert sscanf("1", "%d,%d") == (1, [1])
    assert sscanf("1;", "%d,") == (1, [1])
    assert sscanf("1", "%y") == (0, [])
    assert sscanf("abc", "%2[a-c]%s") == (2, ["ab", "c"])

def test_c_functions():
    """C library work-alikes"""
    assert (atoi(" 12x"), atoi("x"), atof(" 1.5e1x"), atof("x")) == (12, 0, 15.0, 0.0)
    tokens = Tokenizer("1:01, 50,,60\n")
    assert [tokens.next(" ,\t\n"), tokens.next(",\n"), tokens.next(",\n"), tokens.next(",\n")] == ["1:01", " 50", "60", None]
    assert (int16(40000), float32(46.567), c_round(-2.5), c_round(2.5)) == (40000-65536, pytest.approx(46.567, abs=1e-5), -3, 3)
    assert lerp(0.5, 0, 1, 1, 3) == 2
    assert qerp(0.5, 0, 0, 1, 1, 2, 4) == pytest.approx(0.25)
    assert (fmt(1/3), fmt(math.nan), fmt(-0.0)) == ("0.333333333333333", "nan", "0.0")

def test_qerp_spacing(monkeypatch):
    """Quadratic interpolation needs equally spaced points"""
    lines = []
    monkeypatch.setattr(_common, "gl_error", lines.append)
    assert qerp(0.5, 0, 0, 1, 1, 3, 4) == 0.0
    assert lines == ["interpolate_quadratic: this only works given three equally spaced points"]

def test_to_double():
    """Numbers with units"""
    Class.get_units()
    assert to_double("75%", "pu") == pytest.approx(0.75)
    assert to_double(None) == 0.0
    with pytest.raises(_common.ClimateError):
        to_double("warm")
    with pytest.raises(_common.ClimateError):
        to_double("1 m", None)
    with pytest.raises(_common.ClimateError):
        to_double("1 m", "s")

def test_time_helpers(helpers, monkeypatch):
    """Local time and `mkdatetime()` as gridlabd computes them"""
    m = helpers.model("")
    summer = _common.local_datetime(m, 1151712000)
    assert (summer.month, summer.day, summer.hour, summer.is_dst, summer.yearday, summer.weekday) == (6, 30, 17, True, 180, 5)
    assert _common.local_datetime(m, 0) is None and _common.local_datetime(m, -5) is None
    assert _common.mkdatetime(m, (2006, 7, 1, 0, 0, 0), False) == 1151740800
    assert _common.mkdatetime(m, (2006, 7, 1, 0, 0, 0), True) == 1151737200
    lines = []
    monkeypatch.setattr(_common, "gl_error", lines.append)
    assert _common.mkdatetime(m, (2006, 7, 1, 25, 0, 0), False) == 1151712000
    assert _common.mkdatetime(m, (2004, 2, 29, 0, 0, 0), False) > 0
    assert lines == ["Invalid time of day provided in datetime"]
    utc = helpers.model("", timezone="UTC")
    assert _common.mkdatetime(utc, (2006, 7, 1, 0, 0, 0), False) == 1151712000
    stamp = datetime.datetime(2006, 10, 29, 1, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-8)))
    assert _common.to_timestamp(m, "2006-10-29 01:30:00 PST") == int(stamp.timestamp())
    assert _common.to_timestamp(m, "2006-10-29 01:30:00 PDT") == int(stamp.timestamp()) - 3600
    with pytest.raises(_common.ClimateError):
        _common.to_timestamp(m, "yesterday")

def test_flags(helpers):
    """Message flags come from the object and the module global"""
    m = helpers.model('object climate { name c; flags "QUIET|0x2"; }')
    assert _common.object_flags(m, "c") & _common.OF_QUIET
    m.globals.set("climate::message_flags", "VERBOSE")
    assert _common.object_flags(m, "c") & _common.OF_VERBOSE
    assert _common.parse_flags(5, {}) == 5 and _common.parse_flags("0x10", {}) == 16
    assert _common.header_name(m, "c") == "c"
    m.read_glm("object climate { }\n")
    assert _common.header_name(m, "climate:1") == "(null)"
    m.set_property("c", "latitude", "37N30:00")
    assert _common.get_double(m, "c", "latitude") == pytest.approx(37.5)
    assert math.isnan(_common.get_double(m, "climate:1", "longitude"))
