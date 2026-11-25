# pylint: disable=line-too-long
"""TMY2 and TMY3 weather files (gridlabd `tmy2_reader`)

`TmyReader` reads the typical meteorological year files that the
`climate` class loads: NREL TMY2 files (`.tmy2`, fixed columns) and TMY3
files (`.tmy3`, comma-separated). It reads them as gridlabd's
`tmy2_reader` class does, with the same C `sscanf()` formats, so the same
files are accepted and the same values are read.

Syntax
------

    from climate.tmy import TmyReader
    reader = TmyReader()
    count = reader.open(path)          # header fields read, 0 on failure
    while reader.next():
        record = reader.read_data()    # TmyRecord
    reader.close()

Description
-----------

`TmyReader` is expected to satisfy:

1. `open()` reads the header line. A file name without an extension, a
   file that cannot be opened, an empty file, and an extension other than
   `.tmy2` and `.tmy3` give an error line and return 0. Otherwise it
   returns the number of header fields read: 10 for a complete TMY2
   header, 6 for a complete TMY3 header. A TMY2 file gives the warning
   that daylight saving time is not handled correctly.
2. The TMY2 header gives the city, state, time zone, latitude and
   longitude in degrees and minutes with their hemispheres, and the
   elevation; the TMY3 header gives the decimal latitude and longitude,
   which are split into whole degrees and rounded minutes as gridlabd
   splits them (in single precision). Southern latitudes and western
   longitudes are negative degrees.
3. `read_data()` reads the line that `next()` read: a TMY3 line (one
   whose third character is `/`) by its comma-separated fields, else a
   TMY2 line by its columns. It gives an error line when it reads fewer
   than 17 values. Units are converted as gridlabd converts them:
   temperature in degC (TMY3 values truncated to tenths), humidity as a
   fraction, wind speed in m/s (TMY3 truncated to tenths), precipitation
   in in/h (whole mm times 0.03937; the TMY3 value in cm is truncated
   to tenths), snow depth in in (always 0 for TMY3), sky covers in tenths
   as fractions, wind direction in degrees, solar values in W/m^2.
4. `calc_solar()` gives the solar flux on a surface facing a compass
   point: the direct normal irradiance times the cosine of incidence,
   plus the diffuse horizontal irradiance.

Examples
--------

    >>> import os, tempfile
    >>> from climate.tmy import TmyReader
    >>> path = os.path.join(tempfile.mkdtemp(), "site.tmy3")
    >>> with open(path, "w") as fh:
    ...     _ = fh.write('727810,"YAKIMA AIR TERMINAL",WA,-8.0,46.567,-120.550,324\\n')
    >>> reader = TmyReader()
    >>> reader.open(path)
    6
    >>> reader.lat_degrees, reader.lat_minutes, reader.long_degrees, reader.long_minutes, reader.tz_offset
    (46, 34, -120, 33, -8)
    >>> reader.close()

Caveats
-------

- The TMY3 snow depth is always 0, and the TMY3 precipitation field is
  the liquid precipitation depth, read as gridlabd reads it.
- Lines are read in parts of up to 499 characters, as gridlabd's
  `fgets()` buffer reads them.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Values that a short or malformed line does not provide are 0; gridlabd
   leaves them uninitialized.
2. The TMY2 flag that shifts the hours of TMY3 data belongs to the
   reader; gridlabd keeps one flag for all readers (see `climate.climate`).

References
----------

- `arras-energy/gridlabd`: `module/climate/climate.cpp`
  (`tmy2_reader::open()`, `next()`, `header_info()`, `read_data()`,
  `calc_solar()`, `close()`), `climate.h`
- [TMY2 user's manual](https://www.nrel.gov/docs/legosti/old/7668.pdf),
  [TMY3 user's manual](https://www.nrel.gov/docs/fy08osti/43156.pdf)
"""

import math
from dataclasses import dataclass

from ._common import sscanf, atoi, atof, read_lines, float32, c_round, rad, gl_error, gl_warning
from .solar_angles import SolarAngles

CP_H, CP_N, CP_NE, CP_E, CP_SE, CP_S, CP_SW, CP_W, CP_NW, CP_LAST = range(10)
"""Compass points (gridlabd `COMPASS_PTS`): horizontal, then north
clockwise to northwest"""

SURFACE_ANGLES = (360, 180, 135, 90, 45, 0, -45, -90, -135)
"""Azimuth of the surface facing each compass point, from south (degrees,
east positive)"""

BUFFER_SIZE = 500
"""Size of gridlabd's line buffer"""

TMY2_HEADER = "%*s %75s %3s %d %c %d %d %c %d %d %d"
"""`sscanf()` format of the TMY2 header"""

TMY3_HEADER = "%*[^','],%[^','],%[^','],%[^','],%[^','],%[^','],%s"
"""`sscanf()` format of the TMY3 header"""

