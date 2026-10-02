"""Arras Energy

Syntax: `arras [OPTIONS ...] FILE1 [FILE2 [...]] [OPTIONS ...]`

Command-line options
--------------------
-  `--check|-c`: Performs module checks before starting simulation
-  `--debug`: Toggles display of debug messages
-  `--debugger`: Enables the debugger
-  `--dumpall`: Dumps the global variable list
-  `--mt_profile N-THREADS`: Analyses multithreaded performance profile
-  `--profile`: Toggles performance profiling of core and modules while simulation runs
-  `--quiet|-q`: Toggles suppression of all but error and fatal messages
-  `--verbose|-v`: Toggles output of verbose messages
-  `--warn|-w`: Toggles display of warning messages
-  `--workdir|-W`: Sets the working directory
-  `--rusage`: Collect resource usage statistics
-  `--module|-M MODULE`: Load a module

Global, environment and module information
------------------------------------------
-  `--define|-D NAME=[MODULE:]VALUE`: Defines or sets a global (or module) variable
-  `--globals`: Displays a sorted list of all global variables
-  `--libinfo|-L MODULE`: Displays information about a module
-  `--printenv|-E`: Displays the default environment variables

Information
-----------
-  `--copyright`: Displays copyright
-  `--license`: Displays the license agreement
-  `--version|-V [all,number,build,package,branch,platform] Displays the version information
-  `--build-info`: Displays the build information
-  `--setup`: Open simulation setup screen
-  `--origin`: Display origin information
-  `--cite`: Print the complete citation for this version
-  `--depends`: Generate dependency tree

Test processes
--------------
-  `--dsttest`: Perform daylight savings rule test
-  `--endusetest`: Perform enduse pseudo-object test
-  `--globaldump`: Perform a dump of the global variables
-  `--loadshapetest`: Perform loadshape pseudo-object test
-  `--locktest`: Perform memory locking test
-  `--modtest MODULE`: Perform test function provided by module
-  `--randtest`: Perform random number generator test
-  `--scheduletest`: Perform schedule pseudo-object test
-  `--test MODULE`: Perform unit test of module (deprecated)
-  `--testall=FILENAME`: Perform tests of modules listed in file
-  `--unitstest`: Perform unit conversion system test
-  `--validate[=FILENAME ...`: Perform model validation check

File and I/O Formatting
-----------------------
-  `--kml[=FILENAME]`: Output to KML (Google Earth) file of model (only supported by some modules)
-  `--stream`: Toggles streaming I/O
-  `--sanitize OPTIONS INDEXFILE OUTPUTFILE`: Output a sanitized version of the GLM model
-  `--xmlencoding 8|16|32`: Set the XML encoding system
-  `--xmlstrict`: Toggle strict XML formatting (default is enabled)
-  `--xsd [module[:class]]`: Prints the XSD of a module or class
-  `--xsl module[,module[,...]]]`: Create the XSL file for the module(s) listed
-  `--formats`: get a list supported file formats
-  `--sublime_syntax`: generate sublime syntax file

Help
----
-  `--help|-h`: Displays command line help
-  `--info SUBJECT`: Obtain online help regarding SUBJECT
-  `--modhelp module[:class]`: Display structure of a class or all classes in a module
-  `--modlist`: Display list of available modules
-  `--example module:class`: Display an example of an instance of the class after init
-  `--mclassdef module:class`: Generate Matlab classdef of an instance of the class after init
-  `--loadshape name:year`: Generate the named schedule as a timeseries for given year

Process control
---------------
-  `--pidfile[=FILENAME]`: Set the process ID file (default is gridlabd.pid)
-  `--threadcount|-T N`: Set the maximum number of threads allowed
-  `--job ...`: Start a job
-  `--nprocs`: Display the number of processors available to run jobs

System options
--------------
-  `--avlbalance`: Toggles automatic balancing of object index
-  `--bothstdout`: Merges all output on stdout
-  `--check_version`: Perform online version check to see if any updates are available
-  `--compile|-C`: Toggles compile-only flags
-  `--initialize|-I`: Toggles initialize-only flags
-  `--library|-l FILENAME`: Loads a library GLM file
-  `--environment|-e APPNAME`: Set the application to use for run environment
-  `--output|-o FILE`: Enables save of output to a file (default is gridlabd.glm)
-  `--pause`: Toggles pause-at-exit feature
-  `--relax`: Allows implicit variable definition when assignments are made
-  `--template|-t`: Load template

Server mode
-----------
-  `--server`: Enables the server
-  `--daemon|-d COMMAND`: Controls the daemon process
-  `--remote|-r COMMAND`: Connects to a remote daemon process
-  `--clearmap`: Clears the process map of defunct jobs (deprecated form)
-  `--pclear`: Clears the process map of defunct jobs
-  `--pcontrol`: Enters process controller
-  `--pkill PROCNUM`: Kills a run on a processor
-  `--plist`: List runs on processes
-  `--pstatus`: Prints the process list
-  `--redirect STREAM[:FILE]`: Redirects an output to stream to a file (or null)
-  `--server_portnum|-P`: Sets the server port number (default is 6267)
-  `--server_inaddr`: Sets the server interface address (default is INADDR_ANY, any interface)
-  `--slave MASTER`: Enables slave mode under master
-  `--slavenode`: Sets a listener for a remote GridLAB-D call to run in slave mode
-  --id IDNUM`: Sets the ID number for the slave to inform its using to the master
"""

import arras.exceptions as exception
import arras.exitcodes as exitcodes
import arras.main as main
import arras.runner as runner
