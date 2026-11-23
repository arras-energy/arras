[![Validation](https://github.com/arras-energy/arras/actions/workflows/validate.yaml/badge.svg)](https://github.com/arras-energy/arras/actions/workflows/validate.yaml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Farras-energy.github.io%2Farras%2Fcoverage%2Fbadge.json)](https://arras-energy.github.io/arras/coverage/)
[![Documentation](https://github.com/arras-energy/arras/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/arras-energy/arras/actions/workflows/deploy-pages.yml)

# Welcome

[Arras Energy](https://www.arras.energy/) is a release of [HiPAS GridLAB-D](https://github.com/slacgismo/hipas-gridlabd) supported by the Linux Foundation under LF Energy. [GridLAB-D](https://www.gridlabd.org/) was developed at Pacific Northwest National Laboratory with funding from the US Department of Energy.

## Documentation

See https://arras-energy.github.io/arras for the command line interface and supporting modules.

See https://docs.gridlabd.us/ for documentation of the HiPAS GridLAB-D simulator.

## Python API

`arras.Globals` holds the GridLAB-D global variables with the defaults that `gridlabd` uses. Users get, set, and create globals, and evaluate the `${...}` pseudo-globals and expansions that GLM files use:

```python
>>> from arras import Globals
>>> g = Globals()
>>> g.get("starttime")
'2000-01-01 00:00:00 UTC'
>>> g.expand("${RANGE,1,5,2}")
'1,3,5'
```

See the [`arras.globals` documentation](https://arras-energy.github.io/arras/arras/globals.html) for the full list.

## Testing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest pytest-cov
pytest --cov
```

See `src/arras/_test/README.md` for what the tests check. The coverage report for `main` is published at https://arras-energy.github.io/arras/coverage/.

## Source Code Repositories

See https://github.com/arras-energy for the project's repositories.
