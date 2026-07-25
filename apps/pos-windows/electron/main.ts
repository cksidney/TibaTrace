import { join } from 'node:path';

import { app, BrowserWindow, session } from 'electron';

const DEV_SERVER = process.env['VITE_DEV_SERVER_URL'];

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    show: false,
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      // A till renders patient data and drives clinical actions. The renderer
      // gets no Node access and no ability to reach into the main process.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  window.once('ready-to-show', () => window.show());

  if (DEV_SERVER) {
    void window.loadURL(DEV_SERVER);
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'));
  }
}

app.whenReady().then(() => {
  // Deny every permission request outright: the POS needs none of them, and a
  // compromised page should not be able to ask for the camera or location.
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
