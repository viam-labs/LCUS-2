.PHONY: setup test device build

setup:
	./setup.sh

test:
	@test -x .venv/bin/python || python3 -m venv .venv
	.venv/bin/python -m pip install -q -r requirements.txt pytest
	.venv/bin/python -m pytest

device:
	./device.sh

build:
	./build.sh
