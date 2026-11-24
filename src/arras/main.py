"""Arras command line processing"""

import sys

import arras.exitcodes
import arras.exceptions
import arras.runner

def _print(stdout:list[str], stderr:list[str]) -> None:
    """Print the runner's new output lines as they arrive"""
    for line in stderr:
        print(line, file=sys.stderr, flush=True)
    for line in stdout:
        print(line, file=sys.stdout, flush=True)

def main(args:list[str]=None):
    """Arras Energy main command line processor

    Runs the simulation with `arras.runner.Runner` and prints its output
    and error lines after each time step and when the run ends.

    Arguments
    ---------
    - `args`: command line argument list (default is `sys.argv[1:]`)

    Returns
    -------
    - `int`: the runner's exit code (see `arras.exitcodes`)
    """
    try:
        if args is None:
            args = sys.argv[1:] if len(sys.argv) > 1 else []

        result = arras.runner.Runner(*args, progress=_print)
        return result.returncode

    # pylint: disable=bare-except
    except:

        _,e_value,_ = sys.exc_info()
        arras.exceptions.exception(e_value)
        return arras.exitcodes.EXCEPTION
