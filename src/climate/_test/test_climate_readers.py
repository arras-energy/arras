"""TMY and CSV weather files: `climate.tmy` and `climate.csv_reader`"""

import os

import pytest

from climate.tmy import TmyReader, CP_H, CP_S
from climate.csv_reader import CsvReader
from arras import exitcodes
from arras.runner import Runner

import climate_test_files as files

def errors(runner):
    """Error and warning lines without their prefixes"""
    return [x.split("]: ", 1)[1] for x in runner.stderr]

class FakeRunner: # pylint: disable=too-few-public-methods
    """Collects the lines of the module's messages outside a run"""
    def __init__(self):
        self.lines = []
    def error(self, *args):
        self.lines.append(("error", " ".join(args)))
    def warning(self, *args):
        self.lines.append(("warning", " ".join(args)))

@pytest.fixture(name="messages")
def fixture_messages(monkeypatch):
    """Message lines written by the readers"""
    fake = FakeRunner()
    monkeypatch.setattr(Runner, "current", classmethod(lambda cls: fake))
    return fake.lines

#
# TMY files
#
def test_tmy3_header_and_record(messages): # pylint: disable=unused-argument
    """The Yakima TMY3 header and first record"""
    reader = TmyReader()
    assert reader.open(files.TMY3) == 6
    assert (reader.data_city, reader.data_state, reader.tz_offset, reader.elevation) == ('"YAKIMA AIR TERMINAL"', "WA", -8, 324)
    # the second header line is longer than gridlabd's 500-character buffer, so it is read in parts
    assert reader.next()
    parts = 1
    while not reader.buf[1].isdigit():
        assert reader.next()
        parts += 1
    assert parts == 4
    record = reader.read_data()
    assert (record.month, record.day, record.hour) == (1, 1, 1)
    assert (record.tdb, record.rh, record.pressure, record.wind, record.winddir) == (-7.2, 0.92, 978.0, 2.6, 300.0)
    assert (record.tot_sky_cov, record.opq_sky_cov, record.snow_depth) == (1.0, 1.0, 0.0)
    assert messages == []
    reader.close()
    assert not reader.next()

def test_tmy2_records(tmp_path, messages):
    """A TMY2 file is read by its columns"""
    path = files.make_tmy2(str(tmp_path / "y.tmy2"))
    reader = TmyReader()
    assert reader.open(path) == 10
    assert reader.is_tmy2
    assert reader.header_info() == ("YAKIMA", "WA", 46, 34, -120, 33)
    assert reader.next()
    record = reader.read_data()
    assert (record.month, record.day, record.hour, record.tdb, record.rh, record.pressure) == (1, 1, 1, -7.2, 0.92, 978.0)
    assert record.snow_depth == pytest.approx(7*0.3937)
    assert messages[0][0] == "warning"

@pytest.mark.parametrize("name,content,message", [
    ("noext", "x", "tmy2_reader::open(file='{path}'): file name missing type extension"),
    ("empty.tmy3", "", "tmy2_reader::open(file='{path}') -- first fgets read nothing"),
    ("bad.tmyx", "x", "tmy2_reader::open(file='{path}'): unknown TMY file type (extension '.tmyx' is not recognized)"),
])
def test_tmy_open_errors(tmp_path, messages, name, content, message):
    """Files that cannot be read as TMY files"""
    path = tmp_path / name
    path.write_text(content)
    assert TmyReader().open(str(path).replace(".", "") if name == "noext" else str(path)) == 0
    assert messages[-1] == ("error", message.format(path=str(path).replace(".", "") if name == "noext" else path))

def test_tmy_missing_file(tmp_path, messages):
    """A missing file"""
    path = str(tmp_path / "missing.tmy3")
    assert TmyReader().open(path) == 0
    assert messages == [("error", f"tmy2_reader::open(file='{path}') -- fopen failed")]

def test_tmy_short_lines(messages):
    """Lines that do not give 17 values give an error line"""
    reader = TmyReader()
    reader.buf = "01/02/1990,03:00,1\n"
    record = reader.read_data()
    assert (record.month, record.day, record.hour) == (1, 2, 3)
    assert messages == [("error", "TMY reader did not get 17 values for line time 1/2 300")]
    reader.buf = "01/02/1990,x,1\n"
    reader.read_data()
    assert ("error", "TMY reader did not read a complete time from 'x'") in messages
    reader.buf = "  85\n"
    record = reader.read_data()
    assert record.month == -1 and record.tdb == 0.0

def test_calc_solar():
    """The flux on a surface is the direct normal times the cosine of
    incidence plus the diffuse"""
    reader = TmyReader()
    horizontal = reader.calc_solar(3, 172, 0.8, 12.0, 100.0, 10.0, 0.0)
    south = reader.calc_solar(CP_S, 172, 0.8, 12.0, 100.0, 10.0)
    assert horizontal == pytest.approx(10.0 + 100.0*0.924634, abs=1e-4)
    assert 10.0 < south < horizontal
    assert reader.calc_solar(CP_H+1, 172, 0.8, 12.0, 100.0, 10.0) == 10.0
    assert reader.peak_solar == horizontal

