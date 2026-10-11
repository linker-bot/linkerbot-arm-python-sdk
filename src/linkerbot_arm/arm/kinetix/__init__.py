import sys as _sys

try:
    from .kinetix import ArmKinetix
except ImportError as exc:
    if isinstance(exc, ModuleNotFoundError):
        if exc.name == "pinocchio":
            raise ImportError(
                "ArmKinetix requires Pinocchio in the current Python environment "
                f"(Python {_sys.version.split()[0]}, {_sys.executable}).\n"
                "Standalone Python: install the SDK with the 'kinetix' extra "
                "(pin>=4.1.0), or use compatible system/Conda Pinocchio with the base SDK.\n"
                "ROS2: install the APT Pinocchio for your ROS distribution, source its "
                "environment, and install the base SDK using the matching ROS Python."
            ) from exc
        # Missing native wrappers can mean the package was built for another
        # Python ABI. Keep unrelated missing dependencies as their original error.
        if not (exc.name or "").startswith(
            ("pinocchio.", "eigenpy.", "coal.", "numpy.", "scipy.")
        ):
            raise
    raise ImportError(
        "ArmKinetix could not load a dependency "
        f"under Python {_sys.version.split()[0]} ({_sys.executable}): {exc}\n"
        "Check Python, Pinocchio/eigenpy/Boost and NumPy/SciPy binary compatibility "
        "and module/library search paths. Use one compatible build stack; "
        "independent Python environments need their own paths, while ROS2 needs "
        "the matching ROS interpreter and environment."
    ) from exc

__all__ = ["ArmKinetix"]
