"""Arras Energy package

Syntax: arras [OPTIONS ...] COMMAND [ARGUMENTS ...]
"""

import sys
from importlib import metadata as __metadata__
import gld_pypower

__version__ = __metadata__.version("arras")

# error handlers
E_OK = 0
E_SYNTAX = 1

def main(*args,**kwargs):
    """Arras CLI"""

    if not kwargs:
        kwargs = {}

    if len(args) == 1:
        print("\n".join([x for x in __doc__.split("\n") if x.startswith("Syntax: ")]))
        sys.exit(E_SYNTAX)

    if args[1] == "--modules":
        print(gld_pypower.__file__)

    raise NotImplementedError("main")

if __name__ == "__main__":

    main(__file__,"--modules")
