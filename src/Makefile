.PHONY: install uninstall

all: install

uninstall:
	pip3 uninstall -y elastictalk

install: uninstall
	python3 setup.py bdist_wheel
	pip3 install dist/elastictalk-0.0.1-py3-none-any.whl
