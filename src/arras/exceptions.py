"""Arras exception handler"""

import sys
import os
import inspect
from typing import TypeVar, Callable

DEBUG = False
"""Enables halt with traceback on exception"""

TRACE = False
"""Outputs traceback of exception"""

class ArrasException(Exception):
    """General Arras exception"""

def exception(
    *args,
    handler:Callable=None,
    context:TypeVar('frame')=None,
    trace:bool|Callable=None,
    debug:bool=False
    ):
    """Handle an exception

    Arguments
    ---------
    - `*args`: string message(s) or exception object
    - `handler`: handler for exception message (default is `print` to `sys.stderr`)
    - `context`: frame to reference in output (default is caller)
    - `trace`: enables traceback, if callable traceback is sent to
      function (default is `handler`)
    - `debug`: enable immediate raise instead of normal/trace handling
    """

    # debug bypasses normal Arras exception handling
    if debug or DEBUG:
        _,e_value,_ = sys.exc_info()
        raise e_value

    # choose handler
    if handler is None:
        def handler(*args,**kwargs):
            if "file" not in kwargs:
                kwargs["file"] = sys.stderr
                print(*args,**kwargs)

    # get starting frame if not already specified
    if context is None:
        context = inspect.currentframe().f_back
    else:
        assert isinstance(context,type(inspect.currentframe())), \
            f"{context=} is not a frame"
    filename = os.path.basename(context.f_code.co_filename)
    lineno = context.f_lineno
    msg = " ".join([x if isinstance(x,str) else repr(x) for x in args])
    handler(f"EXCEPTION [arras/{filename}@{lineno}]: {msg}")

    if trace or TRACE :
        if not callable(trace):
            trace = handler
        trace("TRACEBACK:")
        while context:
            filename = context.f_code.co_filename
            lineno = context.f_lineno
            funcname = context.f_code.co_name
            trace(f"  {filename}@{lineno}: {funcname}")
            context = context.f_back
