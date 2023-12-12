PKG = webfs

build: build-deps
	python -m build

install: build
	pip install dist/*.tar.gz

develop:
	pip install --upgrade pip
	pip install -e .

check:
	pytest -v tests

check-shell:
	tests/test_what.sh

uninstall:
	pip uninstall $(PKG)

clean:
	rm -rvf dist/ build/ src/*.egg-info

push-test:
	python -m twine upload --repository testpypi dist/*

pull-test:
	pip install -i https://test.pypi.org/simple/ $(PKG)

push-prod:
	python -m twine upload dist/*

pull-prod:
	pip install $(PKG)

build-deps:
	@python -c 'import build' &>/dev/null || pip install build
