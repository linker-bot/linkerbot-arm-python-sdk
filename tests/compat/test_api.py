"""Guard the arm API against the frozen pre-extraction source contract."""

import ast
import importlib
import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import linkerbot_arm

BASELINE = json.loads(Path(__file__).with_name("upstream_api.json").read_text())
PACKAGE = Path(linkerbot_arm.__file__).parent


@pytest.mark.parametrize("relative,record", BASELINE["files"].items())
def test_all_original_signatures(relative, record):
    path = PACKAGE.parent / relative.replace("linkerbot", "linkerbot_arm", 1)
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
        if (
            relative == "linkerbot/comm/can/can.py"
            or relative.startswith("linkerbot/comm/canfd/")
        ) and name not in signatures:
            # Delegated methods still have to match the frozen source contract.
            # Resolve the actual inherited implementation, including properties;
            # do not regenerate the baseline or exempt the dispatcher from it.
            module = relative.removesuffix(".py").replace("/", ".")
            obj = importlib.import_module(
                module.replace("linkerbot", "linkerbot_arm", 1)
            )
            for part in name.split("."):
                obj = (
                    getattr(obj, part)
                    if inspect.ismodule(obj)
                    else inspect.getattr_static(obj, part)
                )
            if isinstance(obj, property):
                obj = obj.fget
            elif isinstance(obj, (classmethod, staticmethod)):
                obj = obj.__func__
            obj = inspect.unwrap(obj)
            delegated = ast.parse(textwrap.dedent(inspect.getsource(obj)))
            prefix = name.rsplit(".", 1)[0] + "." if "." in name else ""
            collect(delegated.body, prefix)
        assert signatures.get(name) == signature, f"{relative}:{name}"


@pytest.mark.parametrize(
    "name,module",
    [("A7", "a7.a7"), ("A7lite", "a7_lite.a7_lite"), ("P7", "p7.p7")],
)
def test_original_imports_preserve_class_identity(name, module):
    cls = getattr(linkerbot_arm, name)
    assert cls is getattr(importlib.import_module("linkerbot_arm.arm"), name)
    assert cls is getattr(importlib.import_module(f"linkerbot_arm.arm.{module}"), name)


def test_lazy_import_and_no_hand_dependency():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import linkerbot_arm
assert 'linkerbot_arm.arm' not in sys.modules
from linkerbot_arm import A7, A7lite, P7
assert 'pinocchio' not in sys.modules
assert not any(n.startswith('linkerbot_arm.hand') for n in sys.modules)
assert 'tomli_w' not in sys.modules
assert not any(n in linkerbot_arm.__all__ for n in ('L6', 'L30', 'O6'))
""",
        ],
        check=True,
    )


def test_pose_and_exception_identity():
    from linkerbot_arm.arm.common import Pose
    from linkerbot_arm.exceptions import ValidationError

    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    assert linkerbot_arm.Pose is Pose
    assert Pose.from_list(values).to_list() == values
    assert linkerbot_arm.ValidationError is ValidationError
