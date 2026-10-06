"""Compatibility with xp2f's NaN-propagating vector reductions."""

import importlib.util
from pathlib import Path
import sys


def test_xp2f_min_max_helpers_are_inlined():
    path = Path(__file__).resolve().parents[1] / "scripts" / "opy.py"
    spec = importlib.util.spec_from_file_location("opy_reduction_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        source = '''program main
use python_mod, only: np_amin, np_amax
implicit none
integer, parameter :: dp = kind(1.0d0)
real(dp) :: x(3) = [1.0_dp, 2.0_dp, 3.0_dp]
print *, np_amin(x), np_amax(x)
end program main
'''
        result, unsupported = module.inline_ofort_helpers(source)
        assert unsupported == []
        assert "use python_mod" not in result
        assert "np_amin = minval(x)" in result
        assert "np_amax = maxval(x)" in result
        assert result.count("if (any(ieee_is_nan(x))) then") == 2
        assert result.count("ieee_value(1.0_dp, ieee_quiet_nan)") == 2
    finally:
        sys.modules.pop(spec.name, None)
