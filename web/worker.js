"use strict";
let modulePromise = null;
let module = null;
let interpreter = 0;
let session = false;
let accepted = [];
let pending = [];
let blocks = [];
let logicalLine = "";
let continuing = false;
let input = new Uint8Array();
let position = 0;
const stdout = [];
const stderr = [];
let queue = Promise.resolve();

const getText = name => module.ccall(name, "string", ["number"], [interpreter]) || "";
function specificationGroup(source) {
  const code = source.split("\n").map(codeWithoutStringsOrComments).join(" ").trim().toLowerCase();
  if (/^(use|import)\b/.test(code)) return 0;
  if (/^implicit\b/.test(code)) return 1;
  // A typed function is a program unit, not a variable declaration.
  if (/\bfunction\s+[a-z]\w*\s*\(/.test(code)) return 3;
  if (/^(integer|real|double\s+(precision|complex)|complex|logical|character)\b/.test(code) ||
      /^(type|class)\s*\(/.test(code) || /^type\s*(?:,[^:]*)?::/.test(code) ||
      /^(parameter|dimension|allocatable|pointer|target|save|external|intrinsic|optional|intent|namelist|common|equivalence|data|procedure)\b/.test(code)) return 2;
  return 3;
}

function sessionSource() {
  const groups = [[], [], [], []];
  for (const submission of accepted) groups[specificationGroup(submission)].push(submission);
  const implicit = groups[1].length ? groups[1] : ["implicit none"];
  return [...groups[0], ...implicit, ...groups[2], ...groups[3], ...pending].join("\n") + "\n";
}

function savedSubmission(lines) {
  const source = lines.join("\n");
  const code = lines.map(codeWithoutStringsOrComments).join(" ").replace(/&/g, " ").trim();
  if (!code || specificationGroup(source) !== 3 || code.includes(";")) return source;
  // Retain actual Fortran statements and constructs. Only the top-level
  // expression shortcut is turned into PRINT in saved/replayed source.
  if (/^(?:[a-z]\w*\s*:\s*)?(?:\d+\s+)?(?:program|module|submodule|contains|end\w*|subroutine|function|pure|impure|elemental|recursive|abstract|interface|type|class|enum|enumeration|call|print|write|read|open|close|flush|rewind|backspace|endfile|inquire|allocate|deallocate|nullify|if|else\w*|do|where|forall|select|case|associate|block|critical|change|sync|lock|unlock|event|form|error|stop|return|exit|cycle|goto|go|continue|format|entry)\b/i.test(code)) return source;
  let depth = 0;
  for (let i = 0; i < code.length; i++) {
    if (code[i] === "(") depth++;
    if (code[i] === ")") depth--;
    if (!depth && code[i] === "=" && code[i + 1] !== "=" && !/[<>=/]/.test(code[i - 1] || " ")) return source;
  }
  const saved = lines.slice();
  const first = saved.findIndex(line => codeWithoutStringsOrComments(line).trim());
  if (first >= 0) saved[first] = "print *, " + saved[first].trimStart();
  return saved.join("\n");
}

async function loadModule() {
  if (!modulePromise) {
    importScripts("ofort.js");
    modulePromise = createOfortModule({
      stdin: () => position < input.length ? input[position++] : null,
      print: text => stdout.push(text),
      printErr: text => stderr.push(text)
    });
  }
  module = await modulePromise;
}

function newInterpreter(repl) {
  if (interpreter) module.ccall("ofort_c_destroy", null, ["number"], [interpreter]);
  interpreter = 0;
  interpreter = module.ccall(repl ? "ofort_web_repl_create" : "ofort_c_create", "number", [], []);
  if (!interpreter) throw new Error("Unable to allocate the interpreter. Close memory-heavy tabs and try again.");
  session = repl;
}

// Buffer logical lines/constructs; the interpreter handles syntax and execution.
function codeWithoutStringsOrComments(line) {
  let quote = "", code = "";
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quote) {
      if (c === quote) {
        if (line[i + 1] === quote) { code += "  "; i++; continue; }
        quote = "";
      }
      code += " ";
    } else if (c === "'" || c === '"') { quote = c; code += " "; }
    else if (c === "!") break;
    else code += c;
  }
  return code;
}

