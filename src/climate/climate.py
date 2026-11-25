# pylint: disable=line-too-long,too-many-lines
# (the markdown tables in the docstring are kept one row per line)
"""Weather (class `climate`)

A `climate` object gives the weather of a site at each time of a
simulation: temperature, humidity, solar irradiance (direct, diffuse,
global, and on surfaces facing nine directions), solar position, wind,
pressure, precipitation, sky cover, and the heat index. It reads a TMY2
or TMY3 file, or a CSV file through a `csv_reader` object, or, with no
file, keeps the values that the model sets ("manual climate control").

Syntax
------

    module climate;
    object climate {
        tmyfile "<file-name>.tmy3";        // .tmy2, .tmy3, .tmy, or .csv
        [reader "<csv_reader-name>";]      // required for .csv files
        [interpolate NONE|LINEAR|QUADRATIC;]
        [ground_reflectivity <decimal> pu;]
        [cloud_model NONE|CUMULUS;]
        [cloud_opacity <decimal> pu; cloud_speed_factor <decimal> pu;]
        [cloud_alpha <decimal> pu; cloud_num_layers <decimal> pu;]
        [cloud_aerosol_transmissivity <decimal> pu;]
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `solar_elevation` | `double[rad]` | `0.0` | solar elevation angle in radians |
| `solar_azimuth` | `double[rad]` | `0.0` | solar azimuth angle in radians |
| `solar_zenith` | `double[rad]` | `0.0` | solar zenith angle in radians |
| `city` | `char256` | | weather data city name |
| `tmyfile` | `char1024` | | weather data file name (required) |
| `temperature` | `double[degF]` | `59.0 degF` | current temperature |
| `humidity` | `double[pu]` | `75%` | current humidity |
| `solar_flux` | `double[W/sf]` | `0.0` | current solar irradiance (9 orientiations) |
| `solar_direct` | `double[W/sf]` | `0.0` | solar direct irradiance |
| `solar_diffuse` | `double[W/sf]` | `0.0` | solar diffuse irradiance |
| `solar_global` | `double[W/sf]` | `0.0` | solar global flux irradiance |
| `extraterrestrial_global_horizontal` | `double[W/sf]` | `0.0` | solar global extraterrestrial irradiance |
| `extraterrestrial_direct_normal` | `double[W/sf]` | `1367 W/m^2` | solar direct normal extraterrestrial irradiance |
| `pressure` | `double[mbar]` | `1013.25 mbar` | current air pressure |
| `wind_speed` | `double[m/s]` | `0.0` | current wind speed |
| `wind_dir` | `double[rad]` | `0.0` | current direction in radians |
| `wind_gust` | `double[m/s]` | `0.0` | current wind gusts |
| `record.low` | `double[degF]` | `0.0` | record low temperature observed |
| `record.low_day` | `int32` | `0` | day of year for record low observation |
| `record.high` | `double[degF]` | `0.0` | record high temperature observed |
| `record.high_day` | `int32` | `0` | day of year for record high observation |
| `record.solar` | `double[W/sf]` | `0.0` | record high solar irradiance observed |
| `rainfall` | `double[in/h]` | `0.0` | rainfall observed |
| `snowdepth` | `double[in]` | `0.0` | snow depth observed |
| `interpolate` | `enumeration {QUADRATIC=2, LINEAR=1, NONE=0}` | `NONE` | the interpolation mode used on the climate data |
| `solar_horiz` ... `solar_northwest` | `double` | `0.0` | solar flux on the horizontal, north, northeast, east, southeast, south, southwest, west, and northwest surfaces |
| `solar_raw` | `double[W/sf]` | `0.0` | raw solar flux |
| `ground_reflectivity` | `double[pu]` | `0.3 pu` | ground reflectivity observed |
| `reader` | `object` | | weather reader object |
| `forecast` | `char1024` | | forecasting specifications |
| `cloud_model` | `enumeration {CUMULUS=1, NONE=0}` | `NONE` | the cloud model to use |
| `cloud_opacity` | `double[pu]` | `1.0 pu` | cloud opacity factor |
| `opq_sky_cov` | `double[pu]` | `0.0` | cloud sky coverage factor |
| `cloud_speed_factor` | `double[pu]` | `1.0 pu` | cloud speed factor |
| `solar_cloud_direct` | `double[W/sf]` | `0.0` | cloud direct irradiance |
| `solar_cloud_diffuse` | `double[W/sf]` | `0.0` | cloud diffuse irradiance |
| `solar_cloud_global` | `double[W/sf]` | `0.0` | cloud global irradiance |
| `cloud_alpha` | `double[pu]` | `400 pu` | cloud alpha |
| `cloud_num_layers` | `double[pu]` | `40 pu` | number of cloud layers |
| `cloud_aerosol_transmissivity` | `double[pu]` | `0.95 pu` | cloud aerosal transmissivity |
| `heat_index` | `double[degF]` | `0.0` | heat index based on temperature and humidity |

All are output properties except `city`, `tmyfile`, `reader`, and
`forecast`. The class functions are listed under Functions.

Description
-----------

The class has `on_init "python:climate.init"` and
`on_presync "python:climate.presync"`. A `climate` object is expected to
satisfy:

1. **Initialization.** An empty `tmyfile` leaves the values as the model
   sets them. Otherwise the file is found as the name given, then in each
   folder of `climate::library_path` (separated by `:` or `;`), then with
   `arras.folders.findfile()`; a file not found fails with `weather file
   'NAME' access failed`. A name containing `.tmy` (`.tmy2`, `.tmy3`) is a
   TMY file, one containing `.csv` a CSV file, and others give a warning
   and are read as TMY files (whose extension must then be `.tmy2` or
   `.tmy3`).
2. **TMY files.** The header gives the object's `latitude` and
   `longitude` (degrees plus minutes/60, with the sign of the degrees);
   a latitude beyond 90 or a longitude beyond 180 degrees fails, and a
   southern latitude gives a warning. Each line with a digit as its
   second character is a record of hour `hour-1` of day
   `day_of_yr(month,day)`; records out of the 8760 hours of a year give a
   warning. For each record, solar values are converted from W/m^2 to
   W/sf, the temperature from degC to degF (with `arras.units`), and the
   solar elevation, azimuth, and zenith, and the flux on the nine
   surfaces (`dnr*cos_incident + dhr`, vertical surfaces and the
   horizontal one) are computed at the solar time of the record's hour.
   `record.low`, `record.high` (with their days), and `record.solar`
   track the extremes. Fewer than 8760 records give an error line, and a
   `.tmy2` file a warning. The object then runs its presync at the clock.
3. **CSV files.** `reader` must name a `csv_reader` object, else the
   initialization fails; if that object is not initialized yet, the
   initialization is deferred. The reader opens its file (see
   `climate.csv_reader`); the object takes the reader's `latitude`,
   `longitude`, and `timezone_offset`, with the same checks as for TMY
   files.
4. **Presync.** With a CSV file, the values of the sample in effect are
   copied from the reader and the solar zenith and the flux on the nine
   surfaces are computed at the current solar time; the result is the
   reader's soft event. With a TMY file, the record of the current local
   hour is used, one hour earlier for TMY3 data (two during daylight
   saving time) because TMY values summarize the preceding hour, wrapping
   at the start of the year. `interpolate` gives the values: the record's
   (`NONE`), linear between the record and the next one (`LINEAR`), or
   quadratic through the record and the next two (`QUADRATIC`, with
   values that cannot be negative clipped at 0 with a verbose message, and
   `wind_dir` wrapped into 0 to 360), by the minute of the hour. The heat
   index is updated and the result is a soft event at the next hour.
5. **Heat index.** Below 80 degF it is `0.75*T + 0.25*(61+1.2*(T-68)+0.094*RH)`;
   otherwise the NOAA regression with its low and high humidity
   adjustments (`T` in degF, `RH` in percent).
6. **Cloud model.** With `cloud_model CUMULUS`, the initialization checks
   the cloud properties (out-of-range values are set to their limits with
   a warning), warns that the model is a large burden, and builds a cloud
   pattern over the `solar` objects (see `climate.cloud`). Each presync
   at a new time computes the clear-sky transmissivity from the pressure
   and the solar zenith and moves the pattern with the wind; the result
   is then the earlier of a hard event 60 s later and the file's event.
7. A time at or before `INIT` gives `NEVER`; without a file or cloud
   model the result is `NEVER`.

Functions
---------

The class functions (`arras.oclass.Class.get_function()`) take the model
and the name of a climate object, and return the irradiance on a surface
in W/sf, or `None` when the object is not a climate object, as gridlabd
returns 0 without a value:

| Function | Arguments after the model and name |
| -------- | ---------------------------------- |
| `calculate_solar_radiation_degrees` | `tilt`, `orientation` (degrees) |
| `calculate_solar_radiation_radians` | `tilt`, `orientation` |
| `calculate_solar_radiation_shading_degrees` | `tilt`, `orientation` (degrees), `shading_value` |
| `calculate_solar_radiation_shading_radians` | `tilt`, `orientation`, `shading_value` |
| `calculate_solar_radiation_shading_position_radians` | `tilt`, `orientation`, `latitude`, `longitude`, `shading_value` |
| `calculate_solpos_radiation_shading_position_radians` | `tilt`, `orientation`, `latitude`, `longitude`, `shading_value` |
| `calc_solar_ideal_shading_position_radians` | `tilt`, `latitude`, `longitude`, `shading_value` |

The first five give `shading*dnr*cos_incident + dhr*(1+cos(tilt))/2 +
ghr*(1-cos(tilt))*ground_reflectivity/2` at the object's `clock` with
the Duffie and Beckman position; the SOLPOS function uses SOLPOS and the
Perez diffuse model (with the clock half an hour later for TMY files);
the ideal function gives `shading*dnr + dhr +
ghr*(1-cos(tilt))*ground_reflectivity/2`. The latitude and longitude
select the cloud value when the cloud model is on.

Examples
--------

A site whose weather the model sets (no file):

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-07-01 12:00:00 UTC"; stoptime "2020-07-01 12:00:00 UTC"; }
    ... module climate;
    ... object climate { name site; tmyfile ""; temperature 90; humidity 0.5; }
    ... ''')
    >>> Runner(model=m).returncode
    0
    >>> m.get_property("site", "temperature")
    '90'
    >>> f = m.classes["climate"].get_function("calc_solar_ideal_shading_position_radians")
    >>> m.set_property("site", "solar_direct", 50)
    >>> f(m, "site", 0.0, 0.0, 0.0, 1.0)
    50.0
    >>> Class.reset()

Caveats
-------

- `solar_flux` is an array of nine values in gridlabd, of which a
  property reads and writes the first (the horizontal surface, the same
  value as `solar_horiz`). `solar_flux()` gives all nine.
- Values are stored in the units of the data, whatever the published
  unit: `wind_dir` holds degrees (published as radians), and CSV values
  are copied without conversion. This is gridlabd's behavior.
- The CSV path does not update `heat_index`, and computes the solar time
  and flux with the day of the year counted from 0 (the zenith from 1),
  as gridlabd does.
- `forecast` is published but not used (gridlabd's forecasting code is
  disabled).
- The SOLPOS function takes the panel `orientation` in radians as the
  SOLPOS `aspect` and the climate's `longitude` in degrees, as gridlabd
  passes them.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `record.low_day` and `record.high_day` give the day of the year;
   gridlabd publishes these `double` members as `int32`, so it reads the
   low 32 bits of the double (0 for whole days).
2. Interpolation at the last hours of the year uses the first hours of
   the year; gridlabd reads past the end of its 8760 records
   (`tmy[hoy+1%8760]` is `tmy[hoy+1]`).
3. Whether TMY3 hours are shifted belongs to each object; gridlabd keeps
   one flag, set by the last TMY file opened by any object.
4. Hours that a TMY file does not give have zero values; gridlabd leaves
   them uninitialized.
5. See `climate.cloud`, `climate.csv_reader`, and `climate.tmy` for the
   differences of the cloud model and the readers.

gridlabd's documentation of the class (`docs/Module/Climate/Climate.md`)
was generated from an older version: it gives `city` as `char32` and
lists the keywords in another form. This package follows the code
(decision 9.2 of DESIGN.md).

References
----------

- `arras-energy/gridlabd`: `module/climate/climate.cpp`, `climate.h`,
  `init.cpp`, `solar_angles.cpp`; `source/interpolate.cpp`,
  `source/find.cpp` (`find_file()`)
- [Climate class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Climate/Climate.md)
  (`docs/Module/Climate/Climate.md`)
- [NOAA heat index equation](https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml)
"""

