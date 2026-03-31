const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn } = require("child_process");
const path = require("path");

let mainWindow = null;
let agentProcess = null;

function startAgent() {
  const command = process.env.SHARDNET_AGENT_COMMAND || "shardnet-agent";
  const args = (process.env.SHARDNET_AGENT_ARGS || "").split(" ").filter(Boolean);

  agentProcess = spawn(command, args, {
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  agentProcess.stdout.on("data", (chunk) => {
    console.log(`[agent] ${chunk.toString().trim()}`);
  });

  agentProcess.stderr.on("data", (chunk) => {
    console.error(`[agent] ${chunk.toString().trim()}`);
  });

  agentProcess.on("exit", (code) => {
    console.log(`[agent] exited with code ${code}`);
    agentProcess = null;
  });
}

function stopAgent() {
  if (!agentProcess) {
    return;
  }

  agentProcess.kill();
  agentProcess = null;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 760,
    title: "ShardNet Desktop",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    backgroundColor: "#0D1A1D",
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

ipcMain.handle("dialog:pickShareFile", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openFile"],
  });
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});

ipcMain.handle("dialog:pickDownloadTarget", async (_, defaultFileName) => {
  const result = await dialog.showSaveDialog({
    defaultPath: defaultFileName || "download.bin",
  });
  if (result.canceled || !result.filePath) {
    return null;
  }
  return result.filePath;
});

ipcMain.handle("app:getAgentUrl", () => {
  return process.env.SHARDNET_AGENT_URL || "http://127.0.0.1:8765";
});

app.whenReady().then(() => {
  startAgent();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopAgent();
});
