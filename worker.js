"use strict";
self.onmessage = async ({data}) => {
  let module;
  let interpreter = 0;
  const stdout = [];
  const stderr = [];
  try {
    importScripts("ofort.js");
    const input = new TextEncoder().encode(data.input + (data.input.endsWith("\n") ? "" : "\n"));
    let position = 0;
    module = await createOfortModule({
      stdin: () => position < input.length ? input[position++] : null,
      print: text => stdout.push(text),
      printErr: text => stderr.push(text)
    });
    self.postMessage({type:"status", text:"Running..."});
    interpreter = module.ccall("ofort_c_create", "number", [], []);
    if (!interpreter) throw new Error("Unable to allocate the interpreter: browser memory allocation failed. Close memory-heavy tabs and try again.");
    module.ccall("ofort_c_set_fast_mode", null, ["number", "number"], [interpreter, Number(data.fast)]);
    const start = performance.now();
    const result = module.ccall("ofort_c_execute", "number", ["number", "string"], [interpreter, data.source]);
    const seconds = (performance.now() - start)/1000;
    const getText = name => module.ccall(name, "string", ["number"], [interpreter]) || "";
    const output = getText("ofort_get_output");
    const errors = [getText("ofort_get_warnings"), getText("ofort_get_error"), ...stderr].filter(Boolean).join("\n");
    self.postMessage({type:"done", ok:result === 0, seconds, output:[...stdout, output].filter(Boolean).join("\n"), errors});
  } catch (error) {
    self.postMessage({type:"error", text:[error.message, ...stderr].filter(Boolean).join("\n")});
  } finally {
    if (module && interpreter) module.ccall("ofort_c_destroy", null, ["number"], [interpreter]);
  }
};
