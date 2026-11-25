# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""CSV weather files (class `csv_reader`)

A `csv_reader` object reads a weather file of comma-separated samples for
a `climate` object that names it in its `reader` property. The climate
object opens the file when it initializes and asks the reader for the
sample in effect at each time.

Syntax
------

    module climate;
    object csv_reader {
        name "<reader-name>";
        filename "<file-name>";
        [timefmt "<scanf-format>";]
        [columns "<column>,<column>,...";]
        [city_name "<string>"; state_name "<string>";]
        [lat_deg <decimal>; lat_min <decimal>; long_deg <decimal>; long_min <decimal>;]
        [timezone_offset <decimal>;]
    }
    object climate {
        tmyfile "<file-name>.csv";
        reader "<reader-name>";
    }

File format:

    # comment
    $<property>=<value>
    <column>,<column>,...
    <time>,<value>,<value>,...

Properties
----------

| Property | Type | Access | Description |
| -------- | ---- | ------ | ----------- |
| `index` | `int32` | `REFERENCE` | reader line index |
| `city_name` | `char32` | | name of city |
| `state_name` | `char32` | | name of state/province |
| `lat_deg`, `lat_min` | `double` | | latitude degrees and minutes |
| `long_deg`, `long_min` | `double` | | longitude degrees and minutes |
| `low_temp` | `double` | `REFERENCE` | lowest temperature |
| `high_temp` | `double` | `REFERENCE` | highest temperature |
| `peak_solar` | `double` | `REFERENCE` | peak solar flux |
| `elevation` | `int32` | | elevation |
| `status` | `enumeration {ERROR=2, OPEN=1, INIT=0}` | `REFERENCE` | reader status |
| `timefmt` | `char32` | | time format |
| `timezone` | `char32` | | timezone |
| `timezone_offset` | `double` | | timezone offset |
| `columns` | `char256` | | column names |
| `filename` | `char256` | | filename |

Description
-----------

The `climate` object calls `CsvReader.open()` when it initializes and
`CsvReader.get_data()` in its presync pass. They are expected to satisfy:

1. `open()` reads the file named by `filename` (from the working folder),
   in lines of up to 1023 characters. Lines that start with `#` are
   comments. A line `$NAME=VALUE` (the value ends at a newline or `#`)
   sets a `double` or `char32` property of the reader (the first 31
   characters); other properties, unknown properties, and malformed lines
   fail. The first other line is the column header, unless `columns` is
   set, in which case `columns` is the header and every other line is a
   sample.
2. Column names are separated by commas and end at the end of the line or
   at `#`; each must be a property of class `weather`, else the open
   fails.
3. A sample line starts with its time, ended by a space, comma, tab, or
   newline. With `timefmt` empty, a time that `convert_to_timestamp()`
   reads is used in local time; otherwise it is read as
   `MONTH:DAY:HOUR:MINUTE:SECOND` (later fields optional). With `timefmt`
   set, it is read with that `sscanf()` format into month, day, hour,
   minute, and second. The values follow, separated by commas (empty
   fields are skipped, as `strtok()` skips them); only `double` columns
   are read, and a value that is not a number fails the open.
4. A sample whose time (with 31-day months) does not come after the
   previous sample's is discarded with a warning.
5. After the file is read, the reader's `latitude` is `lat_deg` plus or
   minus `lat_min/60` (minus unless `lat_deg` is positive), and likewise
   its `longitude`.
6. `get_data(t0)` returns `-next_ts`, the soft event when the sample in
   effect changes. While `t0` is before `next_ts`, nothing changes. On
   the first call it finds the last sample before `t0` in the year of
   `t0` (skipping February 29 in other years), or the last sample of the
   file when `t0` is before the first, and the time of the next sample
   (the first sample of the next year when every sample of the year is
   before `t0`); later calls move to the next sample, wrapping to the first sample of
   the next year. Sample times are local times with the time zone of
   `t0`. A file with one sample keeps its values and moves `next_ts` a
   year ahead.

Examples
--------

    >>> import os, tempfile
    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> folder = tempfile.mkdtemp()
    >>> with open(os.path.join(folder, "weather.csv"), "w") as fh:
    ...     _ = fh.write("$city_name=Berkeley\\ntemperature,humidity\\n1:01:00,50,0.05\\n1:01:01,62,0.16\\n")
    >>> cwd = os.getcwd(); os.chdir(folder)
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { timezone "America/Los_Angeles"; starttime "2001-01-01 01:00:00"; stoptime "2001-01-01 01:00:00"; }
    ... module climate;
    ... object csv_reader { name reader; filename "weather.csv"; }
    ... object climate { name weather; tmyfile "weather.csv"; reader reader; }
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> m.get_property("weather", "temperature"), m.get_property("reader", "city_name")
    ('62.0', 'Berkeley')
    >>> os.chdir(cwd)
    >>> Class.reset()

