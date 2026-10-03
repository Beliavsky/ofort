"""Private xp2f worker; retain translator caches without sharing REPL state."""

import contextlib
import importlib.util
import io
import json
import os
import sys
import traceback
from pathlib import Path


def main() -> None:
    translator = Path(sys.argv[1]).resolve()
    sys.pycache_prefix = sys.argv[2]
    sys.path.insert(0, str(translator.parent))
    protocol_input, protocol_output = sys.stdin, sys.stdout
    module = None
    for request in protocol_input:
        output, errors = io.StringIO(), io.StringIO()
        previous_argv = sys.argv
        previous_directory = os.getcwd()
        status = 0
        try:
            sys.argv = [str(translator), *json.loads(request)]
            sys.stdin = io.StringIO("")
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                try:
                    if module is None:
                        spec = importlib.util.spec_from_file_location("_opy_translator", translator)
                        loaded = importlib.util.module_from_spec(spec)
                        sys.modules[spec.name] = loaded
                        spec.loader.exec_module(loaded)
                        module = loaded
                    result = module.main()
                    status = result if isinstance(result, int) else 0
                except SystemExit as exc:
                    if isinstance(exc.code, int):
                        status = exc.code
                    elif exc.code is not None:
                        status = 1
                        print(exc.code, file=sys.stderr)
                except Exception:
                    status = 1
                    traceback.print_exc()
        finally:
            sys.stdin = protocol_input
            sys.argv = previous_argv
            os.chdir(previous_directory)
        protocol_output.write(json.dumps({
            "returncode": status, "stdout": output.getvalue(), "stderr": errors.getvalue(),
        }) + "\n")
        protocol_output.flush()


if __name__ == "__main__":
    main()
