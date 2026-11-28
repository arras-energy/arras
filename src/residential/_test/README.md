Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	pip install -e . pytest
	pytest src/residential/_test

The package must be installed (editable or not), because `Model` finds the
module through the `arras.modules` entry point in `pyproject.toml`. The
tests use no network and no credentials, and finish in about 20 seconds.

`conftest.py` runs each test in an empty temporary folder with empty
`arras.oclass.Class.registry` and `arras.module.Module.registry`, ignores
the `data` folder when collecting tests, and provides helpers (the
`helpers` fixture):

- `model()` and `run()`: GLM text after a UTC clock and the `powerflow`,
  `tape`, and `residential` modules (`implicit_enduses NONE` by default),
  optionally after `FEEDER`, a swing `triplex_node` feeding the triplex
  meter `meter` through a 0.1 ft lossless triplex line;
- `run_file()`: a GLM file of `data/`, with the Yakima TMY3 file of
  `src/climate/_test/data/` and the players of `data/`;
- `errors()`, `warnings()`, `read_csv()`.

test_residential_module.py
--------------------------

The docstring examples; registration (class order, parents, readiness
level, the enduse internal item added once) and globals; published
properties (enduse parts, `panel.` parts, units, keyword values and
defaults); globals set in the module block; implicit enduses refused; the
static weather and voltage warnings; enduse energy and heat gain
accumulation and the panel sum; handlers outside a run; property aliases.

test_residential_house.py
-------------------------

gridlabd's `test_HVAC_common_cool`, `test_HVAC_common_heat`,
`test_HVAC_peak_cool`, and `test_HVAC_peak_heat` (HVAC and meter energy
within gridlabd's tolerances, 0.5% of the reference ETP results) and
`test_HVAC_balance`; initialization defaults (geometry, R-values, window
SHGC and R-value, UA, sizing, system types), thermal integrity levels, the
legacy `system_type`; `e2solve()` against a brute-force check of the
first positive root; thermostat cycling within the deadband; panel loads
posted to and removed from the meter, and measured by it; a meter out of
service; breaker trips and reclosing; the ANSI voltage warning.

test_residential_zipload.py
---------------------------

gridlabd's `test_zipload_pow_en_hg`; the ZIP parts and power factors,
actual power, power factor sign, and heat gain; duty cycle; heat gain
only; no house parent; a parent that is not a house; demand response;
initialization errors.

data/
-----

gridlabd autotests from `module/residential/autotest/` (gridlabd master
076e78a), with the changes listed at the top of each file:

- `PST8PDT` for `PST+8PDT` and `Etc/GMT-1` for `PST+0PDT` (the summer
  runs are in daylight time), which `arras` does not parse;
- constant setpoint schedules as constants and the `zippwr` schedule as a
  player (`*_zippwr.csv`), since `arras` does not model schedules;
- 5-minute recorders for gridlabd's 1-second ones (the results are the
  same with 60-second steps);
- the meter fed by a swing `triplex_node` through a 0.1 ft lossless
  triplex line, because `arras` meters measure the links that feed them;
- in `test_zipload_pow_en_hg.glm`, an hourly recorder (arras makes no
  event at the in-service time of the asserts) and meter energy
  tolerances of 0.01 (the feeder line changes the meter voltage).

The asserts of the HVAC files are in service from 19 to 47 s before their
stop times, at which `arras` has no event, so the tests check the
energies at the stop time.
