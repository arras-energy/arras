# pylint: disable=line-too-long
"""Class `weather`: weather values for powerplants

Syntax
------

    object pypower.weather {
        file "<file>";
        variables "<property>[,...]";
        resolution <real> s;
        Sn <real> W/m^2;
        Sh <real> W/m^2;
        Sg <real> W/m^2;
        Wd <real> deg;
        Ws <real> m/s;
        Td <real> degC;
        Tw <real> degC;
        RH <real> %;
        PW <real> in;
        HI <real> degF;
    }

The module global `pypower::timestamp_format` is also published (not
used, as in gridlabd).

Description
-----------

A weather object holds weather values that powerplants use for derating
(`Td`). Its values may be set by other objects (e.g. a tape player) or
read from a CSV `file`, as a bus reads its `weather_file`: rows
`timestamp,v1,v2,...` (lines that do not start with a digit are skipped)
whose timestamps are a multiple of `resolution` are kept, and at each
precommit the values of the first row at or after the clock are copied to
the properties named in `variables`, with an event at the time of the
next row. A file that cannot be read, a variable that is not a property,
or a timestamp that is not valid or out of order fails the
initialization.

Caveats
-------

- File values are copied as they are, in the units of the properties.
- Empty fields are skipped (C `strtok()`), so the values after an empty
  field move to earlier columns, as in gridlabd.

References
----------

- `arras-energy/gridlabd`: `module/pypower/weather.cpp`, `weather.h`
"""

from typing import Any

from ._base import PypowerClass, prop, msg
from ._common import TS_NEVER, object_state, get_double, get_text
from ._module import ensure_init
from ._weather import WeatherData

class Weather(PypowerClass):
    """Behavior of class `weather`"""

    NAME = "weather"
    PROPERTIES = (
        ("file", "char1024", prop("Source object for weather data")),
        ("variables", "char1024", prop("Weather variable column names (col1,col2,...)")),
        ("resolution[s]", "double", prop("Weather time downsampling resolution (s)", "3600 s")),
        ("Sn[W/m^2]", "double", prop("Solar direct normal irradiance (W/m^2)")),
        ("Sh[W/m^2]", "double", prop("Solar horizontal irradiance (W/m^2)")),
        ("Sg[W/m^2]", "double", prop("Solar global irradiance (W/m^2)")),
        ("Wd[deg]", "double", prop("Wind direction (deg)")),
        ("Ws[m/s]", "double", prop("Wind speed (m/s)")),
        ("Td[degC]", "double", prop("Dry-bulb air temperature (degC)")),
        ("Tw[degC]", "double", prop("Wet-bulb air temperature (degC)")),
        ("RH[%]", "double", prop("Relative humidity (%)")),
        ("PW[in]", "double", prop("Precipitable_water (in)")),
        ("HI[degF]", "double", prop("Heat index (degF)")),
    )
    EVENTS = ("init", "precommit")

    @classmethod
    def state(cls, model:Any, name:str) -> WeatherData:
        """Weather records of the object"""
        return object_state(model, name, WeatherData)

    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool: # pylint: disable=unused-argument
        """`weather::init()`"""
        if not ensure_init(model):
            return False
        out = msg(model, name)
        file = get_text(model, name, "file")
        if file and not cls.state(model, name).load(model, name, file, get_text(model, name, "variables"),
                get_double(model, name, "resolution"), out):
            out.error(f"unable to load weather_file '{file}'")
            return False
        return True

    @classmethod
    def precommit(cls, model:Any, name:str, t:int) -> int:
        """`weather::precommit()`"""
        data = cls.state(model, name)
        data.get(model, name, t, msg(model, name))
        return data.next_time() if data.records else TS_NEVER
