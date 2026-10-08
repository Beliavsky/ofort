"""Build the browser interpreter with Emscripten, without changing native builds."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emcc", default="emcc", help="Emscripten compiler command or path")
    args = parser.parse_args()
    compiler = shutil.which(args.emcc)
    if not compiler:
        parser.error("emcc not found; activate emsdk_env.bat in this terminal first")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "scripts/write_build_version.py"], cwd=root, check=True)
    sources = ["ofort.c", "ofort_values.c", "ofort_stats.c", "ofort_fixed_form.c",
               "ofort_lapack.c", "ofort_c_api.c"]
    exports = ["ofort_c_create", "ofort_c_destroy", "ofort_c_execute",
               "ofort_c_set_fast_mode", "ofort_get_output", "ofort_get_error",
               "ofort_get_warnings", "ofort_web_build_info", "ofort_c_reset",
               "ofort_web_repl_create", "ofort_web_repl_variables",
               "ofort_execute_auto_declare", "ofort_get_auto_declaration"]
    command = [compiler, "-O2", "-Iinclude", "-DOFORT_MAX_MODULES=16",
               *["src/" + name for name in sources], "web/build_info.c", "web/repl.c",
               "-lm", "--no-entry", "-sMODULARIZE=1", "-sEXPORT_NAME=createOfortModule",
               "-sENVIRONMENT=worker", "-sALLOW_MEMORY_GROWTH=1",
               "-sINITIAL_MEMORY=67108864", "-sMAXIMUM_MEMORY=1073741824",
               "-sSTACK_SIZE=16777216", "-sFORCE_FILESYSTEM=1",
               "-sEXPORTED_FUNCTIONS=" + json.dumps(["_" + name for name in exports]),
               '-sEXPORTED_RUNTIME_METHODS=["ccall","UTF8ToString","FS"]',
               "-o", "web/ofort.js"]
    subprocess.run(command, cwd=root, check=True)
    print("Built web/ofort.js and web/ofort.wasm")
    print("Serve with: python -m http.server 8000 --directory web")


if __name__ == "__main__":
    main()
