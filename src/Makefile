.PHONY: install uninstall build

all: install

build:
	python3 setup.py bdist_wheel

uninstall:
	pip3 uninstall -y elastictalk

install: uninstall build
	pip3 install dist/elastictalk-0.0.1-py3-none-any.whl

deploy: build
	python3 -m twine upload dist/*
