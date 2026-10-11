"""Dependency diagnostics should distinguish missing Pinocchio from bad builds."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "failure",
    ["pinocchio", "scipy", "pinocchio.pinocchio_pywrap_default", "native", "runtime"],
)
def test_kinetix_dependency_diagnostics(failure):
    code = """
import importlib.abc
import importlib.util
import sys

mode = sys.argv[1]
if mode in ('pinocchio', 'scipy', 'pinocchio.pinocchio_pywrap_default'):
    original = ModuleNotFoundError('Missing test dependency: ' + mode, name=mode)
elif mode == 'native':
    original = ImportError('libboost_python313.so.1.90.0: cannot open shared object file')
else:
    original = RuntimeError('Unexpected kinematics implementation failure')

class BrokenKinetix(importlib.abc.Loader):
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        raise original

class DependencyFailure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'linkerbot_arm.arm.kinetix.kinetix':
            return importlib.util.spec_from_loader(fullname, BrokenKinetix())

sys.meta_path.insert(0, DependencyFailure())
try:
    from linkerbot_arm.arm.kinetix import ArmKinetix
except Exception as error:
    if mode == 'pinocchio':
        assert type(error) is ImportError
        assert error.__cause__ is original
        assert 'kinetix' in str(error) and 'APT' in str(error)
        assert 'base SDK' in str(error)
        assert sys.executable in str(error)
    elif mode in ('native', 'pinocchio.pinocchio_pywrap_default'):
        assert type(error) is ImportError
        assert error.__cause__ is original
        assert str(original) in str(error)
        assert 'NumPy/SciPy binary compatibility' in str(error)
        assert sys.executable in str(error)
    else:
        assert error is original
else:
    raise AssertionError('Expected the injected dependency failure')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, failure],
        cwd=Path(__file__).resolve().parents[2],
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
