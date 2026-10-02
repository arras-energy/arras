"""Arras exit codes"""

EXFAILED = -1
"""Failure of exec/wait per system(3)"""

SUCCESS = 0
"""Successful completion per system(3)"""

ARGERR = 1
"""Error processing command line arguments"""

ENVERR = 2
"""Bad environment startup"""

TSTERR = 3
"""Requested test failed"""

USRERR = 4
"""User reject terms of use"""

RUNERR = 5
"""Simulation did not complete as desired"""

INIERR = 6
"""Initialization failed"""

PRCERR = 7
"""Process control error"""

SVRKLL = 8
"""Server killed"""

IOERR = 9
"""I/O error"""

LDERR = 10
"""Model load error"""

SHFAILED = 127
"""Shell failure per system(3)"""

SIGNAL = 128
"""Signal caught; must be or'd with SIG value if known"""

SIGHUP = SIGNAL|1
"""SIGHUP caught"""

SIGINT = SIGNAL|2
"""SIGINT caught"""

SIGKILL = SIGNAL|9
"""SIGKILL caught"""

SIGTERM = SIGNAL|15
"""SIGTERM caught"""

EXCEPTION = 255
"""Exception caught"""
