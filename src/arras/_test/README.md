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
- unit checks with `arras.units`: the shared `Class.units` manager,
  `unit_spec` on properties, unknown units refused by `add_property` and
  `publish`, `name[unit]` limited to `double`/`complex`, a custom unit
  file, and a unit file that fails to load;
- `find_property` through parents, deprecated notices, keyword order and
  the `set` `CHARSET` flag, functions, and event handlers;
- `modhelp`, `to_glm`/`saveall` with `glm_save_options`, `to_xml`/`saveall_xml`,
  and `to_dict`;
- the module docstring examples (doctest).

Each test starts and ends with an empty class registry (`Class.reset()`).
Run it alone with:

	pytest src/arras/_test/test_oclass.py

test_model.py
-------------

Fast, self-contained tests of `arras.model`:

- objects: names (`CLASS:ID` for unnamed objects, naming rules,
  `relax_naming_rules`), ids, `Class.numobjs`, and the container protocol;
- `add_object`/`add_objects` (all or nothing, references within a batch,
  parent loops), `delete_object`/`delete_objects` with `children` set to
  `error`, `orphan`, and `delete`, and `rename`;
- `find` by name, property value, class default, and class (with
  inheritance);
- `get_property`/`get_properties` and `set_property`/`set_properties`
  (several objects at once, all or nothing, read-only header properties);
- the value check of every property type, accepted and refused values, unit
  conversion, transforms and filters, `strict=False`, and `check()`;
- GLM reading: a sample model with nested objects, `:..COUNT` and
  `:FIRST..LAST`, `inherit`, `@NAME`, multi-line and structured values,
  every supported directive and macro, `#include`, `Model.module_loader`,
  and the error message and line number for each kind of bad input;
- GLM and JSON writing, and reading the output back into the same objects;
- `load_classes` from `--modhelp=json` style data, JSON globals, filters,
  and errors;
- `data/case14.json`, written by gridlabd 4.3.11 (see `data/README.md`):
  read, checked, compared with the original objects, and written back as
  JSON and GLM;
- the module docstring examples (doctest).

Each test starts and ends with an empty class registry (`Class.reset()`).
Run it alone with:

	pytest src/arras/_test/test_model.py

Tests that write files write only to pytest's temporary folder.

test_units.py
-------------

Fast, self-contained tests of `arras.units`:

- loading the bundled copy of gridlabd's `runtime/unitfile.txt`: constants,
  scalar prefixes, primary and derived units, and the `unitfile.txt` search
  in the working folder and `GLPATH`;
- the unit parameters that gridlabd's `unit.cpp` computes, including the
  parsing behaviors that `arras.units` reproduces (see its Caveats);
- prefixed and compound units derived on request, and lookup errors;
- every conversion of gridlabd's `unit_test()` (`gridlabd --unitstest`),
  forward and back, plus other conversions, complex values, and mismatched
  units;
- unit file syntax and error reporting with file and line number;
- the module docstring examples (doctest).

Run it alone with:

	pytest src/arras/_test/test_units.py

Tests that write unit files write only to pytest's temporary folder.