import os
import math
from typing import Any

import arras.folders
from arras.oclass import Class

from ._common import (MODULE, TS_ZERO, TS_NEVER, ClimateError, rad, get_state, set_state, get_double,
    get_text, get_keyword, store, local_datetime, lerp, qerp, gl_error, object_error, object_warning,
    object_verbose, header_name, object_rng, to_timestamp)
from .solar_angles import SolarAngles, SolposData, PI_OVER_180
from .tmy import TmyReader, CP_H, CP_E, CP_LAST
from .csv_reader import CsvReader
from .cloud import CloudPattern, EMPTY_VALUE, solar_locations

CI_NONE, CI_LINEAR, CI_QUADRATIC = 0, 1, 2
"""Values of `interpolate`"""

CM_NONE, CM_CUMULUS = 0, 1
"""Values of `cloud_model`"""

RT_NONE, RT_TMY2, RT_CSV = 0, 1, 2
"""Reader types (gridlabd `RECORDTYPE`)"""

INTERPOLATE = {"QUADRATIC": CI_QUADRATIC, "LINEAR": CI_LINEAR, "NONE": CI_NONE}
"""Keywords of `interpolate`, as gridlabd lists them"""

CLOUD_MODEL = {"CUMULUS": CM_CUMULUS, "NONE": CM_NONE}
"""Keywords of `cloud_model`, as gridlabd lists them"""

