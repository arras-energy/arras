PYPOWER (vendored)
==================

This folder holds the modules of [PYPOWER](https://github.com/rwl/PYPOWER)
5.1.16 that `runpf()` and `runopf()` use: the version that gridlabd pins
(`python/requirements.csv` in arras-energy/gridlabd: `PYPOWER,,,5.1.16`).
They are vendored because the `pypower` package of `arras` takes the
top-level name `pypower`, which is also PYPOWER's import name, so PYPOWER
cannot be installed beside it and imported.

Source: `PYPOWER-5.1.16.tar.gz` from PyPI, retrieved 2026-11-24. License:
BSD 3-clause, in `LICENSE` (Copyright (c) 1996-2015, Power System
Engineering Research Center (PSERC) and individual contributors).

Files: the 75 modules that `runpf()` and `runopf()` import (found by running
the Newton-Raphson, fast-decoupled XB and BX, Gauss-Seidel, and DC power
flows and the PIPS OPF on PYPOWER's `case9`, `case14`, and `case30`), and
`__init__.py`. Left out: `api.py` (it imports PYPOWER's tests), the case
files, the tests (`t/`), and the continuation power flow, unit commitment,
and other functions that `runpf()` and `runopf()` do not call.

Changes made to the PYPOWER files, and only these:

1. `from pypower.X import ...` is `from pypower._pypower.X import ...`.
2. `Inf`, `NaN`, and `in1d` are `inf`, `nan`, and `isin` (removed in
   numpy 2; gridlabd's solver adds `numpy.Inf` back for the same reason).
3. `Ybus.H` and `Ybr.H` in `d2Sbus_dV2.py` and `d2Sbr_dV2.py` are
   `.conj().T` (the `.H` attribute of scipy sparse matrices was removed
   after the scipy 1.13 that gridlabd pins).
4. Strings with invalid escape sequences in `opf_model.py`,
   `qps_cplex.py`, and `qps_mosek.py` are raw strings.

Check: on 2026-11-24, the power flows (the four methods and DC) of
`case4gs`, `case9`, `case14`, `case30`, `case39`, `case57`, and
`case118`, and the OPF of the cases with cost data, gave the same
voltages (to 8 decimals), success flags, and costs with these files under
numpy 2.5 and scipy 1.18 as PYPOWER 5.1.16 from PyPI under numpy 1.26 and
scipy 1.13.

Known PYPOWER defects kept (both also with numpy 1.26):

- `runpf()` with `ENFORCE_Q_LIMS` indexes an array with floats and raises
  `IndexError`, so `pypower::enforce_q_limits TRUE` makes the solver fail.
- The PIPS OPF raises `ValueError` when no branch has a rating (`rateA`
  0 on every branch).

Do not edit these files except to update the vendored version; record any
change here.
