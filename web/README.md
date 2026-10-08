# Browser playground (experimental)

This standalone static frontend uses the existing C embedding API. It does not
send programs to a server and does not change the native executable's build.

## Build and serve

Activate Emscripten in the same terminal, then run from the repository root:

```cmd
call C:\c\public_domain\github\emsdk\emsdk_env.bat
python web/build.py
python -m http.server 8000 --directory web
```

Open http://localhost:8000. Do not open index.html as a file URL.
An explicit compiler path can be supplied with `--emcc`.

After a successful build, the contents of `web` can be served by a static host,
including GitHub Pages. Include the generated ofort.js and ofort.wasm in the
deployment; they are ignored in the source repository. Serve .wasm files with
the application/wasm MIME type. No server-side program execution is needed.

## Automatic GitHub Pages deployment

In the repository's **Settings > Pages**, select **GitHub Actions** as the
source once. The `Deploy playground` workflow then builds and publishes `web`
on every push to `main`. It can also be started manually from the Actions tab.

The workflow installs Emscripten 6.0.11 and runs `python3 web/build.py`, so
committed interpreter changes are included along with frontend changes.
Generated `ofort.js` and `ofort.wasm` do not need to be committed. Manual
copying to the `gh-pages` branch is no longer needed.

Follow the deployment in the Actions tab, then open
https://beliavsky.github.io/ofort/. If an already-open page shows the previous
version, reload it with Ctrl+F5; this also restarts its interpreter worker.

## Initial scope

- Free-form complete programs, examples, and source download.
- Clear code empties only the source editor; the editor's Undo restores it.
- A Focus mode toggle hides the header and introduction and expands the editor
  and results panes without hiding the toolbar or standard input.
- Report a bug opens an editable preview with output, diagnostics, browser
  information, Fast mode, and the interpreter's embedded build identifier.
  Source inclusion is opt-in and uses the last run's source; standard input is
  never added automatically. GitHub issues are public, so remove sensitive
  information before opening an issue. Large reports can be downloaded rather
  than put into a URL. A GitHub account is needed to submit an issue.
  Toggling source inclusion preserves other preview edits. If the source section
  itself has been edited, change it manually to avoid overwriting redactions.
- Fortran syntax coloring and line numbers using CodeMirror, with four-space
  indentation, Tab/Shift-Tab, and Ctrl+Enter (Cmd+Enter on macOS) to run.
  No automatic code transformations are performed.
- Standard input supplied before Run, output, warnings, and errors.
- Fast mode and a worker that can be terminated with Stop.
- Fresh interpreter and temporary virtual filesystem for every run.
- A browser-specific limit of 16 modules, avoiding the large preallocated native
  module table. Native builds retain their existing 256-module limit.
- A 30-second limit, including module loading; timing shown covers execution.
- Native LAPACK, native shared libraries, external compilers, and OS command
  execution are unavailable.
- Output is returned when execution ends, not streamed; stopping discards output.
- Data-file upload/download and saving sessions across page reloads are not implemented yet.
- The page fetches its fonts from Google Fonts; source and input stay local.
- CodeMirror 5.65.20 and its Fortran mode are fetched from cdnjs. If those scripts
  cannot load, the editor falls back to the original plain textarea. For offline
  hosting, vendor these assets and update the URLs in index.html.

The WebAssembly build needs its own browser testing before public deployment.
Native pytest results alone do not establish browser compatibility.

## REPL sessions

Choose **REPL session** in the toolbar. Enter standard Fortran one line at a
time; Enter submits and Shift+Enter adds a line. Pasted multi-line input is
accepted. Up/Down recalls earlier submissions. The source pane shows accepted
code and pending blocks; output and variable information appear alongside it.
Variable previews show all elements of arrays of six elements or fewer;
larger arrays show the first three and last three, separated by `...`.
Multi-dimensional arrays use Fortran element order. Each previewed unset
element, and each unset scalar, is shown as `<unset>`, not a default zero or
NaN. An explicitly assigned IEEE NaN remains a value, distinct from `<unset>`.
Previews inspect initialization metadata without evaluating unset values,
emitting diagnostics, or changing state. Unallocated storage is labeled
`<unallocated>` and unassociated pointers are labeled `<unassociated>`.

The WebAssembly interpreter stays alive between submissions. Only new code
executes: previous assignments, random-number calls and file writes are not
automatically repeated. Implicit typing is disabled, initialization checking
is enabled, and bare expressions print their value. Blocks wait for their
matching END, and trailing `&` waits for continuation. Use modern END DO loops;
labeled DO termination and continued character literals are not supported by
the browser's initial block-buffering interface.

Session source groups top-level USE/IMPORT statements, IMPLICIT statements,
and declarations before executable code, preserving order within each group.
Declarations inside submitted procedures or blocks stay inside those units.
Bare expressions such as `i**5` are stored as `print *, i**5`. These changes
affect source display, listing, download, and explicit replay, not the order
in which newly entered code executes. The terminal REPL already moves ordinary
top-level declarations before executable statements.

Available browser commands:

- `.vars` and `.info` show current variable information.
- `.list` and `.list -n` show accumulated source with or without line numbers.
- `.run` or `.` explicitly restarts the interpreter and replays accumulated
  source. This can repeat side effects and change random data.
- `.clear` resets source and interpreter state, retaining temporary files.
- `.help` lists supported commands.

**Clear session** also discards the worker and temporary filesystem. Stop,
timeouts, switching modes, and page reloads discard interpreter state. Each
submission has a 30-second limit. Download source saves the reordered session
source with bare expression shortcuts converted to PRINT statements. It adds
a final END unless the source already ends with END or END PROGRAM, so a
completed loose-code session can be compiled as an implicit main program.
Native REPL shortcuts such as `const`, `.timec`, source editing commands, and
save/load-state are not implemented in this first browser interface.

A rejected submission is not added to accumulated source. Runtime errors are
not transactional: earlier statements in that submission may have changed
state. Clear session if a clean restart is needed. Directly evaluating an unset
variable still produces the interpreter's normal initialization diagnostic.

Rebuild `ofort.js` and `ofort.wasm` with `python web/build.py` before using REPL
mode; the new browser adapters are not present in older generated builds.
