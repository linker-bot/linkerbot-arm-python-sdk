"""Guard the arm API against the frozen pre-extraction source contract."""

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import linkerbot

BASELINE = json.loads(Path(__file__).with_name("upstream_api.json").read_text())
PACKAGE = Path(linkerbot.__file__).parent


@pytest.mark.parametrize("relative,record", BASELINE["files"].items())
def test_all_original_signatures(relative, record):
    path = PACKAGE.parent / relative
    assert path.is_file(), relative
    if path.suffix != ".py":
        return
    tree = ast.parse(path.read_text())
    signatures = {}

    def collect(body, prefix=""):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signatures[prefix + node.name] = {
                    "args": ast.unparse(node.args),
                    "returns": ast.unparse(node.returns) if node.returns else None,
                    "decorators": [ast.unparse(d) for d in node.decorator_list],
                }
            elif isinstance(node, ast.ClassDef):
                collect(node.body, prefix + node.name + ".")

    collect(tree.body)
    for name, signature in record["signatures"].items():
        assert signatures.get(name) == signature, f"{relative}:{name}"


@pytest.mark.parametrize(
    "name,module",
    [("A7", "a7.a7"), ("A7lite", "a7_lite.a7_lite"), ("P7", "p7.p7")],
)
def test_original_imports_preserve_class_identity(name, module):
    cls = getattr(linkerbot, name)
    assert cls is getattr(importlib.import_module("linkerbot.arm"), name)
    assert cls is getattr(importlib.import_module(f"linkerbot.arm.{module}"), name)


def test_lazy_import_and_no_hand_dependency():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import linkerbot
assert 'linkerbot.arm' not in sys.modules
from linkerbot import A7, A7lite, P7
assert 'pinocchio' not in sys.modules
assert not any(n.startswith('linkerbot.hand') for n in sys.modules)
assert 'tomli_w' not in sys.modules
assert not any(n in linkerbot.__all__ for n in ('L6', 'L30', 'O6'))
""",
        ],
        check=True,
    )


def test_pose_and_exception_identity():
    from linkerbot.arm.common import Pose
    from linkerbot.exceptions import ValidationError

    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    assert linkerbot.Pose is Pose
    assert Pose.from_list(values).to_list() == values
    assert linkerbot.ValidationError is ValidationError
