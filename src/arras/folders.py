"""Arras folders

The `arras.folders` module gives the three places where `arras` reads and
writes files, so that no part of `arras` depends on a `gridlabd` install
(`/usr/local/opt/gridlabd`, `GLD_*`, `GLPATH`, `~/.gridlabd`).

Syntax
------

    import arras.folders
    arras.folders.PACKAGEDIR
    arras.folders.userdir([*parts], [create=False])
    arras.folders.workdir()
    arras.folders.search_path([workdir])
    arras.folders.findfile(name, [workdir])

Arguments
---------
- `parts`: subfolder and file names under the user folder
- `create`: create the folder `userdir(*parts)` names if it does not exist
- `workdir`: working folder (default is the current working folder)
- `name`: file name to find, relative to the folders searched

Description
-----------

| Folder | Path | Holds |
|---|---|---|
| package | `PACKAGEDIR` | files installed with `arras` (`unitfile.txt`) |
| user | `userdir()` | files installed at runtime, shared by all models |
| working | `workdir()` | files of one project (models, modules, output) |

`PACKAGEDIR` is the folder of the `arras` package that Python imports, so
it moves with the Python environment where `arras` is installed. The user
folder is `ARRAS_USERDIR` when it is set, else `~/.arras`. The working
folder is the current working folder.

The user folder has these subfolders, which are the defaults of the folder
globals of `arras.globals`:

| Subfolder | Global | Holds |
|---|---|---|
| `share` | `datadir` | shared data files (unit files, includes, weather, ...) |
| `lib` | `libdir` | shared Python modules for GLM `module NAME;` |
| `include` | `incdir` | shared include files |
| `var` | `vardir` | logs, process ids, configuration |
| `tmp` | `tmp` | temporary files |

The functions are expected to satisfy:

1. `userdir(*parts)` returns the absolute path of `parts` under the user
   folder. It creates no folder unless `create=True`, in which case it
   creates the folder that the path names and its parents.
2. `search_path(workdir)` returns the working folder, the `share` folder
   of the user folder, and the package folder, in that order, so a project
   file hides a shared file and a shared file hides an installed file.
3. `findfile(name, workdir)` returns the absolute path of the first file
   `name` in `search_path(workdir)`, or `None`. An absolute `name` is
   returned when the file exists.

Examples
--------

    >>> import os, arras.folders
    >>> os.path.isfile(os.path.join(arras.folders.PACKAGEDIR, "unitfile.txt"))
    True
    >>> os.environ["ARRAS_USERDIR"] = "/home/user/.arras"
    >>> arras.folders.userdir("share")
    '/home/user/.arras/share'
    >>> arras.folders.search_path("/project")[:2]
    ['/project', '/home/user/.arras/share']
    >>> installed = os.path.join(arras.folders.PACKAGEDIR, "unitfile.txt")
    >>> arras.folders.findfile("unitfile.txt", "/nowhere") == installed
    True
    >>> del os.environ["ARRAS_USERDIR"]

Caveats
-------

- The folders are read when the functions are called, so a change of
  `ARRAS_USERDIR`, `HOME`, or the current working folder takes effect at
  the next call. Globals keep the values they were given when a `Globals`
  object was created.
- Nothing is written to the user folder unless code asks for it with
  `create=True`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. `GLD_ETC`, `GLD_BIN`, `GLD_LIB`, `GLD_VAR`, `GLD_INC`, `GLTEMP`, and
   `GLPATH` are not read. Shared files are found in the user folder and
   the package folder instead of the gridlabd install and `GLPATH`.

References
----------

- `arras-energy/gridlabd`: `source/globals.cpp` (folder globals),
  `source/find.cpp` (`find_file()`), `source/tmpfile.cpp` (`buildtmp()`)
"""

import os

PACKAGEDIR = os.path.dirname(os.path.abspath(__file__))
"""Folder of the installed `arras` package"""

USERDIR = "~/.arras"
"""Default user folder, used when `ARRAS_USERDIR` is not set"""

SUBFOLDERS = ("share", "lib", "include", "var", "tmp")
"""Subfolders of the user folder"""

def userdir(*parts:str, create:bool=False) -> str:
    """Path in the user folder

    Arguments
    ---------
    - `*parts`: subfolder and file names under the user folder
    - `create`: create the folder that the path names, and its parents

    Returns
    -------
    - `str`: absolute path
    """
    root = os.getenv("ARRAS_USERDIR") or USERDIR
    path = os.path.abspath(os.path.expanduser(os.path.join(root, *parts)))
    if create:
        os.makedirs(path, exist_ok=True)
    return path

def workdir() -> str:
    """Working folder, where project files are read and written

    Returns
    -------
    - `str`: absolute path of the current working folder
    """
    return os.getcwd()

def search_path(workdir:str|None=None) -> list[str]: # pylint: disable=redefined-outer-name
    """Folders searched for files

    Arguments
    ---------
    - `workdir`: working folder (default is the current working folder)

    Returns
    -------
    - `list[str]`: the working folder, the user `share` folder, and the
      package folder
    """
    return [workdir or os.getcwd(), userdir("share"), PACKAGEDIR]

def findfile(name:str, workdir:str|None=None) -> str|None: # pylint: disable=redefined-outer-name
    """Find a file in the search path

    Arguments
    ---------
    - `name`: file name, relative to the folders searched, or absolute
    - `workdir`: working folder (default is the current working folder)

    Returns
    -------
    - `str`: absolute path of the first file found
    - `None`: the file is not found
    """
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None
    for folder in search_path(workdir):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return os.path.abspath(path)
    return None
