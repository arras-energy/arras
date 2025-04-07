# Makefile
#
# You must run this after updating the code to ensure the documentation is updated as well
#

docs/index.html: arras.py gld_pypower/gld_pypower.py Makefile
	@test -d .venv || python3 -m venv .venv
	@echo Updating $@...
	(source .venv/bin/activate; python3 -m pip install -r requirements.txt)
	(source .venv/bin/activate; pylint arras.py)
	(source .venv/bin/activate; cd gld_pypower; $(MAKE))
	(source .venv/bin/activate; export PYTHONPATH=.; qdox --withcss)
	@echo Done
