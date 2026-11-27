Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	pip install -e . pytest
	pytest src/generators/_test

The package must be installed (editable or not), because `Model` finds the
module through the `arras.modules` entry point in `pyproject.toml`. The
tests use no network and no credentials, and finish in about 20 seconds
(12 of them for the year-long `test_solar_climate_default_playerval.glm`).

`conftest.py` runs each test in an empty temporary folder with empty
`arras.oclass.Class.registry` and `arras.module.Module.registry`, puts the
`climate` test data folder (`src/climate/_test/data/`, which holds the
Yakima TMY3 file) on `GLPATH`, ignores the `data` folder when collecting
tests, and provides `model()` and `run()` (GLM text after a clock and the
modules), `errors()` and `warnings()` (a run's lines without their time
stamps), and the `data` fixture (the ported autotests and their players
copied to the test's folder).

test_generators_module.py
-------------------------

Registration: `module generators;` registers `inverter` and `solar` with
the 163 and 40 properties gridlabd publishes, in its order, with the
`create()` defaults, and the module globals; the handlers need a run; the
docstring examples of `generators`, `generators.inverter`, and
`generators.solar` give the output shown.

test_generators_solar.py
------------------------

`solar` in player mode, against values computed in the tests from the
formulas of `solar.cpp`: the default (base efficiency) power model with
its temperature correction and output voltage and current; the flat plate
model; the flat plate temperature history over three hourly steps (the
second step does not shift, since gridlabd moves the object's clock after
the bottom-up pass); init defaults and gridlabd's warnings; the default
efficiency of each panel type; an overspecified rating; refused generator
modes; the static weather (with gridlabd's cosine of degrees); a climate
object found, written to `weather`, and the tilt fixed to its latitude;
and the errors for `FIXED_AXIS` without climate, a weather object that is
not a climate, tilt angles outside 0 to 90 degrees, a shading factor
outside 0 to 1, and a parent that is not an inverter.

test_generators_inverter.py
---------------------------

`inverter` on a meter fed from a swing node through a link, with `V_In`
and `I_In` set (10 kW DC): legacy PWM output split among three, two, or
one phases, with a power factor, on a triplex meter, and the parent's
accumulators back to 0 after the run; `TWO_PULSE` becoming `PWM`; the
legacy modes that gridlabd refuses; four-quadrant `CONSTANT_PF` with a
leading power factor and at its limit; `CONSTANT_PQ` limits and a full
battery; `OFFLINE`; a parent out of service; parent errors; the modes not
ported yet; the multipoint efficiency model (missing parameters, the SMA
preset against the CEC formula); and an array declared before its
inverter.

test_generators_autotest.py
---------------------------

The gridlabd autotests of `module/generators/autotest/` that use the
ported classes and the Yakima weather file, ported to `data/` (see
`data/README.md`): each succeeds with no error lines, except
`test_solar_parent_err.glm`, which fails at init with gridlabd's message;
and their asserts fail when an input of the model is changed (two changes
for each of the multipoint, four-quadrant, and player tests, one for each
`Vout` test; the player test's changes in its first week), so they test
the values.

test_generators_reference.py
----------------------------

`solar` against gridlabd: the `climate` package's reference files
`solar_position.csv`, `solar_solpos.csv`, and `solar_ideal.csv` hold the
`Insolation` that gridlabd `solar` objects (master 076e78a) recorded every
15 minutes for two days with the Yakima weather (Liu-Jordan and SOLPOS
tilt models on a fixed array, and the ideal orientation). The same model,
run with this package, records the same 192 values of each (within
1e-5).
