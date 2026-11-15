// The first-run screen's only bridge to the main process (sandboxed, context-isolated): state in, four actions out.
"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("firstrun", {
  onState: (cb) => ipcRenderer.on("firstrun:state", (_e, s) => cb(s)),
  retry: () => ipcRenderer.send("firstrun:retry"),
  later: () => ipcRenderer.send("firstrun:later"),
  importPack: () => ipcRenderer.send("firstrun:import"),
});
