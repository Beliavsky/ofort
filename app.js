"use strict";
const byId = id => document.getElementById(id);
const examples = {
  hello: 'program hello\nimplicit none\nprint *, "Hello from ofort in your browser!"\nend program hello\n',
  arrays: 'program arrays\nimplicit none\ninteger :: i\nreal(kind=8) :: x(5)\nx = [(real(i, kind=8), i=1,5)]\nprint *, "x =", x\nprint *, "sum =", sum(x)\nprint *, "mean =", sum(x)/size(x)\nend program arrays\n',
  input: 'program input_demo\nimplicit none\ninteger :: n, ios\nread(*, *, iostat=ios) n\nif (ios == 0) then\n  print *, "Your number squared:", n*n\nelse\n  print *, "Supply an integer in the standard input box."\nend if\nend program input_demo\n'
};
let worker = null;
let timer = null;
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
  const current = worker = new Worker("worker.js");
  current.onmessage = ({data}) => {
    if (worker !== current) return;
    if (data.type === "status") byId("status").textContent = data.text;
    if (data.type === "done") {
      byId("output").textContent = data.output;
      byId("errors").textContent = data.errors;
      finish(`${data.ok ? "Finished" : "Failed"} / ${data.seconds.toFixed(3)} s`);
    }
    if (data.type === "error") {
      byId("errors").textContent = data.text;
      finish("Unable to run");
    }
  };
  current.onerror = event => {
    byId("errors").textContent = event.message || "Unable to load the browser interpreter. Build it with python web/build.py first.";
    finish("Unable to run");
  };
  current.postMessage({source:sourceText(), input:byId("stdin").value, fast:byId("fast").checked});
  timer = setTimeout(() => {
    byId("errors").textContent = "Stopped after the 30-second limit. Partial output is not available.";
    finish("Time limit reached");
  }, 30000);
});
byId("stop").addEventListener("click", () => finish("Stopped"));
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
