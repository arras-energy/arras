"""Arras command line processing"""

import sys
import argparse

import arras.exitcodes
import arras.exceptions
import arras.runner

def main(args:list[str]=None):
    """Arras Energy main command line processor

    Arguments
    ---------
    - `args`: command line argument list
    """
    try:
        if args is None:
            args = sys.argv[1:] if len(sys.argv) > 1 else []

        result = arras.runner.Runner(*args)
        if result.stderr:
            print(*result.stderr,sep="\n",file=sys.stderr)
        if result.stdout:
            print(*result.stdout,sep="\n",file=sys.stdout)

        return result.returncode

    # pylint: disable=bare-except
    except:

        _,e_value,_ = sys.exc_info()
        arras.exceptions.exception(e_value)
        return arras.exitcodes.EXCEPTION