HOURS = 8760
"""Records in a TMY year"""

FLUX = ("solar_horiz", "solar_north", "solar_northeast", "solar_east", "solar_southeast",
    "solar_south", "solar_southwest", "solar_west", "solar_northwest")
"""Properties of the solar flux on each compass point (in `CP_*` order)"""

TMY_FIELDS = ("temp", "rh", "dnr", "dhr", "ghr", "windspeed", "rainfall", "snowdepth",
    "solar_azimuth", "solar_elevation", "solar_zenith", "temp_raw", "solar_raw", "pressure",
    "direct_normal_extra", "global_horizontal_extra", "wind_dir", "tot_sky_cov", "opq_sky_cov")
"""Values of a TMY record that presync interpolates, in gridlabd's order"""

PROPERTY_OF = {"temp": "temperature", "rh": "humidity", "dnr": "solar_direct", "dhr": "solar_diffuse",
    "ghr": "solar_global", "windspeed": "wind_speed", "rainfall": "rainfall", "snowdepth": "snowdepth",
    "solar_azimuth": "solar_azimuth", "solar_elevation": "solar_elevation",
    "solar_zenith": "solar_zenith", "solar_raw": "solar_raw", "pressure": "pressure",
    "direct_normal_extra": "extraterrestrial_direct_normal",
    "global_horizontal_extra": "extraterrestrial_global_horizontal", "wind_dir": "wind_dir",
    "opq_sky_cov": "opq_sky_cov"}
"""Property that each TMY value sets (`temp_raw` and `tot_sky_cov` are
not published)"""

QUADRATIC_CLIP = {"humidity": "humidity", "solar_direct": "solar_direct", "solar_diffuse": "solar_diffuse",
    "solar_global": "solar_global", "wind_speed": "wind_speed", "rainfall": "rainfall",
    "snowdepth": "snowdepth", "solar_raw": "solar_raw", "pressure": "pressure",
    "extraterrestrial_direct_normal": "extraterrestrial_direct_normal",
    "extraterrestrial_global_horizontal": "global_horizontal_extra",
    "tot_sky_cov": "tot_sky_cov", "opq_sky_cov": "opq_sky_cov"}
"""Values that quadratic interpolation clips at 0, with the name in the
verbose message"""

def _out(description:str, default:str|None=None) -> dict[str,Any]:
    options: dict[str,Any] = {"flags": "OUTPUT", "description": description}
    if default is not None:
        options["default"] = default
    return options

class ClimateState: # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """State that gridlabd keeps in unpublished `climate` members"""

    def __init__(self):
        self.reader_type = RT_NONE
        self.reader: str|None = None
        self.file = TmyReader()
        self.tmy: list[dict[str,Any]]|None = None
        self.is_tmy2 = False
        self.tz_meridian = 0.0
        self.tz_offset_val = 0.0
        self.temperature_raw = 15.0
        self.tot_sky_cov = 0.0
        self.prev_ntime = TS_NEVER
        self.global_transmissivity = 1.0
        self.pattern: CloudPattern|None = None

def state(model:Any, name:str) -> ClimateState:
    """State of a climate object (created when first asked for)"""
    found = get_state(model, name)
    if found is None:
        found = ClimateState()
        set_state(model, name, found)
    return found