TMY2_DATA = "%*2s%2d%2d%2d%4d%4d%4d%*2s%4d%*2s%4d%*26s%2d%*2s%2d%*2s%4d%*8s%3d%*2s%4d%*2s%3d%*2s%3d%*25s%3d%*7s%3d"
"""`sscanf()` format of a TMY2 data line"""

TMY3_DATA = "%[^','],%[^','],%[^','],%[^','],%[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%*[^','],%[^','],%*[^','],%*[^','],%*[^','],%*s"
"""`sscanf()` format of a TMY3 data line, as gridlabd writes it"""

@dataclass
class TmyRecord: # pylint: disable=too-many-instance-attributes
    """Values of one TMY line (see the module description for units)"""
    month: int = -1
    day: int = -1
    hour: int = -1
    dnr: float = 0.0
    dhr: float = 0.0
    ghr: float = 0.0
    tdb: float = 0.0
    rh: float = 0.0
    wind: float = 0.0
    winddir: float = 0.0
    precip: float = 0.0
    snow_depth: float = 0.0
    pressure: float = 0.0
    extra_terr_dni: float = 0.0
    extra_terr_ghi: float = 0.0
    tot_sky_cov: float = 0.0
    opq_sky_cov: float = 0.0

class TmyReader: # pylint: disable=too-many-instance-attributes
    """TMY2 and TMY3 file reader; see the module documentation

    Attributes
    ----------
    - `data_city`, `data_state`: header city and state
    - `tz_offset`: time zone (hours east of UTC, whole hours)
    - `lat_degrees`, `lat_minutes`, `long_degrees`, `long_minutes`:
      location (degrees negative in the southern and western hemispheres)
    - `elevation`: elevation (m)
    - `is_tmy2`: the file is a TMY2 file
    - `buf`: the line read last
    - `peak_solar`: largest flux given by `calc_solar()`
    - `report_error`: function that writes `read_data()`'s error lines
      (`gl_error()`)
    """

    def __init__(self):
        self.data_city = ""
        self.data_state = ""
        self.tz_offset = 0
        self.lat_degrees = 0
        self.lat_minutes = 0
        self.long_degrees = 0
        self.long_minutes = 0
        self.elevation = 0
        self.low_temp = 0.0
        self.high_temp = 0.0
        self.peak_solar = 0.0
        self.is_tmy2 = False
        self.buf = ""
        self._lines: list[str] = []
        self._next = 0
        self.report_error = gl_error

    def open(self, file:str) -> int: # pylint: disable=too-many-branches,too-many-statements
        """Open a file and read its header; returns the number of header
        fields read, or 0 on failure (with an error line)"""
        self.is_tmy2 = False
        dot = file.rfind(".")
        ext = file[dot:] if dot >= 0 else None
        if ext is None:
            gl_error(f"tmy2_reader::open(file='{file}'): file name missing type extension")
            return 0
        try:
            self._lines = read_lines(file, BUFFER_SIZE)
        except OSError:
            gl_error(f"tmy2_reader::open(file='{file}') -- fopen failed")
            return 0
        self._next = 0
        if not self._lines:
            gl_error(f"tmy2_reader::open(file='{file}') -- first fgets read nothing")
            return 0
        self.buf = self._lines[0]
        self._next = 1
        lat_hem = long_hem = ""
        if ext == ".tmy2":
            count, values = sscanf(self.buf, TMY2_HEADER)
            fields = ["data_city", "data_state", "tz_offset", "lat_hem", "lat_degrees", "lat_minutes",
                "long_hem", "long_degrees", "long_minutes", "elevation"]
            for key, value in zip(fields, values):
                if key == "lat_hem":
                    lat_hem = value
                elif key == "long_hem":
                    long_hem = value
                else:
                    setattr(self, key, value)
            gl_warning("daylight saving time (DST) is not handled correctly when using TMY2 datasets; please use TMY3 for DST-corrected weather data.")
            self.is_tmy2 = True
        elif ext == ".tmy3":
            count, values = sscanf(self.buf, TMY3_HEADER)
            values = values + [""] * (6 - len(values))
            self.data_city, self.data_state = values[0], values[1]
            tz_offset_temp = float32(atof(values[2]))
            lat_degrees_temp = float32(atof(values[3]))
            long_degrees_temp = float32(atof(values[4]))
            self.elevation = atoi(values[5])
            self.tz_offset = int(tz_offset_temp)
            lat_hem = "S" if lat_degrees_temp < 0 else "N"
            long_hem = "W" if long_degrees_temp < 0 else "E"
            frac = math.modf(lat_degrees_temp)[0]
            self.lat_minutes = int(abs(c_round(frac*60)))
            self.lat_degrees = int(abs(int(lat_degrees_temp)))
            frac = math.modf(long_degrees_temp)[0]
            self.long_minutes = int(abs(c_round(frac*60)))
            self.long_degrees = int(abs(int(long_degrees_temp)))
        else:
            gl_error(f"tmy2_reader::open(file='{file}'): unknown TMY file type (extension '{ext}' is not recognized)")
            return 0
        if lat_hem in ("S", "s"):
            self.lat_degrees = -self.lat_degrees
        if long_hem in ("W", "w"):
            self.long_degrees = -self.long_degrees
        return max(count, 0)

    def next(self) -> bool:
        """Read the next line into `buf`; `False` at the end of the file"""
        if self._next >= len(self._lines):
            return False
        self.buf = self._lines[self._next]
        self._next += 1
        return True

    def header_info(self) -> tuple[str,str,int,int,int,int]:
        """City, state, latitude degrees and minutes, longitude degrees
        and minutes"""
        return (self.data_city, self.data_state, self.lat_degrees, self.lat_minutes,
            self.long_degrees, self.long_minutes)

    def read_data(self) -> TmyRecord: # pylint: disable=too-many-locals
        """Values of the line in `buf` (see the module description)"""
        buf = self.buf
        rec = TmyRecord()
        if buf[2:3] == "/":
            rct, values = sscanf(buf, TMY3_DATA)
            text = values + [""] * (16 - len(values))
            t_ymd, t_hm, t_ehr, t_dni, t_ghr, t_dnr, t_dhr, t_tkc, t_osc, t_tdb, t_rh, t_press, t_wd, t_ws, t_precip, _ = text
            count, date = sscanf(t_ymd, "%d/%d/%*d")
            if count >= 1:
                rec.month = date[0]
            if count >= 2:
                rec.day = date[1]
            if count != 2:
                self.report_error(f"TMY reader did not read a complete date from '{t_ymd}'")
            count, hour = sscanf(t_hm, "%d:%*d")
            if count >= 1:
                rec.hour = hour[0]
            if count != 1:
                self.report_error(f"TMY reader did not read a complete time from '{t_hm}'")
            ints = {
                "extra_ghr": atoi(t_ehr), "extra_dni": atoi(t_dni), "ghr": atoi(t_ghr),
                "dnr": atoi(t_dnr), "dhr": atoi(t_dhr), "tot": atoi(t_tkc), "opq": atoi(t_osc),
                "tdb": int(atof(t_tdb)*10), "rh": atoi(t_rh), "press": atoi(t_press),
                "wd": atoi(t_wd), "ws": int(atof(t_ws)*10), "precip": int(atof(t_precip)*10),
                "sf": 0,
            }
            rct = max(rct, 0) + 1
        else:
            rct, values = sscanf(buf, TMY2_DATA)
            values = values + [0] * (17 - len(values))
            read = max(rct, 0)
            rec.month = values[0] if read >= 1 else -1
            rec.day = values[1] if read >= 2 else -1
            rec.hour = values[2] if read >= 3 else -1
            keys = ("extra_ghr", "extra_dni", "ghr", "dnr", "dhr", "tot", "opq", "tdb", "rh",
                "press", "wd", "ws", "precip", "sf")
            ints = dict(zip(keys, values[3:]))
        if rct != 17:
            self.report_error(f"TMY reader did not get 17 values for line time {rec.month}/{rec.day} {rec.hour}00")
        rec.dnr = float(ints["dnr"])
        rec.dhr = float(ints["dhr"])
        rec.ghr = float(ints["ghr"])
        rec.extra_terr_dni = float(ints["extra_dni"])
        rec.pressure = float(ints["press"])
        rec.tdb = float(ints["tdb"])/10.0
        if rec.tdb < self.low_temp or self.low_temp == 0:
            self.low_temp = rec.tdb
        elif rec.tdb > self.high_temp or self.high_temp == 0:
            self.high_temp = rec.tdb
        rec.rh = float(ints["rh"])/100.0
        rec.wind = ints["ws"]/10.0
        rec.precip = float(ints["precip"]) * 0.03937
        rec.snow_depth = float(ints["sf"]) * 0.3937
        rec.extra_terr_ghi = float(ints["extra_ghr"])
        rec.tot_sky_cov = ints["tot"]/10.0
        rec.opq_sky_cov = ints["opq"]/10.0
        rec.winddir = float(ints["wd"])
        return rec

    def calc_solar(self, cpt:int, doy:int, lat:float, sol_time:float, dnr:float, dhr:float, vert_angle:float=90) -> float: # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Solar flux on a surface facing compass point `cpt` with slope
        `vert_angle` (degrees): `dnr*cos_incident + dhr`"""
        surface_angle = SURFACE_ANGLES[cpt]
        cos_incident = SolarAngles.cos_incident(lat, rad(vert_angle), rad(surface_angle), sol_time, doy)
        solar = dnr * cos_incident + dhr
        if self.peak_solar == 0 or solar > self.peak_solar:
            self.peak_solar = solar
        return solar

    def close(self) -> None:
        """Close the file"""
        self._lines = []
        self._next = 0