Caveats
-------

- Column values are in the units of the `weather` properties (`humidity`
  in %, `wind_speed` in mph, ...); the `climate` object converts them to
  its own units (see `climate.climate`).
- `status`, `low_temp`, `high_temp`, and `peak_solar` are published but
  never set, as in gridlabd.
- The file is read once; changing `filename` during a run has no effect.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A file without samples makes `get_data()` raise `ClimateError`;
   gridlabd reads before the start of an empty array.
2. A `timefmt` with a conversion other than an integer one fails the
   sample; gridlabd passes `short` pointers to any format.
3. Times are read with `arras.globals.Globals.timestamp_from_string()`,
   which accepts only IANA time zone names (#41).
4. When the run starts after the last sample of the year, that sample is
   in effect and the first sample of the next year comes next. gridlabd
   takes the second sample of the same year as the next one, an event in
   the past, which stops the run with an error.

References
----------

- `arras-energy/gridlabd`: `module/climate/csv_reader.cpp`,
  `csv_reader.h`, `weather_reader.cpp`; `source/timestamp.cpp`
  (`convert_to_timestamp()`, `local_datetime()`, `mkdatetime()`)
- [Csv_reader class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Climate/Csv_reader.md)
  (`docs/Module/Climate/Csv_reader.md`)
"""

from typing import Any

from arras.exceptions import ArrasException

from ._common import (TS_INVALID, TS_NEVER, ClimateError, get_state, set_state, get_text, get_double,
    store, sscanf, Tokenizer, int16, local_datetime, mkdatetime, isleapyear, read_lines,
    gl_error, gl_warning)
from .weather import Weather, new_sample

CR_INIT, CR_OPEN, CR_ERROR = 0, 1, 2
"""Values of `status`"""

STATUS = {"ERROR": CR_ERROR, "OPEN": CR_OPEN, "INIT": CR_INIT}
"""Keywords of `status`, as gridlabd lists them"""

LINE_SIZE = 1024
"""Size of gridlabd's line buffer"""

DEFAULT_TIMEFMT = "%hd:%hd:%hd:%hd:%hd"
"""Time format used when `timefmt` is empty and the time is not a timestamp"""

VALUES = ("temperature", "humidity", "solar_direct", "solar_diffuse", "solar_global",
    "global_horizontal_extra", "wind_speed", "wind_dir", "opq_sky_cov", "tot_sky_cov",
    "rainfall", "snowdepth", "pressure")
"""Sample values that `get_data()` gives, in gridlabd's argument order"""

class ReaderState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State that gridlabd keeps in unpublished `csv_reader` members"""

    def __init__(self):
        self.initialized = False
        self.columns: list[str] = []
        self.samples: list[dict[str,Any]] = []
        self.next_ts = 0
        self.index = 0

def _state(model:Any, name:str) -> ReaderState:
    state = get_state(model, name)
    if state is None:
        state = ReaderState()
        set_state(model, name, state)
    return state

class CsvReader:
    """Class `csv_reader`; see the module documentation"""

    NAME = "csv_reader"
    """gridlabd class name"""

    PASSCONFIG = "NOSYNC"
    """Pass configuration (gridlabd `PC_NOSYNC`)"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = (
        ("index", "int32", {"access": "REFERENCE", "description": "reader line index"}),
        ("city_name", "char32", {"description": "name of city"}),
        ("state_name", "char32", {"description": "name of state/province"}),
        ("lat_deg", "double", {"description": "latitude degrees"}),
        ("lat_min", "double", {"description": "latitude minutes"}),
        ("long_deg", "double", {"description": "longitude degrees"}),
        ("long_min", "double", {"description": "longitude minutes"}),
        ("low_temp", "double", {"access": "REFERENCE", "description": "lowest temperature"}),
        ("high_temp", "double", {"access": "REFERENCE", "description": "highest temperature"}),
        ("peak_solar", "double", {"access": "REFERENCE", "description": "peak solar flux"}),
        ("elevation", "int32", {"description": "elevation"}),
        ("status", "enumeration", {"access": "REFERENCE", "description": "reader status", "keywords": STATUS}),
        ("timefmt", "char32", {"description": "time format"}),
        ("timezone", "char32", {"description": "timezone"}),
        ("timezone_offset", "double", {"description": "timezone offset"}),
        ("columns", "char256", {"description": "column names"}),
        ("filename", "char256", {"description": "filename"}),
    )
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order"""

    @classmethod
    def register(cls, module:Any) -> Any:
        """Register the class for `module` with its properties and its
        `on_init` event handler"""
        oclass = module.register_class(cls.NAME, passconfig=cls.PASSCONFIG)
        for name, ptype, options in cls.PROPERTIES:
            oclass.publish(name, ptype, **options)
        oclass.set_event("init", "python:climate.reader_init")
        return oclass

    @classmethod
    def init(cls, model:Any, name:str) -> bool:
        """`init_csv_reader()`: the climate object opens the file; the
        object is marked initialized"""
        _state(model, name).initialized = True
        return True

    @classmethod
    def is_initialized(cls, model:Any, name:str) -> bool:
        """`True` once the object's `init` handler has run (gridlabd
        `OF_INIT`)"""
        state = get_state(model, name)
        return state is not None and state.initialized

    @classmethod
    def timezone_offset(cls, model:Any, name:str) -> float:
        """Value of `timezone_offset`"""
        return get_double(model, name, "timezone_offset")

    #
    # Reading the file
    #
    @classmethod
    def open(cls, model:Any, name:str, file:str) -> int: # pylint: disable=too-many-branches
        """Read a file (gridlabd `csv_reader::open()`); 1 on success, 0
        on failure (with an error line)"""
        state = _state(model, name)
        state.columns = []
        state.samples = []
        has_cols = False
        try:
            lines = read_lines(file[:127], LINE_SIZE)
        except OSError:
            gl_error(f"csv_reader could not open '{file}' for input!")
            return 0
        columns = get_text(model, name, "columns")
        if columns:
            if not cls._read_header(model, name, columns):
                gl_error("csv_reader::open ~ column header read failure from explicit headers")
                return 0
            has_cols = True
        for linenum, line in enumerate(lines, start=1):
            if line.startswith("#"):
                continue
            if line.startswith("$"):
                if not cls._read_prop(model, name, line[1:]):
                    gl_error(f"csv_reader::open ~ property read failure on line {linenum}")
                    return 0
                continue
            if not has_cols:
                if not cls._read_header(model, name, line):
                    gl_error(f"csv_reader::open ~ column header read failure on line {linenum}")
                    return 0
                has_cols = True
                continue
            result = cls._read_line(model, name, line, linenum)
            if result == 0:
                gl_error(f"csv_reader::open ~ data line read failure on line {linenum}")
                return 0
        lat_deg = get_double(model, name, "lat_deg")
        lat_min = get_double(model, name, "lat_min")
        long_deg = get_double(model, name, "long_deg")
        long_min = get_double(model, name, "long_min")
        store(model, name, {
            "latitude": lat_deg + (lat_min if lat_deg > 0 else -lat_min) / 60,
            "longitude": long_deg + (long_min if long_deg > 0 else -long_min) / 60,
        })
        return 1

    @classmethod
    def _read_prop(cls, model:Any, name:str, line:str) -> bool:
        if "=" not in line:
            gl_error("csv_reader::read_prop ~ missing '=' seperator")
            return False
        count, values = sscanf(line, "%[^=]=%[^\n#]")
        if count != 2:
            gl_error("csv_reader::read_prop ~ error reading property & value")
            return False
        propstr, valstr = values[0], values[1]
        spec = model.objects[name].oclass.find_property(propstr)
        if spec is None:
            gl_error(f"csv_reader::read_prop ~ unrecognized csv_reader property '{propstr}'")
            return False
        if spec.ptype == "double":
            count, number = sscanf(valstr, "%lg")
            if count != 1:
                gl_error(f"csv_reader::read_prop ~ unable to set property '{propstr}' to '{valstr}'")
                return False
            store(model, name, {propstr: float(number[0])})
        elif spec.ptype == "char32":
            store(model, name, {propstr: valstr[:31]})
        else:
            gl_error(f"csv_reader::read_prop ~ unable to convert property '{propstr}' due to type restrictions")
            return False
        return True

    @classmethod
    def _read_header(cls, model:Any, name:str, line:str) -> bool:
        state = _state(model, name)
        buffer = line[:LINE_SIZE-1]
        names = []
        index = start = 0
        size = len(buffer)
        stops = ",\n\r#"
        while True:
            while index < size and buffer[index] not in stops:
                index += 1
            end = index
            if index < size and buffer[index] == ",":
                index += 1
            terminated = index >= size or buffer[index] in "\n\r#"
            names.append(buffer[start:end])
            start = index
            if terminated:
                break
        columns = Weather.columns()
        for column in names:
            if column not in columns:
                gl_error(f"csv_reader::read_header ~ unable to find column property '{column}''")
                return False
        state.columns.extend(names)
        return True

    @classmethod
    def _read_line(cls, model:Any, name:str, line:str, linenum:int) -> int: # pylint: disable=too-many-return-statements,too-many-branches
        state = _state(model, name)
        tokens = Tokenizer(line[:LINE_SIZE-1])
        token = tokens.next(" ,\t\n\r")
        if token is None:
            return 2
        sample = new_sample()
        timefmt = get_text(model, name, "timefmt")
        fields = ("month", "day", "hour", "minute", "second")
        if not timefmt:
            ts = cls._timestamp(model, token)
            local = local_datetime(model, ts) if ts not in (TS_INVALID, TS_NEVER) else None
            if local is not None:
                for key in fields:
                    sample[key] = getattr(local, key)
            else:
                count, values = sscanf(token, DEFAULT_TIMEFMT)
                if count < 1:
                    gl_error(f"csv_reader::read_line ~ unable to read time string '{token}' with default format")
                    return 0
                for key, value in zip(fields, values):
                    sample[key] = int16(value)
        else:
            count, values = sscanf(token, timefmt)
            if count < 1 or not all(isinstance(x, int) for x in values):
                gl_error(f"csv_reader::read_line ~ unable to read time string '{token}' with format '{timefmt}'")
                return 0
            for key, value in zip(fields, values):
                sample[key] = int16(value)
        if state.samples:
            last = state.samples[-1]
            t1 = last["month"]*31*86400 + last["day"]*86400 + last["hour"]*3600 + last["minute"]*60 + last["second"]
            t2 = sample["month"]*31*86400 + sample["day"]*86400 + sample["hour"]*3600 + sample["minute"]*60 + sample["second"]
            if t1 >= t2:
                gl_warning(f"csv_reader::read_line ~ sample on line {linenum} does not advance in time and has been discarded")
                return 2
        columns = Weather.columns()
        col = 0
        while True:
            token = tokens.next(",\n\r")
            if token is None or col >= len(state.columns):
                break
            column = state.columns[col]
            if columns[column] == "double":
                count, values = sscanf(token, "%lg")
                if count != 1:
                    gl_error(f"csv_reader::read_line ~ unable to set value '{token}' to double property '{column}'")
                    return 0
                sample[column] = float(values[0])
            col += 1
        state.samples.append(sample)
        return 1

    @staticmethod
    def _timestamp(model:Any, token:str) -> int:
        """gridlabd `convert_to_timestamp()`, `TS_INVALID` when the text is
        not a timestamp"""
        try:
            return model.globals.timestamp_from_string(token.strip("'\""))
        except ArrasException:
            return TS_INVALID

    #
    # Samples
    #
    @classmethod
    def get_data(cls, model:Any, name:str, t0:int) -> tuple[int,dict[str,float]|None]: # pylint: disable=too-many-branches,too-many-locals
        """The soft event when the sample in effect changes (`-next_ts`)
        and the values of the sample in effect at `t0` (`None` when they
        do not change); see the module description

        Exceptions
        ----------
        - `ClimateError`: the file has no samples, the time cannot be
          converted to local time, or no sample follows the current one
        """
        state = _state(model, name)
        samples = state.samples
        count = len(samples)
        if t0 < state.next_ts:
            return -state.next_ts, None
        if count == 0:
            raise ClimateError(f"csv_reader {name} has no samples")
        now = local_datetime(model, t0)
        if now is None:
            raise ClimateError(f"csv_reader::get_data(t0={t0}): unable to resolve local time")
        def mktime(year:int, sample:dict[str,Any]) -> int:
            return mkdatetime(model, (year, sample["month"], sample["day"], sample["hour"],
                sample["minute"], sample["second"]), now.is_dst)
        if state.next_ts == 0:
            i = 0
            while i < count:
                sample = samples[i]
                if sample["month"] == 2 and sample["day"] == 29 and not isleapyear(now.year):
                    i += 1
                    continue
                if mktime(now.year, sample) >= t0:
                    i -= 1
                    break
                i += 1
            if i == count:
                # every sample of the year is before t0: the last one is in
                # effect and the first one of the next year comes next
                i = count - 1
            state.index = i
            values = samples[i] if -1 < i < count else samples[count-1]
            year = now.year + (1 if i+1 == count else 0)
            state.next_ts = mktime(year, samples[(i+1) % count])
            store(model, name, {"index": state.index})
            return -state.next_ts, {key: values[key] for key in VALUES}
        if count == 1:
            state.next_ts += 365 * 24 * 3600
            return -state.next_ts, None
        start = state.index
        while True:
            state.index = 0 if state.index+1 >= count else state.index+1
            next_year = 1 if state.index+1 == count else 0
            year = now.year + next_year
            then = samples[(state.index+1) % count]
            if not (then["month"] == 2 and then["day"] == 29 and not isleapyear(year)):
                state.next_ts = mktime(year, then)
            if not (state.next_ts < t0 and state.index != start):
                break
        store(model, name, {"index": state.index})
        if state.index == start:
            raise ClimateError("something strange happened with the schedule in csv_reader")
        values = samples[state.index]
        return -state.next_ts, {key: values[key] for key in VALUES}
