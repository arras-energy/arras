Testing
-------

From the repository root:

	python3 -m venv .venv
	. .venv/bin/activate
	python3 -m pip install --upgrade pip
	pip install -e . pytest
	pytest

Coverage (settings in `pyproject.toml` under `[tool.coverage.*]`):

	pip install pytest-cov
	pytest --cov --cov-report=term --cov-report=html   # report in htmlcov/

CI (`.github/workflows/validate.yaml`) installs the package non-editable and
runs the tests with coverage. Coverage is informational. Each run shows a
summary on its page and uploads `coverage.xml` and `htmlcov/` as the
`coverage-report` artifact. After Validation passes on `main`,
`.github/workflows/deploy-pages.yml` publishes that report at
https://arras-energy.github.io/arras/coverage/, where `badge.json` feeds the
README badge. The tests use no
network and no credentials, and finish in about a second.

test_globals.py
---------------

Fast, self-contained tests of `arras.globals`:

- defaults: the 160 globals of gridlabd's `source/globals.cpp` `map[]` table,
  their order, aliases, types, access, keyword tables, default strings, and
  folder defaults taken from `GLD_*`, `GLTEMP`, and `PYTHONPATH`;
- `set`/`get` conversion for each property type, the `NAME=VALUE` form,
  `strictnames`, units, date formats, time zones, and relative timestamps;
- `create`, `push`, the container protocol, `dump`, and `saveall`;
- every pseudo-global (`GUID`, `SEQ_*`, `SHELL`, `PYTHON`, `RANGE`,
  `FINDFILE`, `FILENAME`/`FILEPATH`/`FILETYPE`, `FIND`, `GEOCODE`,
  `TMPFILE`, `RANDOM`, ...) and every expansion form, including C integer
  semantics (truncating division, int32 wrap-around);
- the module docstring examples (doctest).

Run it alone with:

	pytest src/arras/_test/test_globals.py

`SHELL` tests run `echo`; `TMPFILE` and `FINDFILE` tests write only to
pytest's temporary folder.

test_oclass.py
--------------

Fast, self-contained tests of `arras.oclass`:

- the `PROPERTY_TYPES` and `PASSCONFIG` tables from gridlabd's
  `source/property.cpp` and `source/class.h`;
- class registration (ids, duplicate names per module, name limits),
  `find` (including `module.class`), `reset`, and GLM `declare` with
  inheritance qualifiers;
- `set_parent` for GLM and module classes, inheritance loops, the
  `UNSAFE_OVERRIDE_OMIT` warnings, and `isa`;
- `publish` (units, keywords, access, flags, defaults, reserved header
  names) and `add_property` (type checks against existing and inherited
  properties, unit and keyword rules, no additions after instantiation);
- `find_property` through parents, deprecated notices, keyword order and
  the `set` `CHARSET` flag, functions, and event handlers;
- `modhelp`, `to_glm`/`saveall` with `glm_save_options`, `to_xml`/`saveall_xml`,
  and `to_dict`;
- the module docstring examples (doctest).

Each test starts and ends with an empty class registry (`Class.reset()`).
Run it alone with:

	pytest src/arras/_test/test_oclass.py