#
# CSV files
#
def reader_glm(file, options="", climate_options=""):
    """A csv_reader and a climate object for a file"""
    return f'''object csv_reader {{ name r; filename "{file}"; {options} }}
object climate {{ name c; tmyfile "{file}"; reader r; {climate_options} }}'''

@pytest.fixture(name="folder")
def fixture_folder(tmp_path, monkeypatch):
    """A scratch working folder"""
    monkeypatch.chdir(tmp_path)
    return tmp_path

def test_csv_properties(folder, helpers):
    """`$` lines set the reader's properties and its location"""
    files.make_year_csv(str(folder / "year.csv"))
    r = helpers.run(reader_glm("year.csv"), start="2001-03-01 00:00:00")
    assert r.returncode == 0
    m = r.model
    assert m.get_property("r", "city_name") == "Testville"
    assert helpers.number(m.get_property("r", "latitude")) == pytest.approx(37.5)
    assert helpers.number(m.get_property("r", "longitude")) == pytest.approx(-122.25)
    assert helpers.number(m.get_property("c", "latitude")) == pytest.approx(37.5)
    assert m.get_property("r", "index") == "472"
    assert CsvReader.timezone_offset(m, "r") == -8

@pytest.mark.parametrize("content,message", [
    ("$city_name\n", "csv_reader::read_prop ~ missing '=' seperator"),
    ("$city_name=\n", "csv_reader::read_prop ~ error reading property & value"),
    ("$nothing=1\n", "csv_reader::read_prop ~ unrecognized csv_reader property 'nothing'"),
    ("$lat_deg=north\n", "csv_reader::read_prop ~ unable to set property 'lat_deg' to 'north'"),
    ("$columns=x\n", "csv_reader::read_prop ~ unable to convert property 'columns' due to type restrictions"),
    ("temperature,wetness\n", "csv_reader::read_header ~ unable to find column property 'wetness''"),
    ("temperature\nnoon,50\n", "csv_reader::read_line ~ unable to read time string 'noon' with default format"),
    ("temperature\n1:01:00,warm\n", "csv_reader::read_line ~ unable to set value 'warm' to double property 'temperature'"),
])
def test_csv_errors(folder, helpers, content, message):
    """Malformed lines fail the initialization"""
    (folder / "bad.csv").write_text(content)
    r = helpers.run(reader_glm("bad.csv"))
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == message

def test_csv_timefmt_errors(folder, helpers):
    """A time that `timefmt` cannot read, and a format with a conversion
    other than integers, fail"""
    (folder / "w.csv").write_text("temperature\nx-02,50\n")
    r = helpers.run(reader_glm("w.csv", 'timefmt "%hd/%hd";'))
    assert errors(r)[0] == "csv_reader::read_line ~ unable to read time string 'x-02' with format '%hd/%hd'"
    r = helpers.run(reader_glm("w.csv", 'timefmt "%s";'))
    assert errors(r)[0] == "csv_reader::read_line ~ unable to read time string 'x-02' with format '%s'"

def test_csv_columns_property(folder, helpers):
    """With `columns` set, the header line of the file is read as a sample
    and fails"""
    (folder / "w.csv").write_text("temperature\n1:01:00,50\n")
    r = helpers.run(reader_glm("w.csv", 'columns "temperature";'))
    assert errors(r)[0] == "csv_reader::read_line ~ unable to read time string 'temperature' with default format"
    (folder / "x.csv").write_text("1:01:00,50\n1:01:02,60\n")
    r = helpers.run(reader_glm("x.csv", 'columns "temperature";'), start="2001-01-01 01:00:00")
    assert r.returncode == 0 and r.model.get_property("c", "temperature") == "50.0"
    r = helpers.run(reader_glm("x.csv", 'columns "temperature,wetness";'))
    assert errors(r)[:2] == ["csv_reader::read_header ~ unable to find column property 'wetness''",
        "csv_reader::open ~ column header read failure from explicit headers"]

def test_csv_missing_file(folder, helpers): # pylint: disable=unused-argument
    """A reader file that cannot be opened fails"""
    (folder / "w.csv").write_text("temperature\n")
    r = helpers.run('object csv_reader { name r; filename "other.csv"; }\nobject climate { name c; tmyfile "w.csv"; reader r; }')
    assert r.returncode == exitcodes.INIERR
    assert errors(r)[0] == "csv_reader could not open 'other.csv' for input!"

