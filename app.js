"use strict";
const byId = id => document.getElementById(id);
const examples = {
  hello: 'program hello\nimplicit none\nprint *, "Hello from ofort in your browser!"\nend program hello\n',
  arrays: 'program arrays\nimplicit none\ninteger :: i\nreal(kind=8) :: x(5)\nx = [(real(i, kind=8), i=1,5)]\nprint *, "x =", x\nprint *, "sum =", sum(x)\nprint *, "mean =", sum(x)/size(x)\nend program arrays\n',
  input: 'program input_demo\nimplicit none\ninteger :: n, ios\nread(*, *, iostat=ios) n\nif (ios == 0) then\n  print *, "Your number squared:", n*n\nelse\n  print *, "Supply an integer in the standard input box."\nend if\nend program input_demo\n'
};
let worker = null;
let timer = null;
let lastRun = null;
function finish(status) {
  if (worker) worker.terminate();
  worker = null;
  clearTimeout(timer);
  byId("run").disabled = false;
  byId("stop").disabled = true;
  byId("status").textContent = status;
}
byId("source").value = examples.hello;
const editor = typeof CodeMirror === "function" ? CodeMirror.fromTextArea(byId("source"), {
  mode: "text/x-fortran",
  theme: "ofort",
  lineNumbers: true,
  indentUnit: 4,
  tabSize: 4,
  indentWithTabs: false,
  lineWrapping: true,
  extraKeys: {
    "Ctrl-Enter": () => { if (!worker) byId("run").click(); },
    "Cmd-Enter": () => { if (!worker) byId("run").click(); },
    "Tab": cm => {
      if (cm.somethingSelected()) cm.indentSelection("add");
      else cm.replaceSelection("    ", "end");
    },
    "Shift-Tab": cm => cm.indentSelection("subtract")
  }
}) : null;
const sourceText = () => editor ? editor.getValue() : byId("source").value;
byId("focus").addEventListener("click", () => {
  const focused = document.body.classList.toggle("focus-mode");
  byId("focus").textContent = focused ? "Exit focus mode" : "Focus mode";
  byId("focus").setAttribute("aria-pressed", String(focused));
  if (editor) editor.refresh();
});
byId("example").addEventListener("change", event => {
  if (editor) editor.setValue(examples[event.target.value]);
  else byId("source").value = examples[event.target.value];
  if (event.target.value === "input") byId("stdin").value = "7\n";
});
byId("run").addEventListener("click", () => {
  byId("output").textContent = "";
  byId("errors").textContent = "";
  byId("status").textContent = "Loading interpreter...";
  byId("run").disabled = true;
  byId("stop").disabled = false;
  lastRun = {source:sourceText(), fast:byId("fast").checked, build:"Unavailable (interpreter not loaded)", status:"Running"};
  const current = worker = new Worker("worker.js");
  current.onmessage = ({data}) => {
    if (worker !== current) return;
    if (data.type === "status") {
      byId("status").textContent = data.text;
      if (data.build) lastRun.build = data.build;
    }
    if (data.type === "done") {
      byId("output").textContent = data.output;
      byId("errors").textContent = data.errors;
      lastRun.status = data.ok ? "Finished" : "Failed";
      finish(`${data.ok ? "Finished" : "Failed"} / ${data.seconds.toFixed(3)} s`);
    }
    if (data.type === "error") {
      byId("errors").textContent = data.text;
      lastRun.status = "Unable to run";
      finish("Unable to run");
    }
  };
  current.onerror = event => {
    lastRun.status = "Unable to run";
    byId("errors").textContent = event.message || "Unable to load the browser interpreter. Build it with python web/build.py first.";
    finish("Unable to run");
  };
  current.postMessage({source:sourceText(), input:byId("stdin").value, fast:byId("fast").checked});
  timer = setTimeout(() => {
    lastRun.status = "Time limit reached";
    byId("errors").textContent = "Stopped after the 30-second limit. Partial output is not available.";
    finish("Time limit reached");
  }, 30000);
});
byId("stop").addEventListener("click", () => {
  if (lastRun) lastRun.status = "Stopped";
  finish("Stopped");
});
byId("source").addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    if (!worker) byId("run").click();
  }
  if (event.key === "Tab") {
    event.preventDefault();
    const editor = event.target;
    editor.setRangeText("    ", editor.selectionStart, editor.selectionEnd, "end");
  }
});
byId("download").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([sourceText()], {type:"text/plain"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "program.f90";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function reportBlock(text, language = "text") {
  const runs = text.match(/`+/g) || [];
  const fence = "`".repeat(Math.max(3, ...runs.map(run => run.length + 1)));
  return `${fence}${language}\n${text}\n${fence}`;
}
function reportSourceSection(included) {
  const source = lastRun ? lastRun.source : sourceText();
  return "## Fortran source\n" + (included ? reportBlock(source, "fortran") : "Not included. Please provide a minimal reproducer if possible.");
}
function reportBody() {
  const snapshot = lastRun || {source:sourceText(), fast:byId("fast").checked, build:"Unavailable (no program run)", status:"Not run"};
  const parts = [
    "## Problem\nDescribe what went wrong and the steps to reproduce it.",
    "## Expected behavior\nDescribe the expected output or behavior.",
    `## Environment\nBuild: ${snapshot.build}\nFast mode: ${snapshot.fast ? "on" : "off"}\nRun status: ${snapshot.status}\nBrowser: ${navigator.userAgent}`,
    reportSourceSection(byId("report-source").checked),
    "## Output\n" + reportBlock(byId("output").textContent || "(none)"),
    "## Warnings and errors\n" + reportBlock(byId("errors").textContent || "(none)"),
    "Standard input is not included automatically. Add any non-sensitive input needed to reproduce the problem."
  ];
  return parts.join("\n\n") + "\n";
}
const issueBase = "https://github.com/Beliavsky/ofort/issues/new";
function issueURL(body) {
  return issueBase + "?" + new URLSearchParams({title:byId("report-title").value.trim() || "Browser playground bug", body});
}
function updateReportNote() {
  const large = issueURL(byId("report-preview").value).length > 7000;
  byId("report-open").textContent = large ? "Open blank GitHub issue" : "Open GitHub issue";
  byId("report-note").textContent = large
    ? "This report is too large for a prefilled URL. Download it, open a blank issue, and paste or attach the report."
    : "Nothing is sent until you open GitHub. You will need a GitHub account to submit the issue.";
}
byId("report").addEventListener("click", () => {
  if (worker) {
    alert("Wait for the run to finish, or press Stop before reporting a bug.");
    return;
  }
  byId("report-source").checked = false;
  byId("report-preview").value = reportBody();
  updateReportNote();
  byId("report-dialog").showModal();
});
byId("report-source").addEventListener("change", () => {
  const included = byId("report-source").checked;
  const previous = reportSourceSection(!included);
  const preview = byId("report-preview");
  if (!preview.value.includes(previous)) {
    byId("report-source").checked = !included;
    byId("report-note").textContent = "The source section has been edited. Add or remove source manually in the preview; your edits have been preserved.";
    return;
  }
  preview.value = preview.value.replace(previous, () => reportSourceSection(included));
  updateReportNote();
});
byId("report-preview").addEventListener("input", updateReportNote);
byId("report-title").addEventListener("input", updateReportNote);
byId("report-open").addEventListener("click", () => {
  const url = issueURL(byId("report-preview").value);
  window.open(url.length > 7000 ? issueBase : url, "_blank", "noopener,noreferrer");
});
byId("report-download").addEventListener("click", () => {
  const text = "# " + byId("report-title").value + "\n\n" + byId("report-preview").value;
  const url = URL.createObjectURL(new Blob([text], {type:"text/markdown;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "ofort-bug-report.md";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
byId("report-close").addEventListener("click", () => byId("report-dialog").close());