class Climate:
    """Class `climate`; see the module documentation"""

    NAME = "climate"
    """gridlabd class name"""

    PASSCONFIG = "PRETOPDOWN|AUTOLOCK"
    """Pass configuration (gridlabd `PC_PRETOPDOWN|PC_AUTOLOCK`)"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = (
        ("solar_elevation[rad]", "double", _out("solar elevation angle in radians")),
        ("solar_azimuth[rad]", "double", _out("solar azimuth angle in radians")),
        ("solar_zenith[rad]", "double", _out("solar zenith angle in radians")),
        ("city", "char256", {"description": "weather data city name"}),
        ("tmyfile", "char1024", {"flags": "REQUIRED", "description": "weather data file name"}),
        ("temperature[degF]", "double", _out("current temperature", "59.0 degF")),
        ("humidity[pu]", "double", _out("current humidity", "75%")),
        ("solar_flux[W/sf]", "double", _out("current solar irradiance (9 orientiations)")),
        ("solar_direct[W/sf]", "double", _out("solar direct irradiance")),
        ("solar_diffuse[W/sf]", "double", _out("solar diffuse irradiance")),
        ("solar_global[W/sf]", "double", _out("solar global flux irradiance")),
        ("extraterrestrial_global_horizontal[W/sf]", "double", _out("solar global extraterrestrial irradiance")),
        ("extraterrestrial_direct_normal[W/sf]", "double", _out("solar direct normal extraterrestrial irradiance", "1367 W/m^2")),
        ("pressure[mbar]", "double", _out("current air pressure", "1013.25 mbar")),
        ("wind_speed[m/s]", "double", _out("current wind speed")),
        ("wind_dir[rad]", "double", _out("current direction in radians")),
        ("wind_gust[m/s]", "double", _out("current wind gusts")),
        ("record.low[degF]", "double", _out("record low temperature observed")),
        ("record.low_day", "int32", _out("day of year for record low observation")),
        ("record.high[degF]", "double", _out("record high temperature observed")),
        ("record.high_day", "int32", _out("day of year for record high observation")),
        ("record.solar[W/sf]", "double", _out("record high solar irradiance observed")),
        ("rainfall[in/h]", "double", _out("rainfall observed")),
        ("snowdepth[in]", "double", _out("snow depth observed")),
        ("interpolate", "enumeration", {**_out("the interpolation mode used on the climate data", "NONE"), "keywords": INTERPOLATE}),
        ("solar_horiz", "double", _out("solar flux on horizontal surface")),
        ("solar_north", "double", _out("solar flux on north surface")),
        ("solar_northeast", "double", _out("solar flux on northeast surface")),
        ("solar_east", "double", _out("solar flux on east surface")),
        ("solar_southeast", "double", _out("solar flux on southeast surface")),
        ("solar_south", "double", _out("solar flux on south surface")),
        ("solar_southwest", "double", _out("solar flux on southwest surface")),
        ("solar_west", "double", _out("solar flux on west surface")),
        ("solar_northwest", "double", _out("solar flux on northwest surface")),
        ("solar_raw[W/sf]", "double", _out("raw solar flux")),
        ("ground_reflectivity[pu]", "double", _out("ground reflectivity observed", "0.3 pu")),
        ("reader", "object", {"description": "weather reader object"}),
        ("forecast", "char1024", {"description": "forecasting specifications"}),
        ("cloud_model", "enumeration", {**_out("the cloud model to use", "NONE"), "keywords": CLOUD_MODEL}),
        ("cloud_opacity[pu]", "double", _out("cloud opacity factor", "1.0 pu")),
        ("opq_sky_cov[pu]", "double", _out("cloud sky coverage factor")),
        ("cloud_speed_factor[pu]", "double", _out("cloud speed factor", "1.0 pu")),
        ("solar_cloud_direct[W/sf]", "double", _out("cloud direct irradiance")),
        ("solar_cloud_diffuse[W/sf]", "double", _out("cloud diffuse irradiance")),
        ("solar_cloud_global[W/sf]", "double", _out("cloud global irradiance")),
        ("cloud_alpha[pu]", "double", _out("cloud alpha", "400 pu")),
        ("cloud_num_layers[pu]", "double", _out("number of cloud layers", "40 pu")),
        ("cloud_aerosol_transmissivity[pu]", "double", _out("cloud aerosal transmissivity", "0.95 pu")),
        ("heat_index[degF]", "double", _out("heat index based on temperature and humidity")),
    )
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order"""

    @classmethod
    def register(cls, module:Any) -> Any:
        """Register the class for `module` with its properties, functions,
        and event handlers"""
        oclass = module.register_class(cls.NAME, passconfig=cls.PASSCONFIG)
        for name, ptype, options in cls.PROPERTIES:
            oclass.publish(name, ptype, **options)
        for name, call in FUNCTIONS.items():
            oclass.define_function(name, call)
        oclass.set_event("init", f"python:{MODULE}.init")
        oclass.set_event("presync", f"python:{MODULE}.presync")
        return oclass

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str) -> bool|int: # pylint: disable=too-many-return-statements,too-many-branches
        """Initialize an object; `False` fails, 2 defers"""
        st = state(model, name)
        st.reader_type = RT_NONE
        tmyfile = get_text(model, name, "tmyfile")
        if tmyfile == "":
            return True
        found = find_weather_file(model, tmyfile)
        if found is None:
            object_error(model, name, f"weather file '{tmyfile}' access failed")
            return False
        if get_keyword(model, name, "cloud_model") != CM_NONE:
            cls._init_cloud(model, name, st)
        if ".tmy2" in tmyfile or ".tmy" in tmyfile:
            st.reader_type = RT_TMY2
        elif ".csv" in tmyfile:
            st.reader_type = RT_CSV
        else:
            object_warning(model, name, "climate: unrecognized filetype, assuming TMY2")
        if st.reader_type == RT_CSV:
            return cls._init_csv(model, name, st, tmyfile)
        return cls._init_tmy(model, name, st, tmyfile, found)

    @classmethod
    def _init_cloud(cls, model:Any, name:str, st:ClimateState) -> None:
        obj = header_name(model, name)
        values = {}
        opacity = get_double(model, name, "cloud_opacity")
        if opacity > 1:
            object_warning(model, name, f"climate:{obj} - Cloud opacity must be no greater than 1.0, setting to 1.0")
            values["cloud_opacity"] = 1.0
        elif opacity < 0:
            object_warning(model, name, f"climate:{obj} - Cloud opacity must be no less than 0.0, setting to 0.0")
            values["cloud_opacity"] = 0.0
        if get_double(model, name, "cloud_speed_factor") < 0:
            object_warning(model, name, f"climate:{obj} - Cloud speed adjustment cannot be negative, setting to 1.0")
            values["cloud_speed_factor"] = 1.0
        layers = get_double(model, name, "cloud_num_layers")
        if get_double(model, name, "cloud_alpha") < layers:
            object_warning(model, name, f"climate:{obj} - Cloud model alpha value must be less than or equal to cloud_num_layers, setting to cloud_num_layers")
            values["cloud_alpha"] = layers
        aerosol = get_double(model, name, "cloud_aerosol_transmissivity")
        if aerosol < 0:
            object_warning(model, name, f"climate:{obj} - Cloud model aerosol transmissivity must be greater than or equal to 0, setting to default value of 0.9")
            values["cloud_aerosol_transmissivity"] = 0.9
        if aerosol > 1:
            object_warning(model, name, f"climate:{obj} - Cloud model aerosol transmissivity must be less than or equal to 1, setting to 1")
            values["cloud_aerosol_transmissivity"] = 1.0
        store(model, name, values)
        object_warning(model, name, "This cloud model places a large burden on computational resources. Patience and/or a more capable computer may be required.")
        st.pattern = CloudPattern(solar_locations(model), object_rng(model, name))
        st.pattern.convert_to_binary_cloud(get_double(model, name, "opq_sky_cov"))
        st.pattern.convert_to_fuzzy_cloud(EMPTY_VALUE, int(get_double(model, name, "cloud_num_layers")),
            get_double(model, name, "cloud_alpha"))
        st.prev_ntime = model.globals.getvalue("clock") - 60

    @classmethod
    def _check_location(cls, model:Any, name:str) -> bool:
        obj = header_name(model, name)
        latitude = get_double(model, name, "latitude")
        longitude = get_double(model, name, "longitude")
        if abs(latitude) > 90:
            object_error(model, name, f"climate:{obj} - Latitude is outside +/-90!")
            return False
        if abs(longitude) > 180:
            object_error(model, name, f"climate:{obj} - Longitude is outside +/-180!")
            return False
        if latitude < 0:
            object_warning(model, name, f"climate:{obj} - Southern hemisphere solar position model may have issues")
        return True

    @classmethod
    def _init_csv(cls, model:Any, name:str, st:ClimateState, tmyfile:str) -> bool|int:
        reader = get_text(model, name, "reader")
        if reader == "":
            object_error(model, name, f"climate::init(): no csv_reader specified for tmyfile {tmyfile}")
            return False
        robj = model.objects.get(reader)
        if robj is None or robj.oclass.name != CsvReader.NAME:
            object_error(model, name, f"climate::init(): reader '{reader}' is not a csv_reader object")
            return False
        if not CsvReader.is_initialized(model, reader):
            object_verbose(model, name, f"climate::init(): deferring initialization on {reader}")
            return 2
        st.reader = reader
        result = CsvReader.open(model, reader, get_text(model, reader, "filename"))
        st.tz_offset_val = CsvReader.timezone_offset(model, reader)
        store(model, name, {
            "latitude": get_double(model, reader, "latitude"),
            "longitude": get_double(model, reader, "longitude"),
        })
        if not cls._check_location(model, name):
            return False
        st.tz_meridian = 15 * st.tz_offset_val
        return bool(result)

    @classmethod
    def _init_tmy(cls, model:Any, name:str, st:ClimateState, tmyfile:str, found:str) -> bool: # pylint: disable=too-many-locals
        file = st.file
        if file.open(found) < 3:
            object_error(model, name, "climate::init() -- weather file header improperly formed")
            return False
        st.is_tmy2 = file.is_tmy2
        _, _, lat_deg, lat_min, long_deg, long_min = file.header_info()
        latitude = lat_deg - lat_min/60 if lat_deg < 0 else lat_deg + lat_min/60
        longitude = long_deg - long_min/60 if long_deg < 0 else long_deg + long_min/60
        store(model, name, {"latitude": float(latitude), "longitude": float(longitude)})
        if not cls._check_location(model, name):
            return False
        st.tz_meridian = 15 * file.tz_offset
        st.tz_offset_val = float(file.tz_offset)
        tmy, record, line, events = _read_records(file, found, tmyfile, latitude, longitude, st.tz_meridian)
        for kind, text in events:
            if kind == "error":
                gl_error(text)
            else:
                object_warning(model, name, text)
        st.tmy = tmy
        store(model, name, {"record.low": record["low"], "record.low_day": record["low_day"],
            "record.high": record["high"], "record.high_day": record["high_day"],
            "record.solar": record["solar"]})
        if line < HOURS:
            object_error(model, name, f"{tmyfile}({line}): unable to read a full year of data")
        if ".tmy2" in tmyfile:
            object_warning(model, name, "TMY2 files exhibit unpredictable behavior, please use TMY3 file format.")
        cls.presync(model, name, model.globals.getvalue("clock"))
        return True

    #
    # Presync
    #
    @classmethod
    def presync(cls, model:Any, name:str, t0:int) -> int: # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """Update the weather at `t0`; returns the time of the next event"""
        st = state(model, name)
        csv_rv = tmy_rv = cloud_rv = 0
        values: dict[str,Any] = {}
        def member(key:str) -> float:
            if key in values:
                return values[key]
            return get_double(model, name, key)
        if t0 > TS_ZERO and st.reader_type == RT_CSV and st.reader is not None:
            csv_rv, sample = CsvReader.get_data(model, st.reader, t0)
            if sample is not None:
                values.update({
                    "temperature": sample["temperature"], "humidity": sample["humidity"],
                    "solar_direct": sample["solar_direct"], "solar_diffuse": sample["solar_diffuse"],
                    "solar_global": sample["solar_global"],
                    "extraterrestrial_global_horizontal": sample["global_horizontal_extra"],
                    "wind_speed": sample["wind_speed"], "wind_dir": sample["wind_dir"],
                    "opq_sky_cov": sample["opq_sky_cov"], "rainfall": sample["rainfall"],
                    "snowdepth": sample["snowdepth"], "pressure": sample["pressure"],
                })
                st.tot_sky_cov = sample["tot_sky_cov"]
            now = local_datetime(model, t0)
            if now is None:
                raise ClimateError("climate::sync -- unable to resolve localtime!")
            rlat = rad(get_double(model, st.reader, "latitude"))
            rlon = rad(get_double(model, st.reader, "longitude"))
            sol_time = SolarAngles.solar_time(now.hour + now.minute/60.0 + now.second/3600.0 + (-1 if now.is_dst else 0),
                now.yearday, rad(st.tz_meridian), rlon)
            values["solar_zenith"] = SolarAngles.zenith(SolarAngles.day_of_yr(now.month, now.day), rlat, sol_time)
            direct, diffuse = member("solar_direct"), member("solar_diffuse")
            for point in range(CP_LAST):
                if point == CP_H:
                    sol_rad = st.file.calc_solar(CP_E, now.yearday, rlat, sol_time, direct, diffuse, 0.0)
                else:
                    sol_rad = st.file.calc_solar(point, now.yearday, rlat, sol_time, direct, diffuse)
                values[FLUX[point]] = sol_rad
            values["solar_flux"] = values[FLUX[CP_H]]
        if t0 > TS_ZERO and st.tmy is not None:
            ts = local_datetime(model, t0)
            if ts is None:
                raise ClimateError("climate::sync -- unable to resolve localtime!")
            hoy = (SolarAngles.day_of_yr(ts.month, ts.day) - 1) * 24 + ts.hour
            if not st.is_tmy2:
                hoy -= 2 if ts.is_dst else 1
            if hoy < 0:
                hoy += HOURS
            cls._interpolate(model, name, st, values, hoy, ts.minute)
            temperature = values["temperature"]
            values["heat_index"] = heat_index(temperature, values["humidity"])
            tmy_rv = -(t0 + (3600 - t0 % 3600))
        cloud_model = get_keyword(model, name, "cloud_model")
        if cloud_model == CM_CUMULUS:
            if st.prev_ntime != t0:
                p = member("pressure")*0.1
                zenith = member("solar_zenith")
                m = 0.02857*math.sqrt((1224. * math.cos(zenith) * math.cos(zenith)) + 1.)
                aw = 0.077*(4.5/m)**0.3
                pa = get_double(model, name, "cloud_aerosol_transmissivity")
                prpa = 1.041-(0.15*math.sqrt(((p*0.00949)+0.051)/m))
                st.global_transmissivity = max(0.0, (prpa-aw)*pa)
                if st.pattern is not None:
                    st.pattern.update(t0 - st.prev_ntime,
                        member("wind_speed") * get_double(model, name, "cloud_speed_factor"),
                        member("wind_dir"), zenith, member("opq_sky_cov"),
                        int(get_double(model, name, "cloud_num_layers")), get_double(model, name, "cloud_alpha"))
                st.prev_ntime = t0
            cloud_rv = t0 + 60
        store(model, name, values)
        if t0 <= TS_ZERO:
            return TS_NEVER
        if cloud_model == CM_NONE:
            if st.reader_type == RT_CSV:
                return csv_rv
            return tmy_rv if st.tmy is not None else TS_NEVER
        if st.reader_type == RT_CSV:
            return cloud_rv if cloud_rv <= abs(csv_rv) else csv_rv
        return cloud_rv if cloud_rv <= abs(tmy_rv) else tmy_rv

    @classmethod
    def _interpolate(cls, model:Any, name:str, st:ClimateState, values:dict[str,Any], hoy:int, minute:int) -> None: # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches
        tmy = st.tmy
        assert tmy is not None
        mode = get_keyword(model, name, "interpolate")
        rec0, rec1, rec2 = tmy[hoy], tmy[(hoy+1) % HOURS], tmy[(hoy+2) % HOURS]
        now, hoy0, hoy1, hoy2 = hoy + minute/60.0, float(hoy), hoy + 1.0, hoy + 2.0
        result: dict[str,float] = {}
        if mode == CI_NONE:
            result = {key: rec0[key] for key in TMY_FIELDS}
            flux = list(rec0["solar"])
        elif mode == CI_LINEAR:
            result = {key: lerp(now, hoy0, rec0[key], hoy1, rec1[key]) for key in TMY_FIELDS}
            flux = [lerp(now, hoy0, rec0["solar"][pt], hoy1, rec1["solar"][pt]) for pt in range(CP_LAST)]
        elif mode == CI_QUADRATIC:
            for key in TMY_FIELDS:
                result[key] = qerp(now, hoy0, rec0[key], hoy1, rec1[key], hoy2, rec2[key])
                prop = PROPERTY_OF.get(key, key)
                if prop in QUADRATIC_CLIP and result[key] < 0.0:
                    result[key] = 0.0
                    label = QUADRATIC_CLIP[prop]
                    object_verbose(model, name, f"Setting {label} to zero. Quadratic interpolation caused the {label} to drop below zero.")
                if key == "wind_dir":
                    if result[key] < 0.0:
                        result[key] = 360.0 + result[key]
                        object_verbose(model, name, "Setting wind_dir to 360+wind_dir. Quadratic interpolation caused the wind_dir to drop below zero.")
                    if result[key] > 360.0:
                        result[key] = result[key] - 360.0
                        object_verbose(model, name, "Setting wind_dir to wind_dir-360. Quadratic interpolation caused the wind_dir to rise above 360.")
            flux = []
            for pt in range(CP_LAST):
                if rec0["solar"][pt] == rec1["solar"][pt]:
                    flux.append(rec0["solar"][pt])
                else:
                    value = qerp(now, hoy0, rec0["solar"][pt], hoy1, rec1["solar"][pt], hoy2, rec2["solar"][pt])
                    flux.append(0.0 if value < 0.0 else value)
        else:
            raise ClimateError("climate::sync -- unrecognized interpolation mode!")
        st.temperature_raw = result["temp_raw"]
        st.tot_sky_cov = result["tot_sky_cov"]
        for key, prop in PROPERTY_OF.items():
            values[prop] = result[key]
        for point in range(CP_LAST):
            values[FLUX[point]] = flux[point]
        values["solar_flux"] = flux[CP_H]

    #
    # Solar radiation for a location
    #
    @classmethod
    def get_solar_for_location(cls, model:Any, name:str, latitude:float, longitude:float) -> tuple[float,float,float]:
        """Direct, global, and diffuse irradiance at a location (gridlabd
        `climate::get_solar_for_location()`); with the cloud model, the
        direct irradiance is dimmed by the cloud value of the location
        and `solar_cloud_*` are set

        Exceptions
        ----------
        - `ClimateError`: the cloud model is on and the object has no
          cloud pattern, or the location is outside it
        """
        if get_keyword(model, name, "cloud_model") == CM_CUMULUS:
            st = state(model, name)
            if st.pattern is None:
                raise ClimateError(f"climate {name} has no cloud pattern")
            cloud = st.pattern.fuzzy_value(latitude, longitude)
            f = 1 - (cloud * get_double(model, name, "cloud_opacity"))
            sol_z = get_double(model, name, "solar_zenith")
            etrn = get_double(model, name, "extraterrestrial_direct_normal")
            direct = 0.0 if sol_z > rad(90) else f*st.global_transmissivity*etrn
            diffuse = get_double(model, name, "solar_diffuse")
            glob = max(direct*max(math.cos(sol_z), 0.0) + diffuse, 0.0)
            store(model, name, {"solar_cloud_direct": direct, "solar_cloud_diffuse": diffuse,
                "solar_cloud_global": glob})
            return direct, glob, diffuse
        return (get_double(model, name, "solar_direct"), get_double(model, name, "solar_global"),
            get_double(model, name, "solar_diffuse"))