def test_csv_reader_property(folder, helpers):
    """A CSV file needs a csv_reader object in `reader`"""
    (folder / "w.csv").write_text("temperature\n1:01:00,50\n")
    r = helpers.run('object climate { name c; tmyfile "w.csv"; }')
    assert errors(r)[0] == "c: climate::init(): no csv_reader specified for tmyfile w.csv"
    r = helpers.run('object weather { name w; }\nobject climate { name c; tmyfile "w.csv"; reader w; }')
    assert errors(r)[0] == "c: climate::init(): reader 'w' is not a csv_reader object"

def test_csv_deferred(folder, helpers):
    """A climate object created before its reader is deferred until the
    reader is initialized"""
    (folder / "w.csv").write_text("temperature\n1:01:00,50\n1:01:02,60\n")
    m = helpers.model('object climate { name c; flags VERBOSE; tmyfile "w.csv"; reader r; }\nobject csv_reader { name r; filename "w.csv"; }',
        start="2001-01-01 01:00:00")
    m.globals.set("verbose", True)
    r = Runner(model=m)
    assert r.returncode == 0
    assert "c: climate::init(): deferring initialization on r" in errors(r)

def test_csv_discard_and_blank(folder, helpers):
    """Samples that do not advance in time are discarded with a warning;
    blank lines are skipped"""
    (folder / "w.csv").write_text("temperature\n1:01:02,50\n1:01:01,60\n\n1:01:03,70\n")
    r = helpers.run(reader_glm("w.csv"), start="2001-01-01 02:00:00")
    assert r.returncode == 0
    assert errors(r) == ["csv_reader::read_line ~ sample on line 3 does not advance in time and has been discarded"]

def test_csv_one_sample(folder, helpers):
    """A file of one sample keeps its values and moves its event a year"""
    (folder / "w.csv").write_text("temperature\n6:15:12,77\n")
    r = helpers.run(reader_glm("w.csv"), start="2001-06-01 00:00:00", stop="2003-06-17 00:00:00")
    assert r.returncode == 0
    assert r.model.get_property("c", "temperature") == "77.0"
    assert r.steps == 4
    # after the sample in the year of the start, the event is in the past, as in gridlabd
    r = helpers.run(reader_glm("w.csv"), start="2001-06-16 00:00:00")
    assert r.returncode == exitcodes.RUNERR

def test_csv_no_samples(folder, helpers):
    """A file without samples fails at the first presync"""
    (folder / "w.csv").write_text("temperature\n")
    r = helpers.run(reader_glm("w.csv"))
    assert r.returncode == exitcodes.RUNERR
    assert "csv_reader r has no samples" in errors(r)[-1]

def test_csv_latitude_sign(folder, helpers):
    """Minutes are subtracted unless the degrees are positive, as gridlabd
    does (also for 0 degrees)"""
    (folder / "w.csv").write_text("$lat_deg=0\n$lat_min=30\n$long_deg=10\n$long_min=30\ntemperature\n1:01:00,50\n")
    r = helpers.run(reader_glm("w.csv"), start="2001-01-01 00:00:00")
    assert helpers.number(r.model.get_property("c", "latitude")) == -0.5
    assert helpers.number(r.model.get_property("c", "longitude")) == 10.5

def test_csv_iso_times(folder, helpers):
    """Times that are timestamps are read in local time"""
    (folder / "w.csv").write_text("temperature,month\n2001-03-01,50,7\n2001-03-02,60,7\n")
    r = helpers.run(reader_glm("w.csv"), start="2001-03-02 00:00:00")
    assert r.model.get_property("c", "temperature") == "60.0"

def test_csv_location_check(folder, helpers):
    """A reader location out of range fails"""
    (folder / "w.csv").write_text("$lat_deg=91\ntemperature\n1:01:00,50\n")
    r = helpers.run(reader_glm("w.csv"))
    assert errors(r)[0] == "c: climate:c - Latitude is outside +/-90!"
    (folder / "w.csv").write_text("$long_deg=-181\ntemperature\n1:01:00,50\n")
    r = helpers.run(reader_glm("w.csv"))
    assert errors(r)[0] == "c: climate:c - Longitude is outside +/-180!"

def test_csv_bad_dates(folder, helpers):
    """A sample date that does not exist gives gridlabd's error line"""
    (folder / "w.csv").write_text("temperature\n1:01:00,50\n4:31:00,60\n")
    r = helpers.run(reader_glm("w.csv"), start="2001-01-01 00:00:00")
    assert "Invalid day provided in datetime" in errors(r)
    (folder / "w.csv").write_text("temperature\n13:01:00,50\n14:01:00,60\n")
    r = helpers.run(reader_glm("w.csv"), start="2001-01-01 00:00:00")
    assert "Invalid month provided in datetime" in errors(r)

def test_reader_outside_run(helpers):
    """The reader's handlers need a run"""
    m = helpers.model('object csv_reader { name r; }')
    assert not CsvReader.is_initialized(m, "r")
    assert os.path.basename(files.TMY3) == helpers.YAKIMA
