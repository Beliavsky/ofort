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

## Initial scope

- Free-form complete programs, examples, and source download.
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
  execution are unavailable. This is not the full interactive REPL.
- Output is returned when execution ends, not streamed; stopping discards output.
- Data-file upload/download and persistent sessions are not implemented yet.
- The page fetches its fonts from Google Fonts; source and input stay local.
- CodeMirror 5.65.20 and its Fortran mode are fetched from cdnjs. If those scripts
  cannot load, the editor falls back to the original plain textarea. For offline
  hosting, vendor these assets and update the URLs in index.html.

The WebAssembly build needs its own browser testing before public deployment.
Native pytest results alone do not establish browser compatibility.
