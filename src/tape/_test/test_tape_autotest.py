"""The gridlabd `tape` module autotests, ported to `arras`

Each GLM file in `data/` is a gridlabd autotest from `module/tape/autotest/`
with the changes listed in `data/README.md`. Files whose name ends in
`_err` must fail with `RUNERR`; the others must succeed without errors.
Each runs in its own empty folder, because several write the same files.
"""

import os
import glob

import pytest

from arras import exitcodes
from arras.runner import Runner

DATA = os.path.join(os.path.dirname(__file__), "data")
TESTS = sorted(os.path.basename(x) for x in glob.glob(os.path.join(DATA, "test_*.glm")))

NOT_PORTED = ["test_delta_player_first_delta_timestep_err.glm", "test_deltamode_player_endtime_err.glm"]
"""gridlabd autotests that need deltamode and powerflow"""

ERRORS = {
    "test_recorder_flush_1_err.glm": "ERROR [2000-01-01 00:00:00 EST]: model commit failed",
    "test_recorder_interval_err.glm": "ERROR [2000-01-01 00:00:00 UTC]: invalid interval value (-2)",
}

def autotest(helpers, file:str) -> Runner:
    """Run an autotest in the working folder, with the data copied there"""
    helpers.copy_data(os.getcwd())
    return Runner(file)

def data_rows(helpers, file:str) -> list[str]:
    """The rows of a recorder file (comment lines left out)"""
    return [x for x in helpers.lines(file) if not x.startswith("#")]

def test_files():
    """Every gridlabd autotest of the tape module is ported, except the two
    deltamode tests"""
    assert len(TESTS) + len(NOT_PORTED) == 26
    assert set(ERRORS) == {x for x in TESTS if x.endswith("_err.glm")}

@pytest.mark.parametrize("file", TESTS)
def test_autotest(helpers, file):
    """Each autotest succeeds, or fails with the expected first error"""
    runner = autotest(helpers, file)
    if file.endswith("_err.glm"):
        assert runner.returncode == exitcodes.RUNERR, runner.stderr
        assert runner.stderr[0].startswith(ERRORS[file])
    else:
        assert runner.returncode == exitcodes.SUCCESS, runner.stderr
        assert runner.stderr == []

def test_player_header(helpers):
    """A player that reads its properties from a CSV header plays a year of
    hourly weather that a recorder writes exactly as gridlabd did"""
    autotest(helpers, "test_player_header.glm")
    assert helpers.lines("test_player_header_output.csv") == helpers.lines(os.path.join(DATA, "test_player_header_output.csv"))

def test_multiplayer(helpers):
    """Multiplayers with and without property lists, with units in the
    property list and in the CSV header, give gridlabd's recordings"""
    autotest(helpers, "test_multiplayer.glm")
    for n in (1, 2):
        name = f"test_multiplayer_record_{n}.csv"
        assert helpers.lines(name) == helpers.lines(os.path.join(DATA, name))

def test_player_exercise(helpers):
    """A looping player with relative times plays its 24-hour cycle 28
    times"""
    runner = autotest(helpers, "test_player_exercise_2_1_2.glm")
    house = runner.model.objects["house:0"]
    assert (house["heating_setpoint"], house["cooling_setpoint"]) == ("72", "82")
    assert runner.steps == 28*3 + 1

def test_player_buffer(helpers):
    """A player writes complex values longer than 32 characters (checked by
    the autotest's complex_asserts)"""
    runner = autotest(helpers, "test_player_buffer.glm")
    assert runner.model.get_property("load4", "constant_power_C") == "22.12820806729023+79.78912749199718j"

@pytest.mark.parametrize("file, rows", [
    ("test_histogram_basic.glm", ["2000-01-01 00:00:10 EST,6,8,10,7,14,20,"]),
    ("test_histogram_count_int.glm", ["2000-01-01 00:00:00 EST,0,0,0,0,0,0,"] + [f"2000-01-01 00:0{t//60}:{t%60:02d} EST,6,8,10,7,14,20," for t in range(10, 100, 10)]),
    ("test_histogram_enum.glm", [f"2000-01-01 00:0{t//60}:{t%60:02d} EST,20,0,0," for t in range(10, 110, 10)]),
    ("test_histogram_set.glm", [f"2000-01-01 00:0{t//60}:{t%60:02d} EST,20,0,0," for t in range(10, 110, 10)]),
])
def test_histograms(helpers, file, rows):
    """Histogram counts of value bins (2400 V to 4800 V in steps of 200 V,
    and 2400 V to 3600 V), enumerations, and sets"""
    autotest(helpers, file)
    assert data_rows(helpers, "hist_test.csv") == rows
    assert helpers.lines("hist_test.csv")[-1] == "# end of tape"

