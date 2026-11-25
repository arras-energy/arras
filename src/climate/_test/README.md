Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	pip install -e . pytest
	pytest src/climate/_test

The package must be installed (editable or not), because `Model` finds the
module through the `arras.modules` entry point in `pyproject.toml`. The
tests use no network and no credentials, and finish in about 15 seconds.
`conftest.py` clears `arras.oclass.Class.registry` and
`arras.module.Module.registry` before and after each test, and provides
helpers: `model()` and `run()` (GLM text after a clock and
`module climate;`), `add_ticker()` (an object that asks for an event at a
fixed interval, as a gridlabd recorder does), `sample()` (property values
at each committed time), `reference()` (a gridlabd reference file), and
`mismatches()` (values that differ from a reference by more than its 6
significant digits).

`climate_test_files.py` writes weather files that the tests and
`data/reference/make_reference.py` share (a TMY2 file made from the Yakima
TMY3 data, a year of CSV samples, a CSV file with `timefmt`).
`climate_test_solar.py` holds the event handlers that stand in for the
`solar` classes of the ported autotests.

The cloud model tests set `climate.cloud.TILE_SIZE` to 16, 32, or 64
pixels so that they run in seconds; gridlabd's tiles are 512 pixels.

test_climate_reference.py
-------------------------

`arras` against values that gridlabd wrote (`data/reference/`, made by
`make_reference.py` with a gridlabd build of master 076e78a): every
recorded value, within the 6 significant digits of gridlabd's recorders:

- TMY3 data with `interpolate NONE` (two weeks, hourly, across the start of
  daylight saving time), `LINEAR` (two days, every 15 minutes, across it),
  and `QUADRATIC` (two days, every 15 minutes, across its end); TMY2 data;
  28 climate properties each;
- CSV files: the two autotest files, the year file across the new year and
  across a leap day in another time zone, and the `timefmt` file with
  explicit `columns`; 23 properties each, with gridlabd's `humidity` and
  `wind_speed` converted from % and mph to pu and m/s (decision 9.9);
- the class functions `calculate_solar_radiation_shading_position_radians`,
  `calculate_solpos_radiation_shading_position_radians`, and
  `calc_solar_ideal_shading_position_radians`, against the `Insolation` of
  gridlabd `generators` `solar` objects that call them.

test_climate_autotest.py
------------------------

The gridlabd autotests of the `climate` module (`module/climate/autotest/`),
ported to `data/` (see `data/README.md`):

- every autotest is ported (6 files) and succeeds with no error lines;
- each `double_assert` of `test_WA-Yakima-tmy3.glm` whose window is in the
  run fails when its value is changed by 1 (10 of 11; the `rainfall`
  assert's window is in 2001, outside the run, in gridlabd too);
- the CSV autotests give the samples of their files hour by hour, with
  humidity converted from % to pu;
- the solar object of `test_singleHouseSolarInverter.glm` gets gridlabd's
  insolation (`data/reference/solar_hawaii.csv`);
- the asserts of `test_solar_opt.glm` fail when their value is 0.2 MWh
  off;
- the cloud model of `test_cloud_tmy3_opt.glm` keeps the insolation
  between the cloudy and clear values.

test_climate_module.py
----------------------

The package: the docstring examples (doctest), the entry point, `load()`
(classes, module, globals, loading into a second model), `modhelp` output
against `gridlabd --modhelp climate` (`data/reference/modhelp.txt`),
property types, units, defaults, flags, access, and keywords against
`gridlabd --modhelp=json climate` (`data/reference/modhelp.json`), except
the `wind_dir` unit (decision 9.9), pass
configuration, readiness levels, class functions, event handlers, the
handlers outside a run and on other classes, and entry point errors.

test_climate_class.py
---------------------

Class `climate`: manual climate control, TMY initialization (location,
records of extremes and their days, values at the start), files not
found, `climate::library_path`, unrecognized extensions, location checks,
short files and records out of range, TMY2 warnings, quadratic clipping
messages and the `VERBOSE` flag, the heat index, the cloud model's
property checks and events (including a run without a file, which
gridlabd fails), CSV files with the cloud model, the class functions (other
classes, outside a run, degree and radian forms, cloud locations),
`solar_flux()`, and the cache of TMY records.

test_climate_readers.py
-----------------------

`climate.tmy` (TMY3 and TMY2 headers and records, the 500-character line
buffer, open errors, short lines, `calc_solar()`) and `climate.csv_reader`
(`$` properties and the location, every read error, `timefmt`, the
`columns` property, missing files, `reader` errors, deferred
initialization, discarded samples and blank lines, one sample, a start
after the last sample of the year (which gridlabd fails), no samples, the latitude sign, timestamps as times, location checks, and
invalid dates).

test_climate_parts.py
---------------------

`climate.solar_angles` against values printed by gridlabd's
`solar_angles.cpp` compiled with `data/reference/solar_angles_main.cpp`
(`data/reference/solar_angles.txt`), SOLPOS branches, the cloud pattern
(size, binary cover, fuzzy edge, movement in eight directions, locations
outside the pattern, `solar` objects without a location), and the private
helpers (`sscanf()`, `strtok_r()`, `atoi()`, `atof()`, interpolation, number
and unit conversion, local time and `mkdatetime()`, message flags).
