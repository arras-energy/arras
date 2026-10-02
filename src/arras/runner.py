"""Arras gridlabd runner"""

import os
import subprocess

class Runner:
    """GridLAB-D runner implementation

    Attributes
    ----------
    - `result:subprocess.CompletedProcess`: `subprocess.run` return value
    - `returncode:int`: gridlabd exitcode
    - `stderr:list[str]`: gridlabd error output
    - `stdout:list[str]`:
    """
    GRIDLABD_PATH = "/usr/local/opt/gridlabd/current"
    """Path to gridlabd system"""

    def __init__(self,*args,**kwargs):
        """Create a gridlabd runner

        Arguments
        ---------

        - `*args`: gridlabd positional arguments
        - `**kwargs`: `subprocess.run` keyword arguments
        """

        # default environment
        if "env" not in kwargs:
            kwargs["env"] = dict(os.environ)
            for key,value in (
                    ("GLD_DOC",f"{self.GRIDLABD_PATH}/doc"),
                    ("GLD_BIN",f"{self.GRIDLABD_PATH}/bin"),
                    ("GLD_ETC",f"{self.GRIDLABD_PATH}/share/gridlabd"),
                    ("GLPATH",f"{self.GRIDLABD_PATH}/lib/gridlabd:{self.GRIDLABD_PATH}/share/gridlabd"),
                    ("GLD_LIB",f"{self.GRIDLABD_PATH}/lib/gridlabd"),
                    ("GLD_SRC",f"{self.GRIDLABD_PATH}/src"),
                    ("GLD_INC",f"{self.GRIDLABD_PATH}/include"),
                    ("GLD_VAR",f"{self.GRIDLABD_PATH}/var/gridlabd"),
                    ("GLD_VER",f"{self.GRIDLABD_PATH}"),            
                    ):
                if not key in kwargs["env"]:
                    kwargs["env"][key] = value

        # default exe is "gridlabd.bin" in GLD_BIN folder
        if "exe" not in kwargs:
            exe = os.path.join(kwargs["env"]["GLD_BIN"],"gridlabd.bin")
        else:
            exe = kwargs["exe"]
            del kwargs["exe"]

        # run the executable with the specified kwargs
        self.result = subprocess.run([exe]+list(args),**kwargs)
        """`subprocess.CompletedProcess` return value"""

        # collect results from CompletedProcess
        self.returncode = self.result.returncode
        """Exit code of gridlabd process (see `arras.exitcodes`)"""

        self.stdout = self.result.stdout
        """Standard output when `subprocess.run` includes `capture_output=True`"""

        self.stderr = self.result.stderr
        """Standard error when `subprocess.run` includes `capture_output=True`"""