def test_recorder_epoch(helpers):
    """`format 1` timestamps are seconds; output formats give the forms the
    recorder documentation lists"""
    autotest(helpers, "test_recorder_epoch.glm")
    rows = data_rows(helpers, "test_recorder_epoch.csv")
    assert rows[0] == "timestamp,Rroof,Rwall,Rfloor,Rdoors"
    assert rows[1].split(",")[0] == "1281844800" and rows[2].split(",")[0] == "1281844860"
    assert rows[1] == "1281844800,+17.77,+8.67,+10.59,+3"
    assert data_rows(helpers, "test_multirecorder_epoch.csv")[1] == "1281844800,+17.77,+16.68,+18.58,+21.61,+33.69"
    assert data_rows(helpers, "test_group_recorder_epoch.csv")[1].startswith("1281844800,")
    load = data_rows(helpers, "totalload_5_houses_Aug.csv")
    assert load[1] == ("2010-08-15 00:00:00 EDT,+0 uW,0x0.0000p+0 uW,0.0000e+00 uW,0.0000 uW,0 uW,0X0.0000P+0 uW,0.0000E+00 uW,0.0000 uW,0 uW,"
        "0.0000+0.0000i uVA,0.0000+0.0000j uVA,0.0000+0.0000d uVA,0.0000+0.0000r uVA,0.0000 uVA,0.0000 uVA,0.0000 uVA,0.0000 uVA,0.0000 uVA")

def test_recorder_strftime(helpers):
    """`strftime_format` timestamps"""
    autotest(helpers, "test_recorder_strftime_format.glm")
    assert data_rows(helpers, "totalload_5_houses_Aug.csv")[0].startswith("08/15/10 00:00:00,")

def test_tape_whitespace(helpers):
    """Property lists with spaces after the commas"""
    autotest(helpers, "test_tape_whitespace.glm")
    assert data_rows(helpers, "test_recorder_whitespace1.csv")[0] == "2010-08-15 00:00:00 EDT,+17.77,+8.67,+10.59,+3"

def test_recorder_flush(helpers):
    """`flush 0` writes every row at once (checked by the autotest's commit
    handler); a row is written every minute"""
    autotest(helpers, "test_recorder_flush_0.glm")
    rows = data_rows(helpers, "test_recorder_flush_0.csv")
    assert rows[0] == "timestamp,x" and len(rows) == 62

def test_recorder_global(helpers):
    """A recorder of the `clock` global"""
    autotest(helpers, "test_recorder_global.glm")
    assert data_rows(helpers, "clock.csv") == ["2001-01-01 00:00:00 PST,2001-01-01 00:00:00 PST"]

def test_multirecorder_global(helpers):
    """A multi-recorder of a global, the parent's property in another unit,
    and another object's property in another unit"""
    autotest(helpers, "test_multirecorder_global.glm")
    assert data_rows(helpers, "multirecorder.csv") == ["2001-01-01 00:00:00 PST,2001-01-01 00:00:00 PST,-17.7789 degC,-17.7789 degC"]

def test_recorder_exercise(helpers):
    """A recorder of a waterheater with a row limit; its default file is in
    the folder (gridlabd's exercise writes `exercise_2_2_2.csv`)"""
    autotest(helpers, "test_recorder_exercise_2_2_2.glm")
    assert data_rows(helpers, "exercise_2_2_2.csv") == ["2001-01-01 00:00:00 PST,+0"]

def test_collectors(helpers):
    """Collector aggregates over groups by class and by group id"""
    autotest(helpers, "test_collector_exercise_2_4_2.glm")
    rows = data_rows(helpers, "exercise_2_4_2.csv")
    assert len(rows) == 7*24 - 1
    assert rows[0] == "2005-01-01 01:00:00 PST,+0,+0,+0,+0"
    autotest(helpers, "test_collector_multiple_properties.glm")
    rows = data_rows(helpers, "test_collector_multiple_properties.csv")
    assert len(rows) == 7*24 - 1 and len(rows[0].split(",")) == 9

def test_recorders_multiple_properties(helpers):
    """Recorders and multi-recorders with several `property` lines record
    every property"""
    autotest(helpers, "test_recorder_multiple_properties.glm")
    rows = data_rows(helpers, "test_recorder_multiple_properties.csv")
    assert len(rows) == 7*24 and len(rows[0].split(",")) == 3
    autotest(helpers, "test_multi_recorder_multiple_properties_long.glm")
    rows = data_rows(helpers, "test_multi_recorder_multiple_properties.csv")
    assert len(rows) == 7*24 and len(rows[0].split(",")) == 1 + 12*14