function trackConstruct(statement) {
  const code = statement.trim().toLowerCase().replace(/^[a-z]\w*\s*:\s*/, "");
  if (!code) return;
  if (/^end(?:\s|$)|^end(?:do|if|where|forall|select|associate|block|type|interface|function|subroutine|module|program)\b/.test(code)) {
    if (blocks.length) blocks.pop();
    return;
  }
  let construct = null;
  if (/^do(?:\s|$)/.test(code)) construct = "DO";
  else if (/^if\s*\(.*\)\s*then\s*$/.test(code)) construct = "IF";
  else if (/^(where|forall)\s*\(/.test(code)) {
    let depth = 0, close = -1;
    for (let i = code.indexOf("("); i < code.length; i++) {
      if (code[i] === "(") depth++;
      if (code[i] === ")" && --depth === 0) { close = i; break; }
    }
    if (close >= 0 && !code.slice(close + 1).trim()) construct = code.startsWith("where") ? "WHERE" : "FORALL";
  } else if (/^select\s*(case|type|rank)\b/.test(code)) construct = "SELECT";
  else if (/^associate\s*\(/.test(code)) construct = "ASSOCIATE";
  else if (/^block(?:\s+data\b|\s*$)/.test(code)) construct = "BLOCK";
  else if (/^type\s*(?:,[^:]*)?::/.test(code) || /^type\s+[a-z]\w*\s*$/.test(code)) construct = "TYPE";
  else if (/^(?:abstract\s+)?interface(?:\s|$)/.test(code)) construct = "INTERFACE";
  else if (/\bsubroutine\s+[a-z]\w*/.test(code)) construct = "SUBROUTINE";
  else if (/\bfunction\s+[a-z]\w*\s*\(/.test(code)) construct = "FUNCTION";
  else if (/^module\s+(?!procedure\b|function\b|subroutine\b)[a-z]\w*/.test(code)) construct = "MODULE";
  else if (/^program\s+[a-z]\w*/.test(code)) construct = "PROGRAM";
  if (construct) blocks.push(construct);
}

function execute(source, output, errors) {
  module.ccall("ofort_c_reset", null, ["number"], [interpreter]);
  const result = module.ccall("ofort_c_execute", "number", ["number", "string"], [interpreter, source]);
  const text = getText("ofort_get_output");
  if (text) output.push(text);
  const diagnostics = [getText("ofort_get_warnings"), result !== 0 ? getText("ofort_get_error") : ""].filter(Boolean).join("\n");
  if (diagnostics) errors.push(diagnostics);
  return result === 0;
}

const variables = () => getText("ofort_web_repl_variables");

function clearPending() {
  pending = [];
  blocks = [];
  logicalLine = "";
  continuing = false;
}

function replCommand(command, output, errors, fast) {
  const trimmed = command.trim();
  if (trimmed.startsWith(".")) {
    if (trimmed === ".clear") {
      newInterpreter(true);
      accepted = [];
      clearPending();
      module.ccall("ofort_c_set_fast_mode", null, ["number", "number"], [interpreter, Number(fast)]);
      output.push("Session cleared. Clear session also resets temporary files.");
      return true;
    }
    if (trimmed === ".help") {
      output.push("Enter standard Fortran declarations and statements, or expressions.\nBlocks execute after their matching END; '&' continues a line.\n.run or . restarts and runs accumulated code.\n.list / .list -n lists source. .vars / .info lists variables.\n.clear discards source and values. Clear session also resets temporary files.\nThis browser mode supports these commands, not every native REPL shortcut.");
      return true;
    }
    if (trimmed === ".vars" || trimmed === ".info") { output.push(variables()); return true; }
    if (trimmed === ".list" || trimmed === ".list -n") {
      const lines = sessionSource().trimEnd().split("\n");
      output.push(lines.map((line, i) => trimmed.endsWith("-n") ? line : `${String(i + 1).padStart(4)}  ${line}`).join("\n"));
      return true;
    }
    if (trimmed === "." || trimmed === ".run") {
      if (blocks.length || continuing) { errors.push("Finish the pending block or continuation before running accumulated code."); return false; }
      const source = sessionSource();
      newInterpreter(true);
      module.ccall("ofort_c_set_fast_mode", null, ["number", "number"], [interpreter, Number(fast)]);
      return execute(source, output, errors);
    }
    errors.push("Unsupported browser REPL command. Enter .help for available commands.");
    return false;
  }
  let ok = true;
  for (const line of command.replace(/\r\n?/g, "\n").split("\n")) {
    if (!line.trim() && !pending.length) continue;
    pending.push(line);
    let code = codeWithoutStringsOrComments(line).trim();
    if (continuing) code = code.replace(/^&\s*/, "");
    // Comment/blank lines between continued lines must not end continuation.
    if (!code && continuing) continue;
    continuing = code.endsWith("&");
    logicalLine += " " + (continuing ? code.slice(0, -1) : code);
    if (continuing) continue;
    for (const statement of logicalLine.split(";")) trackConstruct(statement);
    logicalLine = "";
    if (blocks.length) continue;
    const source = pending.join("\n") + "\n";
    ok = execute(source, output, errors);
    if (ok) accepted.push(savedSubmission(pending));
    clearPending();
    if (!ok) {
      errors.push("The submission was not added to source. Statements before a runtime error may already have changed state; Clear session starts over.");
      break;
    }
  }
  return ok;
}

async function handle(data) {
  stdout.length = 0;
  stderr.length = 0;
  const repl = data.type && data.type.startsWith("repl");
  try {
    const text = data.input || "";
    input = new TextEncoder().encode(text + (text.endsWith("\n") ? "" : "\n"));
    position = 0;
    await loadModule();
    const build = module.ccall("ofort_web_build_info", "string", [], []);
    self.postMessage({type:"status", text:repl ? "Updating session..." : "Running...", build});
    if (!repl || !session || !interpreter) newInterpreter(repl);
    module.ccall("ofort_c_set_fast_mode", null, ["number", "number"], [interpreter, Number(data.fast)]);
    const start = performance.now();
    const output = [], errors = [];
    let ok;
    if (data.type === "repl-replay") {
      newInterpreter(true);
      accepted = [];
      clearPending();
      module.ccall("ofort_c_set_fast_mode", null, ["number", "number"], [interpreter, Number(data.fast)]);
      ok = replCommand(data.source || "", output, errors, data.fast);
      if (!ok) errors.push("Replay failed in the new interpreter. The old state was discarded; displayed variables reflect the possibly partial new state.");
    } else {
      ok = data.type === "repl-init" ? true : repl
        ? replCommand(data.command || "", output, errors, data.fast)
        : execute(data.source, output, errors);
    }
    self.postMessage({type:"done", repl, ok, seconds:(performance.now() - start)/1000,
      output:[...stdout, ...output].filter(Boolean).join("\n"),
      errors:[...errors, ...stderr].filter(Boolean).join("\n"),
      source:repl ? sessionSource() : undefined,
      variables:repl ? variables() : undefined,
      pending:repl && (blocks.length > 0 || continuing),
      waiting:continuing ? "continuation" : blocks[blocks.length - 1]});
  } catch (error) {
    self.postMessage({type:"error", text:[error.message, ...stderr].filter(Boolean).join("\n")});
  } finally {
    if (!repl && module && interpreter) {
      module.ccall("ofort_c_destroy", null, ["number"], [interpreter]);
      interpreter = 0;
    }
  }
}

self.onmessage = ({data}) => {
  queue = queue.then(() => handle(data)).catch(error => self.postMessage({type:"error", text:error.message}));
};
