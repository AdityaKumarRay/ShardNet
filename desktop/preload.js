const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopBridge", {
  pickShareFile: () => ipcRenderer.invoke("dialog:pickShareFile"),
  pickDownloadTarget: (defaultFileName) =>
    ipcRenderer.invoke("dialog:pickDownloadTarget", defaultFileName),
  getAgentUrl: () => ipcRenderer.invoke("app:getAgentUrl"),
});
