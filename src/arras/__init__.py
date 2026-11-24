"""Arras Energy

Syntax: `arras [OPTIONS ...] FILE1 [FILE2 [...]] [OPTIONS ...]`

The `arras` command reads the model files named on the command line and
solves the quasi-steady time series in Python with `arras.runner.Runner`;
it does not run `gridlabd`. Arguments are processed in order.

Command-line options
--------------------
-  `FILE.glm`, `FILE.json`: Reads a model file
-  `--define|-D NAME=VALUE`: Defines or sets a global variable
-  `--output|-o FILE`: Saves the model to FILE (`.glm` or `.json`) when the run ends
-  `--check|-c`: Checks the model before the simulation starts
-  `--compile|-C`: Loads the model only
-  `--initialize|-I`: Loads and initializes the model only
-  `--quiet|-q`: Toggles suppression of all but error messages
-  `--verbose|-v`: Toggles output of verbose messages
-  `--warn|-w`: Toggles display of warning messages
-  `--debug`: Toggles display of debug messages

Other gridlabd options are not supported (exit code `arras.exitcodes.ARGERR`).
See `arras.runner` for the simulation, the event handlers that give objects
behavior, background runs, and the progress callback.

Python API
----------
-  `arras.globals.Globals`: global variables with gridlabd defaults, get/set/create,
   and `${...}` pseudo-global and expansion evaluation (see `arras.globals`)
-  `arras.oclass.Class`: object classes with gridlabd's class registry,
   property declaration and inheritance, keywords, functions, event handlers,
   and modhelp/GLM/XML output (see `arras.oclass`)
-  `arras.units.Units`: unit manager that reads gridlabd's `unitfile.txt`,
   derives compound units, and converts values between units (see `arras.units`)
-  `arras.model.Model`: gridlabd model (globals, modules, classes, schedules,
   filters, and objects keyed on name) with GLM and gridlabd JSON read/write,
   regex search, add/delete, and validated get/set of properties (see `arras.model`)
-  `arras.module.Module`: modules with gridlabd's module list, the classes each
   module registers, the solvers that keep the clock synchronized, class
   heartbeat solvers, and the core's internal items (random variables,
   schedules, loadshapes, transforms, enduses), with dispatchers that combine
   their results as the gridlabd core does (see `arras.module`)
-  `arras.folders`: the package folder (files installed with `arras`), the
   user folder (`ARRAS_USERDIR`, else `~/.arras`: files installed at runtime
   and shared by all models), and the working folder (project files), and
   the file search across them (see `arras.folders`)
-  `arras.runner.Runner`: quasi-steady time-series simulation of a model,
   in the foreground or in a background thread with a progress callback
   (see `arras.runner`)

gridlabd modules in Python
--------------------------
Python packages installed with `arras` implement some gridlabd modules. A
model loads one with GLM `module NAME;` (`arras.model.Model.load_module()`
finds it as an `arras.modules` entry point):

-  `assert`: the `assert`, `double_assert`, `complex_assert`, `enum_assert`,
   and `int_assert` classes, whose objects stop a simulation when a property
   check fails (see `assert`)
"""

import arras.exceptions as exception
import arras.exitcodes as exitcodes
import arras.folders
import arras.globals
import arras.oclass
import arras.main as main
import arras.runner as runner
import arras.units
import arras.model
import arras.module

from arras.globals import Globals, GlobalsError
from arras.oclass import Class, ClassError
from arras.units import Units, Unit, UnitsError
from arras.model import Model, ModelError, Object
from arras.module import Module, ModuleError
from arras.runner import Runner, RunnerError
