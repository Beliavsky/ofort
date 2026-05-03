from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
OFORT = ROOT / "ofort.exe"
CASES = ROOT / "tests" / "cases"
RUNNER = ROOT / "scripts" / "xofort.py"


@pytest.fixture(scope="session", autouse=True)
def build_ofort():
    result = subprocess.run(
        ["make"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert OFORT.exists()


def case_files():
    return sorted(
        source for source in CASES.glob("*.f90")
        if source.name not in {
            "xsub.f90",
            "ximplicit_none.f90",
            "xtype_change.f90",
            "xwrite_file.f90",
            "xwrite_file_alloc.f90",
            "xstream.f90",
            "xexit.f90",
            "xtyped_function.f90",
            "xtype_keyword_intrinsic.f90",
            "xrandom_print_array.f90",
            "ximplicit_default.f90",
            "xcpu_time.f90",
            "xdate_and_time.f90",
            "xtransfer.f90",
            "xsave.f90",
            "xentry_obsolescent.f90",
            "xalternate_return_obsolescent.f90",
            "xallocate_already_allocated.f90",
        }
    )


@pytest.mark.parametrize("source", case_files(), ids=lambda p: p.stem)
def test_case_stdout(source):
    expected = source.with_suffix(".out").read_text(encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == expected


def test_entry_statement_is_reported_obsolescent():
    source = CASES / "xentry_obsolescent.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    expected = source.with_suffix(".out").read_text(encoding="utf-8").strip()
    assert expected in result.stderr


def test_alternate_return_is_reported_obsolescent():
    source = CASES / "xalternate_return_obsolescent.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    expected = source.with_suffix(".out").read_text(encoding="utf-8").strip()
    assert expected in result.stderr


def test_allocate_rejects_already_allocated_variable():
    source = CASES / "xallocate_already_allocated.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    expected = source.with_suffix(".out").read_text(encoding="utf-8").strip()
    assert expected in result.stderr
    assert "line 17: allocate (dates(4))" in result.stderr


def test_parser_expected_token_errors_are_readable(tmp_path):
    source = tmp_path / "xbad_syntax.f90"
    source.write_text("integer : i\n", encoding="utf-8")
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Expected token type" not in result.stderr
    assert "Syntax error at line 1: expected identifier but found ':'" in result.stderr
    assert "line 1: integer : i" in result.stderr


def test_xsub_random_statistics():
    source = CASES / "xsub.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""

    parts = result.stdout.split()
    assert len(parts) == 3
    n = int(parts[0])
    mean = float(parts[1])
    sd = float(parts[2])

    assert n == 100
    assert 0.0 <= mean < 1.0
    assert 0.0 <= sd < 0.6


def test_cpu_time_runs_and_reports_elapsed_time():
    source = CASES / "xcpu_time.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[:2] == [
        "cpu_time returns CPU time in seconds.",
        "",
    ]
    assert re.match(r"^result s = \d+(?:\.\d+)?(?:e[+-]?\d+)?$", lines[2])
    match = re.match(r"^CPU time = ([0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?) seconds$", lines[3])
    assert match
    assert float(match.group(1)) >= 0.0


def test_date_and_time_reports_clock_fields():
    source = CASES / "xdate_and_time.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert "date only:" in lines
    assert "time only:" in lines
    assert "zone only:" in lines
    assert "values only:" in lines
    assert "all arguments:" in lines
    date_match = re.search(r"(?m)^date =  (\d{8})$", result.stdout)
    time_match = re.search(r"(?m)^time =  (\d{6}\.\d{3})$", result.stdout)
    zone_match = re.search(r"(?m)^zone =  ([+-]\d{4})$", result.stdout)
    values_match = re.search(
        r"(?m)^values =  (\d{4}) (\d{1,2}) (\d{1,2}) ([+-]?\d+) "
        r"(\d{1,2}) (\d{1,2}) (\d{1,2}) (\d{1,3})$",
        result.stdout,
    )
    formatted_match = re.search(
        r"(?m)^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{3}) ([+-]\d{4})$",
        result.stdout,
    )
    assert date_match
    assert time_match
    assert zone_match
    assert values_match
    assert formatted_match
    year, month, day, offset, hour, minute, second, millisecond = values_match.groups()
    assert date_match.group(1) == f"{year}{int(month):02d}{int(day):02d}"
    assert time_match.group(1) == f"{int(hour):02d}{int(minute):02d}{int(second):02d}.{int(millisecond):03d}"
    assert zone_match.group(1) == formatted_match.group(8)
    assert formatted_match.groups()[:7] == (
        year,
        f"{int(month):02d}",
        f"{int(day):02d}",
        f"{int(hour):02d}",
        f"{int(minute):02d}",
        f"{int(second):02d}",
        f"{int(millisecond):03d}",
    )
    assert -1440 <= int(offset) <= 1440


def test_transfer_reinterprets_basic_values():
    source = CASES / "xtransfer.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "integer to real:" in result.stdout
    assert "real to integer:" in result.stdout
    assert "character to integer:" in result.stdout
    assert "array result using size argument:" in result.stdout

    int_to_real = re.findall(r"ia\(i\) = (\d+)  transfer -> real = ([0-9.e+-]+)", result.stdout)
    assert [int(i) for i, _ in int_to_real] == [1, 2, 3, 4]
    assert [pytest.approx(float(x), rel=1e-6) for _, x in int_to_real] == [
        1.401298e-45,
        2.802597e-45,
        4.203895e-45,
        5.605194e-45,
    ]

    real_to_int = re.findall(r"ra\(i\) = (\d+)  transfer -> integer = (\d+)", result.stdout)
    assert [(int(r), int(i)) for r, i in real_to_int] == [
        (1, 1065353216),
        (2, 1073741824),
        (3, 1077936128),
        (4, 1082130432),
    ]

    assert "s = ABCD  transfer(s,0) = 1145258561" in result.stdout
    assert "transfer(ia, 0.0, size=2) = 1.401298e-45 2.802597e-45" in result.stdout
    assert "transfer(ia, 0.0, size=1) = 1.401298e-45" in result.stdout


def test_formatted_print_expands_random_array():
    source = CASES / "xrandom_print_array.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    parts = result.stdout.split()
    assert len(parts) == 2
    assert all(0.0 <= float(part) < 1.0 for part in parts)


def test_implicit_none_rejects_undeclared_variable():
    source = CASES / "ximplicit_none.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Variable 'i' has no implicit type" in result.stderr
    assert "line 2: i = 2" in result.stderr


def test_implicit_typing_is_default():
    source = CASES / "ximplicit_default.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2"]
    assert result.stderr == ""


def test_no_implicit_typing_option_rejects_undeclared_variable():
    source = CASES / "ximplicit_default.f90"
    result = subprocess.run(
        [str(OFORT), "--no-implicit-typing", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Variable 'i' has no implicit type" in result.stderr


def test_implicit_typing_option_allows_legacy_default():
    source = CASES / "ximplicit_default.f90"
    result = subprocess.run(
        [str(OFORT), "--implicit-typing", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2"]
    assert result.stderr == ""


def test_command_arguments_from_file_mode(tmp_path):
    source = tmp_path / "xargs.f90"
    source.write_text(
        "program xargs\n"
        "implicit none\n"
        "integer :: n, length, status\n"
        "character(len=8) :: arg\n"
        "n = command_argument_count()\n"
        "print *, n\n"
        "call get_command_argument(1, arg, length, status)\n"
        "print *, trim(arg), length, status\n"
        "call get_command_argument(2, arg, length, status)\n"
        "print *, trim(arg), length, status\n"
        "end program xargs\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source), "--", "alpha", "longer_than_8"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "2",
        "alpha 5 0",
        "longer_t 13 -1",
    ]


def test_getarg_extension_from_file_mode(tmp_path):
    source = tmp_path / "xgetarg.f90"
    source.write_text(
        "program xgetarg\n"
        "implicit none\n"
        "character(len=8) :: arg\n"
        "call getarg(1, arg)\n"
        "print *, trim(arg)\n"
        "end program xgetarg\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source), "--", "alpha"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "alpha"
    assert "warning: nonstandard GETARG extension; prefer GET_COMMAND_ARGUMENT" in result.stderr


def test_w_option_suppresses_getarg_warning(tmp_path):
    source = tmp_path / "xgetarg.f90"
    source.write_text(
        "program xgetarg\n"
        "implicit none\n"
        "character(len=8) :: arg\n"
        "call getarg(1, arg)\n"
        "print *, trim(arg)\n"
        "end program xgetarg\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "-w", str(source), "--", "alpha"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "alpha"
    assert result.stderr == ""


def test_multiple_source_files_are_concatenated(tmp_path):
    first = tmp_path / "part1.f90"
    second = tmp_path / "part2.f90"
    first.write_text(
        "program xmulti\n"
        "implicit none\n"
        "integer :: i\n"
        "i = 6\n",
        encoding="utf-8",
    )
    second.write_text(
        "print *, i * 7\n"
        "end program xmulti\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(first), str(second)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.split() == ["42"]


def test_private_module_names_are_not_imported(tmp_path):
    source = tmp_path / "xprivate_hidden.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "private\n"
        "public :: pi\n"
        "real :: pi = 3.14\n"
        "real :: hidden = 2.0\n"
        "end module m\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "print *, hidden\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Undefined variable 'hidden'" in result.stderr


def test_protected_module_variable_cannot_be_assigned_after_use(tmp_path):
    source = tmp_path / "xprotected_assign.f90"
    source.write_text(
        "module m\n"
        "implicit none\n"
        "real, protected :: pi = 3.14\n"
        "end module m\n"
        "program main\n"
        "use m\n"
        "implicit none\n"
        "pi = 4.0\n"
        "print *, pi\n"
        "end program main\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Cannot assign to PROTECTED variable 'pi'" in result.stderr


def test_save_warns_for_implicit_save_local():
    source = CASES / "xsave.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert "warning: local variable 'mcall' has implicit SAVE due to initialization" in result.stderr
    assert "integer :: mcall = 0" in result.stderr
    assert "ncall" not in result.stderr


def test_w_option_suppresses_warnings():
    source = CASES / "xsave.f90"
    result = subprocess.run(
        [str(OFORT), "-w", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_implicit_external_unit_warns(tmp_path):
    source = tmp_path / "ximplicit_unit.f90"
    source.write_text(
        "integer :: i, j\n"
        "write(12,*) 70, 80\n"
        "rewind 12\n"
        "read(12,*) i, j\n"
        "print *, i, j\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "70 80\n"
    assert "warning: implicit external unit 12 uses default file 'fort.12'; prefer OPEN with FILE=" in result.stderr
    assert (tmp_path / "fort.12").read_text(encoding="utf-8") == "70 80\n"


def test_w_option_suppresses_implicit_external_unit_warning(tmp_path):
    source = tmp_path / "ximplicit_unit.f90"
    source.write_text(
        "integer :: i, j\n"
        "write(12,*) 70, 80\n"
        "rewind 12\n"
        "read(12,*) i, j\n"
        "print *, i, j\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "-w", str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "70 80\n"
    assert result.stderr == ""


def test_fast_option_suppresses_warnings_and_preserves_output():
    source = CASES / "xsave.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_real_star_8_extension_warns_and_runs(tmp_path):
    source = tmp_path / "xreal_star_8.f90"
    source.write_text(
        "real*8 :: x\n"
        "x = 1.25d0\n"
        "print *, kind(x), x\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "8 1.25\n"
    assert "warning: nonstandard REAL*8 treated as REAL(KIND=8) extension" in result.stderr


def test_w_option_suppresses_real_star_8_warning(tmp_path):
    source = tmp_path / "xreal_star_8.f90"
    source.write_text(
        "real*8 :: x\n"
        "x = 1.25d0\n"
        "print *, kind(x), x\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(OFORT), "-w", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "8 1.25\n"
    assert result.stderr == ""


def test_fast_option_preserves_counted_do_loop_result():
    source = CASES / "xlarge_do_loop.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_initialized_arrays():
    source = CASES / "xarray_init.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_rank2_array_expressions():
    source = CASES / "xfast_rank2_array_expr.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_aliases_array_dummy_arguments():
    source = CASES / "xfast_array_dummy_alias.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_reuses_local_array_storage_safely():
    source = CASES / "xfast_local_array_reuse.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_nested_numeric_do_loops():
    source = CASES / "xfast_numeric_do_loop.f90"
    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert result.stderr == ""


def test_fast_option_handles_array_random_number_and_sum(tmp_path):
    source = tmp_path / "xfast_array.f90"
    source.write_text(
        "integer, parameter :: n = 1000\n"
        "real :: x(n)\n"
        "call random_number(x)\n"
        "print *, sum(x) / size(x)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    mean = float(result.stdout.strip())
    assert 0.0 <= mean <= 1.0


def test_fast_random_number_advances_state(tmp_path):
    source = tmp_path / "xfast_random_state.f90"
    source.write_text(
        "real :: x\n"
        "call random_number(x)\n"
        "print *, x\n"
        "call random_number(x)\n"
        "print *, x\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    values = [float(line) for line in result.stdout.splitlines()]
    assert len(values) == 2
    assert all(0.0 <= value < 1.0 for value in values)
    assert values[0] != values[1]


def test_fast_packed_array_reads_default_numeric_element(tmp_path):
    source = tmp_path / "xfast_packed_default.f90"
    source.write_text(
        "real :: x(3)\n"
        "print *, kind(x(1)), x(1)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "4 0\n"


def test_fast_packed_array_power_can_be_summed(tmp_path):
    source = tmp_path / "xfast_packed_power_sum.f90"
    source.write_text(
        "real :: x(3)\n"
        "x(1) = 1.0\n"
        "x(2) = 2.0\n"
        "x(3) = 3.0\n"
        "print *, sum(x), sum(x**2)\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "6 14\n"


def test_fast_scalar_numeric_update(tmp_path):
    source = tmp_path / "xfast_scalar_update.f90"
    source.write_text(
        "real :: x, xsum\n"
        "integer :: i\n"
        "x = 0.25\n"
        "xsum = 0.0\n"
        "do i = 1, 4\n"
        "  xsum = xsum + x\n"
        "end do\n"
        "print *, xsum\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "1\n"


def test_fast_random_sum_loop_pattern(tmp_path):
    source = tmp_path / "xfast_random_sum_loop.f90"
    source.write_text(
        "integer, parameter :: n = 1000\n"
        "real :: x, xsum\n"
        "integer :: i\n"
        "xsum = 0.0\n"
        "do i = 1, n\n"
        "  call random_number(x)\n"
        "  xsum = xsum + x\n"
        "end do\n"
        "print *, i, xsum/n\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--fast", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    fields = result.stdout.split()
    assert int(fields[0]) == 1001
    assert 0.0 <= float(fields[1]) < 1.0


def test_time_option_reports_execution_time_without_changing_stdout():
    source = CASES / "xtry.f90"
    result = subprocess.run(
        [str(OFORT), "--time", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert re.search(r"(?m)^time: \d+\.\d{6} s$", result.stderr)


def test_profile_lines_reports_statement_times(tmp_path):
    source = tmp_path / "xprofile.f90"
    source.write_text(
        "integer :: i\n"
        "i = 2\n"
        "print *, i**5\n"
        "end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--profile-lines", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "32\n"
    assert "line profile:" in result.stderr
    assert re.search(r"(?m)^\s*2\s+1\s+\d+\.\d{6}\s+i = 2$", result.stderr)
    assert re.search(r"(?m)^\s*3\s+1\s+\d+\.\d{6}\s+print \*, i\*\*5$", result.stderr)


def test_time_option_reports_check_time_without_changing_stdout(tmp_path):
    source = tmp_path / "xcheck_time.f90"
    source.write_text(
        "program xcheck_time\n"
        "print *, 12345\n"
        "end program xcheck_time\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--time", "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "ofort check passed\n"
    assert re.search(r"(?m)^time: \d+\.\d{6} s$", result.stderr)


def assert_time_detail(stderr):
    assert re.search(
        r"(?m)^time:\n"
        r"  setup:    \d+\.\d{6} s\n"
        r"  lex:      \d+\.\d{6} s\n"
        r"  parse:    \d+\.\d{6} s\n"
        r"  register: \d+\.\d{6} s\n"
        r"  execute:  \d+\.\d{6} s\n"
        r"  total:    \d+\.\d{6} s$",
        stderr,
    )


def test_time_detail_option_reports_execution_breakdown_without_changing_stdout():
    source = CASES / "xtry.f90"
    result = subprocess.run(
        [str(OFORT), "--time-detail", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.with_suffix(".out").read_text(encoding="utf-8")
    assert_time_detail(result.stderr)


def test_time_detail_option_reports_check_breakdown_without_changing_stdout(tmp_path):
    source = tmp_path / "xcheck_time_detail.f90"
    source.write_text(
        "program xcheck_time_detail\n"
        "print *, 12345\n"
        "end program xcheck_time_detail\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--time-detail", "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "ofort check passed\n"
    assert_time_detail(result.stderr)


def test_repl_warns_when_implicit_save_line_is_entered(tmp_path):
    source = tmp_path / "empty.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input="subroutine s()\ninteger :: n = 0\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "warning: local variable 'n' has implicit SAVE due to initialization" in result.stderr


def test_w_option_suppresses_repl_implicit_save_warning(tmp_path):
    source = tmp_path / "empty.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "-w", "--load", str(source)],
        cwd=ROOT,
        input="subroutine s()\ninteger :: n = 0\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_repl_run_repeats_with_command_arguments(tmp_path):
    source = tmp_path / "xrun.f90"
    source.write_text(
        "program xrun\n"
        "implicit none\n"
        "print *, command_argument_count()\n"
        "end program xrun\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".run 2 -- aa bb\n.runq 1 -- cc\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    numeric_lines = re.findall(r"(?m)^(?:ofort>\s*)?([0-9]+)$", result.stdout)
    assert numeric_lines == ["2", "2", "1"]


def test_repl_time_repeats_and_prints_summary(tmp_path):
    source = tmp_path / "xtime.f90"
    source.write_text(
        "program xtime\n"
        "print *, 123\n"
        "end program xtime\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".time 2\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    numeric_lines = re.findall(r"(?m)^(?:ofort>\s*)?(123)$", result.stdout)
    assert numeric_lines == ["123", "123"]
    assert re.search(r"(?m)^\s+total\s+avg\s+sd\s+min\s+max$", result.stdout)
    assert re.search(
        r"(?m)^\s*\d+\.\d{6}\s+\d+\.\d{6}\s+\d+\.\d{6}\s+\d+\.\d{6}\s+\d+\.\d{6} s$",
        result.stdout,
    )


def test_repl_time_single_run_prints_only_total(tmp_path):
    source = tmp_path / "xtime1.f90"
    source.write_text(
        "program xtime1\n"
        "print *, 456\n"
        "end program xtime1\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".time\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert re.search(r"(?m)^(?:ofort>\s*)?456$", result.stdout)
    assert re.search(r"(?m)^\s+total$", result.stdout)
    assert re.search(r"(?m)^\s*\d+\.\d{6} s$", result.stdout)
    assert not re.search(r"(?m)^\s+total\s+avg\s+sd\s+min\s+max$", result.stdout)


def test_repl_vars_lists_all_and_selected_values(tmp_path):
    source = tmp_path / "xvars.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x\n"
            "i = 2\n"
            "x = 3.5\n"
            ".vars\n"
            ".vars i x missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("i = 2") == 2
    assert result.stdout.count("x = 3.5") == 2
    assert "missing: undefined" in result.stdout


def test_repl_info_lists_declaration_style_details(tmp_path):
    source = tmp_path / "xinfo.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x(5)\n"
            "i = 2\n"
            "x = [1,2,3,4,5]\n"
            ".info\n"
            ".info x i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("integer i: 2") == 2
    assert result.stdout.count("real x(5): 1 2 3 4 5") == 2
    assert "missing: undefined" in result.stdout


def test_repl_shapes_lists_array_shapes(tmp_path):
    source = tmp_path / "xshapes.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x(5)\n"
            "real :: y(3,2)\n"
            "i = 2\n"
            "x = [1,2,3,4,5]\n"
            "y = [1,2,3,4,5,6]\n"
            ".shapes\n"
            ".shapes x y i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("x: 5") == 2
    assert result.stdout.count("y: 3 2") == 2
    assert "i: scalar" in result.stdout
    assert "missing: undefined" in result.stdout


def test_repl_sizes_lists_array_sizes(tmp_path):
    source = tmp_path / "xsizes.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "real :: x(5)\n"
            "real :: y(3,2)\n"
            "i = 2\n"
            "x = [1,2,3,4,5]\n"
            "y = [1,2,3,4,5,6]\n"
            ".sizes\n"
            ".sizes x y i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("x: 5") == 2
    assert result.stdout.count("y: 6") == 2
    assert "i: scalar" in result.stdout
    assert "missing: undefined" in result.stdout


def test_repl_stats_lists_grouped_array_tables(tmp_path):
    source = tmp_path / "xstats.f90"
    source.write_text("", encoding="utf-8")

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            "integer :: i\n"
            "integer :: ia(5)\n"
            "real :: x(5)\n"
            "i = 2\n"
            "ia = [1,2,3,4,5]\n"
            "x = [2,4,6,8,10]\n"
            ".stats\n"
            ".stats x ia i missing\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("integer arrays") == 2
    assert result.stdout.count("real arrays") == 2
    assert result.stdout.count("name                 size") == 4
    assert re.search(r"(?m)^ia\s+5\s+1\s+5\s+3\s+1\.581139\s+1\s+5$", result.stdout)
    assert re.search(r"(?m)^x\s+5\s+2\s+10\s+6\s+3\.162278\s+2\s+10$", result.stdout)
    assert "i: scalar" in result.stdout
    assert "missing: undefined" in result.stdout


def test_repl_del_deletes_lines_and_ranges(tmp_path):
    source = tmp_path / "xdel.f90"
    source.write_text(
        "program xdel\n"
        "integer :: i\n"
        "i = 1\n"
        "print *, i\n"
        "i = 2\n"
        "print *, i\n"
        "end program xdel\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".del 5\n.del 3:4\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   1  program xdel\n" in result.stdout
    assert "   2    integer :: i\n" in result.stdout
    assert "   3    print *, i\n" in result.stdout
    assert "   4  end program xdel\n" in result.stdout
    assert "   4    i = 1\n" not in result.stdout
    assert "i = 2" not in result.stdout


def test_repl_del_open_ended_ranges(tmp_path):
    source = tmp_path / "xdelopen.f90"
    source.write_text(
        "program xdelopen\n"
        "integer :: i\n"
        "i = 1\n"
        "print *, i\n"
        "end program xdelopen\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".del :2\n.list\n.del 2:\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   1  i = 1\n" in result.stdout
    assert "   2  print *, i\n" in result.stdout
    assert "end program xdelopen" in result.stdout
    assert result.stdout.count("   1  i = 1\n") == 2
    assert "   2  end program xdelopen\n" in result.stdout


def test_repl_del_rejects_footer_line(tmp_path):
    source = tmp_path / "xdelfooter.f90"
    source.write_text(
        "program xdelfooter\n"
        "print *, 1\n"
        "end program xdelfooter\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".del 3\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".del range is outside the editable source buffer" in result.stderr
    assert "   3  end program xdelfooter\n" in result.stdout


def test_repl_ins_and_rep_edit_lines(tmp_path):
    source = tmp_path / "xedit.f90"
    source.write_text(
        "program xedit\n"
        "integer :: i\n"
        "i = 1\n"
        "print *, i\n"
        "end program xedit\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=(
            ".ins 3 integer :: j\n"
            ".rep 4 i = 10\n"
            ".ins 6 print *, i\n"
            ".list\n"
            ".clear\n"
            ".quit\n"
        ),
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   1  program xedit\n" in result.stdout
    assert "   2    integer :: i\n" in result.stdout
    assert "   3    integer :: j\n" in result.stdout
    assert "   4    i = 10\n" in result.stdout
    assert "   5    print *, i\n" in result.stdout
    assert "   6    print *, i\n" in result.stdout
    assert "   7  end program xedit\n" in result.stdout
    assert "   4    i = 1\n" not in result.stdout


def test_repl_ins_rep_reject_footer_line(tmp_path):
    source = tmp_path / "xeditfooter.f90"
    source.write_text(
        "program xeditfooter\n"
        "print *, 1\n"
        "end program xeditfooter\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rep 3 end\n.ins 4 print *, 2\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".rep line is outside the editable source buffer" in result.stderr
    assert ".ins line is outside the editable source buffer" in result.stderr
    assert "   3  end program xeditfooter\n" in result.stdout


def test_repl_rename_variable_tokens(tmp_path):
    source = tmp_path / "xrename.f90"
    source.write_text(
        "program xrename\n"
        "integer :: i\n"
        "integer :: idx\n"
        "i = 2\n"
        "print *, i, idx\n"
        "print *, \"i should stay\"\n"
        "! i should stay in comment\n"
        "end program xrename\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rename i j\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "integer :: j" in result.stdout
    assert "integer :: idx" in result.stdout
    assert "j = 2" in result.stdout
    assert "print *, j, idx" in result.stdout
    assert '"i should stay"' in result.stdout
    assert "! i should stay in comment" in result.stdout
    assert "   2    integer :: i\n" not in result.stdout
    assert "   4    i = 2\n" not in result.stdout


def test_repl_rename_rejects_existing_name(tmp_path):
    source = tmp_path / "xrename_conflict.f90"
    source.write_text(
        "program xrename_conflict\n"
        "integer :: i\n"
        "integer :: j\n"
        "i = 2\n"
        "end program xrename_conflict\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rename i j\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".rename: j already exists" in result.stderr
    assert "integer :: i" in result.stdout
    assert "integer :: j" in result.stdout
    assert "i = 2" in result.stdout


def test_repl_rename_rejects_missing_old_name(tmp_path):
    source = tmp_path / "xrename_missing.f90"
    source.write_text(
        "program xrename_missing\n"
        "integer :: i\n"
        "i = 2\n"
        "end program xrename_missing\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".rename k j\n.list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert ".rename: k not found" in result.stderr
    assert "integer :: i" in result.stdout
    assert "i = 2" in result.stdout


def test_repl_decl_lists_declaration_lines(tmp_path):
    source = tmp_path / "xdecl.f90"
    source.write_text(
        "program xdecl\n"
        "implicit none\n"
        "integer :: i\n"
        "real :: x(2)\n"
        "i = 2\n"
        "print *, i\n"
        "end program xdecl\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".decl\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   2    implicit none\n" in result.stdout
    assert "   3    integer :: i\n" in result.stdout
    assert "   4    real :: x(2)\n" in result.stdout
    assert "i = 2" not in result.stdout
    assert "print *, i" not in result.stdout


def test_repl_list_auto_indents_blocks(tmp_path):
    source = tmp_path / "xindent.f90"
    source.write_text(
        "program x\n"
        "integer :: i\n"
        "do i = 1, 2\n"
        "if (i == 1) then\n"
        "print *, i\n"
        "else\n"
        "print *, -i\n"
        "end if\n"
        "end do\n"
        "end program x\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--load", str(source)],
        cwd=ROOT,
        input=".list\n.clear\n.quit\n",
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "   3    do i = 1, 2\n" in result.stdout
    assert "   4      if (i == 1) then\n" in result.stdout
    assert "   5        print *, i\n" in result.stdout
    assert "   6      else\n" in result.stdout
    assert "   8      end if\n" in result.stdout
    assert "   9    end do\n" in result.stdout
    assert "  10  end program x\n" in result.stdout


def test_rejects_type_changing_assignment():
    source = CASES / "xtype_change.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Cannot assign CHARACTER to INTEGER variable 'i'" in result.stderr
    assert 'line 4: i = "a"' in result.stderr


def test_write_and_read_external_file(tmp_path):
    source = CASES / "xwrite_file.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ichk =  10 20 30\nsum(abs(i-ichk)) =  0\n"
    assert (tmp_path / "temp.txt").read_text(encoding="utf-8") == "10 20 30\n"


def test_write_read_internal_file_and_allocatable(tmp_path):
    source = CASES / "xwrite_file_alloc.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ichk =  10.1 20.1 30.1\nsum(abs(i-ichk)) =  0\n"
    assert (tmp_path / "temp.txt").read_text(encoding="utf-8") == "3 10.1 20.1 30.1\n"


def test_unformatted_stream_io(tmp_path):
    source = CASES / "xstream.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ichk =  10.1 20.1 30.1\nsum(abs(i-ichk)) =  0\n"
    assert (tmp_path / "temp.bin").read_text(encoding="utf-8") == "3\n10.1\n20.1\n30.1\n"


def test_exit_from_unbounded_do_loop():
    source = CASES / "xexit.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines
    assert lines[-1].startswith("big ")
    assert float(lines[-1].split()[1]) > 0.9
    for line in lines[:-1]:
        assert 0.0 <= float(line) <= 0.9


def test_check_parses_without_running(tmp_path):
    source = tmp_path / "xcheck.f90"
    source.write_text(
        "program xcheck\n"
        "print *, 12345\n"
        "end program xcheck\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ofort check passed\n"


def test_check_rejects_syntax_error(tmp_path):
    source = tmp_path / "xbad.f90"
    source.write_text(
        "program xbad\n"
        "print *, (1\n"
        "end program xbad\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr != ""


def test_check_skips_generic_interface_block(tmp_path):
    source = tmp_path / "xinterface.f90"
    source.write_text(
        "module m\n"
        "interface g\n"
        "  module procedure s\n"
        "end interface g\n"
        "contains\n"
        "subroutine s()\n"
        "end subroutine s\n"
        "end module m\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ofort check passed\n"


def test_check_accepts_utf8_bom(tmp_path):
    source = tmp_path / "xbom.f90"
    source.write_bytes(
        b"\xef\xbb\xbfprogram xbom\n"
        b"print *, 1\n"
        b"end program xbom\n"
    )

    result = subprocess.run(
        [str(OFORT), "--check", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "ofort check passed\n"


def test_typed_function_prefixes():
    source = CASES / "xtyped_function.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "6\n7.5\n"


def test_type_keyword_intrinsic_call():
    source = CASES / "xtype_keyword_intrinsic.f90"
    result = subprocess.run(
        [str(OFORT), str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "3 4\n"


def test_batch_runner_runs_file_glob(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "==> " in result.stdout
    assert "a.f90" in result.stdout
    assert "b.f90" in result.stdout
    assert "(1 lines)" in result.stdout
    assert "\n\n==> " in result.stdout
    assert "11" in result.stdout
    assert "22" in result.stdout
    assert re.search(r"2 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_forwards_check(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--check", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.count("ofort check passed") == 2
    output_lines = result.stdout.splitlines()
    assert "11" not in output_lines
    assert "22" not in output_lines
    assert re.search(r"2 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_limit(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\n", encoding="utf-8")
    (tmp_path / "c.f90").write_text("print *, 33\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--limit", "2", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    output_lines = result.stdout.splitlines()
    assert "11" in output_lines
    assert "22" in output_lines
    assert "33" not in output_lines
    assert re.search(r"2 passed in \d+\.\d{2}s", result.stdout)


def test_batch_runner_max_lines_skips_long_files(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text(
        "print *, 22\n"
        "print *, 33\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--max-lines", "1", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "a.f90" in result.stdout
    assert "(1 lines)" in result.stdout
    output_lines = result.stdout.splitlines()
    assert "11" in output_lines
    assert "b.f90" not in result.stdout
    assert "22" not in output_lines
    assert "(2 lines)" not in result.stdout
    assert "skipped: longer than 1 lines" not in result.stdout
    assert re.search(r"1 passed, 1 skipped in \d+\.\d{2}s", result.stdout)


def test_batch_runner_quiet_suppresses_success_output(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("print *, 22\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--quiet", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_batch_runner_filter_skips_rejected_files(tmp_path):
    good = tmp_path / "good.f90"
    bad = tmp_path / "bad.f90"
    filter_script = tmp_path / "filter.py"
    good.write_text("print *, 11\n", encoding="utf-8")
    bad.write_text("print *, 22\n", encoding="utf-8")
    filter_script.write_text(
        "import pathlib\n"
        "import sys\n"
        "raise SystemExit(0 if pathlib.Path(sys.argv[-1]).name == 'good.f90' else 1)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--filter",
            f'"{sys.executable}" "{filter_script}"',
            str(tmp_path / "*.f90"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "good.f90" in result.stdout
    output_lines = result.stdout.splitlines()
    assert "11" in output_lines
    assert "bad.f90" not in result.stdout
    assert "22" not in output_lines
    assert re.search(r"1 passed, 1 skipped in \d+\.\d{2}s", result.stdout)


def test_batch_runner_quiet_prints_failed_files(tmp_path):
    good = tmp_path / "good.f90"
    bad = tmp_path / "bad.f90"
    fake_ofort = tmp_path / "fake_ofort.bat"
    good.write_text("print *, 11\n", encoding="utf-8")
    bad.write_text("print *, 22\n", encoding="utf-8")
    fake_ofort.write_text(
        "@echo off\n"
        "echo handled %~nx1\n"
        "echo problem %~nx1 1>&2\n"
        "if /I \"%~nx1\"==\"bad.f90\" exit /b 1\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--quiet",
            "--ofort",
            str(fake_ofort),
            str(tmp_path / "*.f90"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "bad.f90" in result.stdout
    assert "handled bad.f90" in result.stdout
    assert "good.f90" not in result.stdout
    assert "handled good.f90" not in result.stdout
    assert "problem bad.f90" in result.stderr
    assert "problem good.f90" not in result.stderr
    assert re.search(r"1 of 2 failed in \d+\.\d{2}s", result.stderr)


def test_batch_runner_rejects_bad_limit(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--limit", "0", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--limit must be at least 1" in result.stderr


def test_batch_runner_times_out_file(tmp_path):
    source = tmp_path / "a.f90"
    fake_ofort = tmp_path / "fake_ofort.bat"
    source.write_text("print *, 11\n", encoding="utf-8")
    fake_ofort.write_text(
        "@echo off\n"
        f"\"{sys.executable}\" -c \"import time; time.sleep(2)\"\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--ofort",
            str(fake_ofort),
            "--timeout",
            "0.1",
            str(source),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "==> " in result.stdout
    assert "(1 lines)" in result.stdout
    assert "timed out after 0.1 seconds" in result.stderr
    assert re.search(r"1 of 1 failed in \d+\.\d{2}s", result.stderr)


def test_batch_runner_rejects_bad_timeout(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--timeout", "-1", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--timeout must be non-negative" in result.stderr


def test_batch_runner_rejects_bad_max_lines(tmp_path):
    (tmp_path / "a.f90").write_text("print *, 11\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--max-lines", "-1", str(tmp_path / "*.f90")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--max-lines must be non-negative" in result.stderr
