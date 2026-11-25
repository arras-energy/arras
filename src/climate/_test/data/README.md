Test data
---------

Ported gridlabd autotests
-------------------------

The `test_*.glm` files are the autotests of gridlabd's `climate` module
(`arras-energy/gridlabd` master 076e78a, `module/climate/autotest/`), with
these changes:

| File | Changes |
| ---- | ------- |
| all | `module tape;` and `module residential { ... };` replaced by `#include "tape.glm"` and `#include "residential.glm"`, which declare the classes used as GLM classes without behavior (`arras` has no `tape` or `residential` module); time zones `PST+8PDT` and `HST+10` replaced by `America/Los_Angeles` and `Pacific/Honolulu` (#41) |
| `test_csvreader_dst.glm`, `test_csvreader_exercise_5_1_2.glm` | `timestamp` in the clock block replaced by `starttime` (`arras` reads only `starttime`); `../weather*.csv` replaced by `weather*.csv` (the tests run in this folder, gridlabd's in a subfolder) |
| `test_WA-Yakima-tmy3.glm` | `#weather get` commented out (the TMY3 file is in this folder); object name `Yakima WA` replaced by `Yakima_WA` (`arras` refuses spaces in names) |
| `test_cloud_tmy3_opt.glm` | the `powerflow` objects, the `inverter`, the `player` and its `double_assert` removed, and the `generators` `solar` class declared by `generators.glm` (its `Insolation` comes from the climate class functions, `climate_test_solar.insolation`); the asserted insolation came from gridlabd's random cloud pattern, which `arras` does not reproduce (see `climate.cloud`); the `phases CS` of the solar object removed (the gridlabd `solar` class has no `phases`, so the gridlabd test fails to load) |
| `test_singleHouseSolarInverter.glm` | only the climate object and the solar object kept, the solar object declared by `generators.glm`; the feeder, houses, and inverter need the `powerflow`, `residential`, and `generators` modules |
| `test_solar_opt.glm` | the climate object of the missing `../WA-Yakima.glm` replaced by one reading the Yakima TMY3 file; the intrinsic C++ functions of its `solar` class replaced by Python handlers (`climate_test_solar.opt_*`); `#set tmp`, `#setenv`, `#set force_compile`, and the recorder file name macros removed; the expected energies changed from 135.2 and 99.2 MWh (made with a TMY2 file that is not in gridlabd's repository) to 133.7 and 98.9 MWh, computed from the climate values that gridlabd gives for the TMY3 file |

The humidity column of `weather.csv` and `weather_dst.csv` holds fractions
(0.05 to 0.16), but `weather.humidity` is in %, so `arras` reads them as
0.05% to 0.16% (0.0005 to 0.0016 pu); gridlabd copies them as 0.05 to 0.16
pu (decision 9.9). The files are unchanged.

The players `cloud_insolation.player` and `cloud_insolation_tmy3.player`
are not copied, because their values come from gridlabd's random cloud
patterns.

Weather files
-------------

| File | Source | Size |
| ---- | ------ | ---- |
| `WA-Yakima_Air_Terminal.tmy3` | `arras-energy/gridlabd-weather`, `US/WA-Yakima_Air_Terminal.tmy3` (the file that `#weather get` downloads) | 1.7 MB |
| `weather.csv`, `weather_dst.csv` | `arras-energy/gridlabd`, `module/climate/autotest/` | under 1 kB |

Stand-in classes
----------------

- `tape.glm`: `recorder` and `multi_recorder` (no behavior)
- `residential.glm`: `house` (no behavior)
- `generators.glm`: `solar`, whose `on_sync` handler sets `Insolation` as
  the gridlabd `generators` `solar` object does

Reference values (`reference/`)
-------------------------------

Written by gridlabd (master 076e78a, built with Python 3.12, modules
`climate`, `tape`, `powerflow`, and `generators`):

- `make_reference.py`: the script that ran gridlabd and wrote the CSV files
  (`python3 make_reference.py GRIDLABD`); not run by the tests;
- `yakima_*.csv`, `csv_*.csv`, `solar_*.csv`: values written by gridlabd's
  recorders (see `make_reference.py` for each case);
- `modhelp.txt`, `modhelp.json`: `gridlabd --modhelp climate` and
  `gridlabd --modhelp=json climate`;
- `solar_angles.txt`: printed by `solar_angles_main.cpp` compiled with
  gridlabd's `module/climate/solar_angles.cpp` and `solar_angles.h`
  (`g++ solar_angles_main.cpp solar_angles.cpp`, with a `climate.h` that
  defines `PI` and includes `solar_angles.h`).