_RECORDS: dict[tuple,tuple] = {}
"""TMY records already read, keyed on the file and what the records depend on"""

RECORDS_CACHED = 2
"""Most TMY files whose records are kept"""

def _read_records(file:TmyReader, found:str, tmyfile:str, latitude:float, longitude:float, # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        tz_meridian:float) -> tuple[list[dict[str,Any]],dict[str,Any],int,list[tuple[str,str]]]:
    """Records of an open TMY file (gridlabd's loop in `climate::init()`):
    the 8760 hourly records, the records of extremes, the number of lines
    read, and the messages to write (`("error", text)` for `gl_error()`,
    `("warning", text)` for the object's warnings)

    The result depends only on the file and the unit manager, so the last
    files read are kept and read again only when they change."""
    try:
        info = os.stat(found)
        key: tuple|None = (os.path.realpath(found), info.st_mtime_ns, info.st_size, tmyfile,
            latitude, longitude, tz_meridian, id(Class.get_units()))
    except OSError:
        key = None
    if key is not None and key in _RECORDS:
        file.close()
        return _RECORDS[key]
    convert = Class.get_units().convert
    events: list[tuple[str,str]] = []
    file.report_error = lambda text: events.append(("error", text))
    lat = rad(latitude)
    tmy: list[dict[str,Any]] = [{} for _ in range(HOURS)]
    record = {"low": 0.0, "low_day": 0, "high": 0.0, "high_day": 0, "solar": 0.0}
    line = 0
    ended = False
    while line < HOURS and file.next():
        while not file.buf[1:2].isdigit():
            if not file.next():
                ended = True
                break
        if ended:
            break
        rec = file.read_data()
        doy = SolarAngles.day_of_yr(rec.month, rec.day) if 1 <= rec.month <= 12 else 0
        hoy = (doy - 1) * 24 + (rec.hour - 1)
        if 0 <= hoy < HOURS:
            dnr = convert(rec.dnr, "W/m^2", "W/sf")
            dhr = convert(rec.dhr, "W/m^2", "W/sf")
            temp = convert(rec.tdb, "degC", "degF")
            sol_time = SolarAngles.solar_time(float(rec.hour), doy, rad(tz_meridian), rad(longitude))
            elevation = SolarAngles.altitude(doy, lat, sol_time)
            item = {
                "temp_raw": rec.tdb, "temp": temp, "windspeed": rec.wind, "rh": rec.rh,
                "dnr": dnr, "dhr": dhr, "ghr": convert(rec.ghr, "W/m^2", "W/sf"), "rainfall": rec.precip,
                "snowdepth": rec.snow_depth, "solar_raw": dnr,
                "direct_normal_extra": convert(rec.extra_terr_dni, "W/m^2", "W/sf"),
                "pressure": rec.pressure, "global_horizontal_extra": convert(rec.extra_terr_ghi, "W/m^2", "W/sf"),
                "wind_dir": rec.winddir, "tot_sky_cov": rec.tot_sky_cov,
                "opq_sky_cov": rec.opq_sky_cov, "solar_elevation": elevation,
                "solar_azimuth": SolarAngles.azimuth(doy, lat, sol_time),
                "solar_zenith": (90. * PI_OVER_180) - elevation,
            }
            solar = []
            for point in range(CP_LAST):
                if point == CP_H:
                    sol_rad = file.calc_solar(CP_E, doy, lat, sol_time, dnr, dhr, 0.0)
                else:
                    sol_rad = file.calc_solar(point, doy, lat, sol_time, dnr, dhr)
                solar.append(sol_rad)
                if sol_rad > record["solar"] or record["solar"] == 0:
                    record["solar"] = sol_rad
                if temp > record["high"] or record["high"] == 0:
                    record["high"], record["high_day"] = temp, doy
                if temp < record["low"] or record["low"] == 0:
                    record["low"], record["low_day"] = temp, doy
            item["solar"] = solar
            tmy[hoy] = item
        else:
            events.append(("warning", f"{tmyfile}({line}): hour {hoy} is out of allowed range 0-8759 hours (month={rec.month}, day={rec.day}, hour={rec.hour})"))
        line += 1
    file.close()
    file.report_error = gl_error
    for item in tmy:
        if not item:
            item.update({key_: 0.0 for key_ in TMY_FIELDS}, solar=[0.0]*CP_LAST)
    result = (tmy, record, line, events)
    if key is not None:
        while len(_RECORDS) >= RECORDS_CACHED:
            del _RECORDS[next(iter(_RECORDS))]
        _RECORDS[key] = result
    return result

def heat_index(temperature:float, humidity:float) -> float:
    """Heat index (degF) of a temperature (degF) and relative humidity
    (fraction), as gridlabd's `climate::update_heatindex()` computes it"""
    t = temperature
    rh = humidity * 100
    if t < 80:
        return 0.75*t + 0.25*(61.0+1.2*(t-68.0)+0.094*rh)
    result = (-42.379 + 2.04901523*t + 10.14333127*rh - 0.22475541*t*rh - 0.00683783*t*t
        - 0.05481717*rh*rh + 0.00122874*t*t*rh + 0.00085282*t*rh*rh - 0.00000199*t*t*rh*rh)
    if rh < 13 and t < 112:
        result -= ((13-rh)/4)*math.sqrt((17-abs(t-95.))/17)
    elif rh > 85 and t < 87:
        result += ((rh-85)/10) * ((87-t)/5)
    return result

def find_weather_file(model:Any, name:str) -> str|None:
    """Path of a weather file: the name as given, then in the folders of
    `climate::library_path`, then with `arras.folders.findfile()`; `None`
    when it is not found"""
    if os.access(name, os.R_OK) and os.path.isfile(name):
        return name
    path = model.globals.get(f"{MODULE}::library_path") if model.globals.isdefined(f"{MODULE}::library_path") else ""
    for folder in (x for x in str(path or "").replace(";", ":").split(":") if x):
        candidate = os.path.join(folder, name)
        if os.access(candidate, os.R_OK) and os.path.isfile(candidate):
            return candidate
    return arras.folders.findfile(name)

def solar_flux(model:Any, name:str) -> list[float]:
    """The nine values of `solar_flux` (W/sf), in compass point order:
    horizontal, north, northeast, east, southeast, south, southwest, west,
    northwest"""
    return [get_double(model, name, prop) for prop in FLUX]

#
# Published functions
#
def _climate(model:Any, name:str) -> bool:
    obj = model.objects.get(name) if hasattr(model, "objects") else None
    return obj is not None and obj.oclass.name == Climate.NAME and obj.oclass.module == MODULE

def _clock(model:Any, name:str) -> int:
    """Clock of a climate object: the clock of the running simulation (the
    object has synchronized at that time, and gridlabd sets an object's
    clock when it synchronizes, `arras` at the commit), else the object's
    `clock`"""
    from arras.runner import Runner # pylint: disable=import-outside-toplevel
    current = Runner.current()
    if current is not None and current.model is model and current.clock is not None:
        return current.clock
    text = model.get_property(name, "clock")
    if text in (None, ""):
        return model.globals.getvalue("clock")
    return to_timestamp(model, text)

def calculate_solar_radiation_degrees(model:Any, name:str, tilt:float, orientation:float) -> float|None:
    """`calculate_solar_radiation_degrees()`: angles in degrees, no shading"""
    return calculate_solar_radiation_shading_radians(model, name, rad(tilt), rad(orientation), 1.0)

def calculate_solar_radiation_radians(model:Any, name:str, tilt:float, orientation:float) -> float|None:
    """`calculate_solar_radiation_radians()`: no shading"""
    return calculate_solar_radiation_shading_radians(model, name, tilt, orientation, 1.0)

def calculate_solar_radiation_shading_degrees(model:Any, name:str, tilt:float, orientation:float, shading_value:float) -> float|None:
    """`calculate_solar_radiation_shading_degrees()`: angles in degrees"""
    return calculate_solar_radiation_shading_radians(model, name, rad(tilt), rad(orientation), shading_value)

def calculate_solar_radiation_shading_radians(model:Any, name:str, tilt:float, orientation:float, shading_value:float) -> float|None:
    """`calculate_solar_radiation_shading_radians()`: no location"""
    return calculate_solar_radiation_shading_position_radians(model, name, tilt, orientation, math.nan, math.nan, shading_value)

def calculate_solar_radiation_shading_position_radians(model:Any, name:str, tilt:float, orientation:float, # pylint: disable=too-many-arguments,too-many-positional-arguments
        latitude:float, longitude:float, shading_value:float) -> float|None:
    """`calculate_solar_radiation_shading_position_radians()`: irradiance
    on a surface (W/sf) with the Duffie and Beckman solar position"""
    if not _climate(model, name):
        return None
    dnr, ghr, dhr = Climate.get_solar_for_location(model, name, latitude, longitude)
    dt = local_datetime(model, _clock(model, name))
    if dt is None:
        raise ClimateError(f"climate {name}: clock cannot be converted to local time")
    std_time = float(dt.hour) + float(dt.minute)/60.0 + (-1.0 if dt.is_dst else 0.0)
    doy = SolarAngles.day_of_yr(dt.month, dt.day)
    st = state(model, name)
    solar_time = SolarAngles.solar_time(std_time, doy, rad(st.tz_meridian), rad(get_double(model, name, "longitude")))
    cos_incident = SolarAngles.cos_incident(rad(get_double(model, name, "latitude")), tilt, orientation, solar_time, doy)
    reflectivity = get_double(model, name, "ground_reflectivity")
    return (shading_value*dnr*cos_incident) + dhr*(1+math.cos(tilt))/2. + ghr*(1-math.cos(tilt))*reflectivity/2.

def calc_solar_solpos_shading_deg(model:Any, name:str, tilt:float, orientation:float, shading_value:float) -> float|None:
    """`calc_solar_solpos_shading_deg()`: angles in degrees"""
    return calc_solar_solpos_shading_rad(model, name, rad(tilt), rad(orientation), shading_value)

def calc_solar_solpos_shading_rad(model:Any, name:str, tilt:float, orientation:float, shading_value:float) -> float|None:
    """`calc_solar_solpos_shading_rad()`: no location"""
    return calc_solar_solpos_shading_position_rad(model, name, tilt, orientation, math.nan, math.nan, shading_value)

def calc_solar_solpos_shading_position_rad(model:Any, name:str, tilt:float, orientation:float, # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        latitude:float, longitude:float, shading_value:float) -> float|None:
    """`calc_solar_solpos_shading_position_rad()` (published as
    `calculate_solpos_radiation_shading_position_radians`): irradiance on
    a surface (W/sf) with SOLPOS and the Perez diffuse tilt model"""
    if not _climate(model, name):
        return None
    dnr, ghr, dhr = Climate.get_solar_for_location(model, name, latitude, longitude)
    st = state(model, name)
    clock = _clock(model, name)
    offsetclock = clock + 1800 if st.reader_type == RT_TMY2 else clock
    dt = local_datetime(model, offsetclock)
    if dt is None:
        raise ClimateError(f"climate {name}: clock cannot be converted to local time")
    pdat = SolposData()
    SolarAngles.S_init(pdat)
    pdat.longitude = get_double(model, name, "longitude")
    pdat.latitude = rad(get_double(model, name, "latitude"))
    pdat.timezone = st.tz_offset_val - 1.0 if dt.is_dst else st.tz_offset_val
    pdat.year = dt.year
    pdat.daynum = dt.yearday + 1
    pdat.hour = dt.hour + (-1 if dt.is_dst else 0)
    pdat.minute = dt.minute
    pdat.second = dt.second
    pdat.temp = (get_double(model, name, "temperature") - 32.0)*5.0/9.0
    pdat.press = get_double(model, name, "pressure")
    pdat.solcon = get_double(model, name, "extraterrestrial_direct_normal")
    pdat.aspect = orientation
    pdat.tilt = tilt
    pdat.diff_horz = dhr
    pdat.dir_norm = dnr
    SolarAngles.S_solpos(pdat)
    cos_incident = pdat.cosinc if pdat.cosinc >= 0.0 else 0.0
    reflectivity = get_double(model, name, "ground_reflectivity")
    return (shading_value*dnr*cos_incident) + dhr*pdat.perez_horz + ghr*((1-math.cos(tilt))*reflectivity/2.0)

def calc_solar_ideal_shading_position_radians(model:Any, name:str, tilt:float, latitude:float, # pylint: disable=too-many-arguments,too-many-positional-arguments
        longitude:float, shading_value:float) -> float|None:
    """`calc_solar_ideal_shading_position_radians()`: irradiance on a
    surface that faces the sun (W/sf)"""
    if not _climate(model, name):
        return None
    dnr, ghr, dhr = Climate.get_solar_for_location(model, name, latitude, longitude)
    return shading_value*dnr + dhr + ghr*(1-math.cos(tilt))*get_double(model, name, "ground_reflectivity")/2.0

FUNCTIONS = {
    "calculate_solar_radiation_degrees": calculate_solar_radiation_degrees,
    "calculate_solar_radiation_radians": calculate_solar_radiation_radians,
    "calculate_solar_radiation_shading_degrees": calculate_solar_radiation_shading_degrees,
    "calculate_solar_radiation_shading_radians": calculate_solar_radiation_shading_radians,
    "calculate_solar_radiation_shading_position_radians": calculate_solar_radiation_shading_position_radians,
    "calculate_solpos_radiation_shading_position_radians": calc_solar_solpos_shading_position_rad,
    "calc_solar_ideal_shading_position_radians": calc_solar_ideal_shading_position_radians,
}
"""Class functions of `climate`, in gridlabd's publication order"""
