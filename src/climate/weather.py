# pylint: disable=line-too-long
# (the markdown tables in the docstring are kept one row per line)
"""Weather samples (class `weather`)

A `weather` object holds one weather sample. gridlabd gives the objects
no behavior: the class is the list of the columns that a `csv_reader`
file may have, and each line of such a file is read into a sample with
these properties.

Syntax
------

    module climate;
    object weather {
        temperature <decimal> degF;
        humidity <decimal> %;
        solar_direct <decimal> W/sf;
        solar_diffuse <decimal> W/sf;
        solar_global <decimal> W/sf;
        global_horizontal_extra <decimal> W/sf;
        wind_speed <decimal> mph;
        wind_dir <decimal> deg;
        opq_sky_cov <decimal> pu;
        tot_sky_cov <decimal> pu;
        rainfall <decimal> in/h;
        snowdepth <decimal> in;
        pressure <decimal> mbar;
        month <integer>;
        day <integer>;
        hour <integer>;
        minute <integer>;
        second <integer>;
    }

Properties
----------

| Property | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `temperature` | `double[degF]` | `0.0 degF` | dry-bulb air temperature |
| `humidity` | `double[%]` | `0%` | relative humidity |
| `solar_direct` | `double[W/sf]` | `0.0 W/sf` | direct solar flux |
| `solar_diffuse` | `double[W/sf]` | `0.0 W/sf` | diffuse solar flux |
| `solar_global` | `double[W/sf]` | `0.0 W/sf` | global solar flux |
| `global_horizontal_extra` | `double[W/sf]` | `0.0 W/sf` | horizontal surface solar flux |
| `wind_speed` | `double[mph]` | `0.0 mph` | wind speed |
| `wind_dir` | `double[deg]` | `0.0 deg` | wind direction |
| `opq_sky_cov` | `double[pu]` | `0.0 pu` | opaque sky cover |
| `tot_sky_cov` | `double[pu]` | `0.0 pu` | total sky cover |
| `rainfall` | `double[in/h]` | `0.0 in/h` | rainfall rate |
| `snowdepth` | `double[in]` | `0.0 in` | depth of snow on the ground |
| `pressure` | `double[mbar]` | `0.0 mbar` | air pressure |
| `month`, `day`, `hour`, `minute`, `second` | `int16` | `0` | time of the sample |

All are output properties except `solar_direct`.

Description
-----------

The class is expected to satisfy:

1. It is registered with no synchronization passes (`NOSYNC`) and
   technology readiness level 2 (`TRL_CONCEPT`), with the properties
   above in this order.
2. Its objects have no event handlers.
3. A `csv_reader` column is named by one of these properties; only the
   `double` properties are read from the file.

Examples
--------

    >>> from arras import Model, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm("module climate; object weather { name w; wind_speed 10 m/s; }\\n")
    >>> m.get_property("w", "wind_speed")
    '22.369362920544 mph'
    >>> Class.reset()

Caveats
-------

- gridlabd's documentation of the class (`docs/Module/Climate/Weather.md`)
  also lists `solar_dir` and `solar_diff`, which the code does not publish.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/climate/weather.cpp`, `weather.h`
- [Weather class](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Climate/Weather.md)
  (`docs/Module/Climate/Weather.md`)
"""

from typing import Any

from ._common import TRL_CONCEPT

def _out(description:str, default:str|None=None) -> dict[str,Any]:
    options: dict[str,Any] = {"flags": "OUTPUT", "description": description}
    if default is not None:
        options["default"] = default
    return options

class Weather:
    """Class `weather`; see the module documentation"""

    NAME = "weather"
    """gridlabd class name"""

    PASSCONFIG = "NOSYNC"
    """Pass configuration (gridlabd `PC_NOSYNC`)"""

    TRL = TRL_CONCEPT
    """Technology readiness level"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = (
        ("temperature[degF]", "double", _out("dry-bulb air temperature", "0.0 degF")),
        ("humidity[%]", "double", _out("relative humidity", "0%")),
        ("solar_direct[W/sf]", "double", {"description": "direct solar flux", "default": "0.0 W/sf"}),
        ("solar_diffuse[W/sf]", "double", _out("diffuse solar flux", "0.0 W/sf")),
        ("solar_global[W/sf]", "double", _out("global solar flux", "0.0 W/sf")),
        ("global_horizontal_extra[W/sf]", "double", _out("horizontal surface solar flux", "0.0 W/sf")),
        ("wind_speed[mph]", "double", _out("wind speed", "0.0 mph")),
        ("wind_dir[deg]", "double", _out("wind direction", "0.0 deg")),
        ("opq_sky_cov[pu]", "double", _out("opaque sky cover", "0.0 pu")),
        ("tot_sky_cov[pu]", "double", _out("total sky cover", "0.0 pu")),
        ("rainfall[in/h]", "double", _out("rainfall rate", "0.0 in/h")),
        ("snowdepth[in]", "double", _out("depth of snow on the ground", "0.0 in")),
        ("pressure[mbar]", "double", _out("air pressure", "0.0 mbar")),
        ("month", "int16", _out("current month")),
        ("day", "int16", _out("current day")),
        ("hour", "int16", _out("current hour")),
        ("minute", "int16", _out("current minute")),
        ("second", "int16", _out("current second")),
    )
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order"""

    @classmethod
    def register(cls, module:Any) -> Any:
        """Register the class for `module` (an `arras.module.Module`)"""
        oclass = module.register_class(cls.NAME, passconfig=cls.PASSCONFIG)
        oclass.trl = cls.TRL
        for name, ptype, options in cls.PROPERTIES:
            oclass.publish(name, ptype, **options)
        return oclass

    @classmethod
    def columns(cls) -> dict[str,str]:
        """Property types keyed on property name (the `csv_reader`
        columns)"""
        return {name.split("[", maxsplit=1)[0]: ptype for name, ptype, _ in cls.PROPERTIES}

def new_sample() -> dict[str,Any]:
    """An empty sample (gridlabd `weather::weather()`): every value 0"""
    return {name: (0 if ptype == "int16" else 0.0) for name, ptype in Weather.columns().items()}
