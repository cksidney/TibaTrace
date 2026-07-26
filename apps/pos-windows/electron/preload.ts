import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('tibatrace', {
  platform: 'windows' as const,
  version: process.env['npm_package_version'] ?? '0.0.0',
  auth: {
    restore: () => ipcRenderer.invoke('auth:restore'),
    login: (username: string, password: string) =>
      ipcRenderer.invoke('auth:login', { username, password }),
    logout: () => ipcRenderer.invoke('auth:logout'),
  },
  api: {
    request: (request: unknown) => ipcRenderer.invoke('api:request', request),
  },
  offline: {
    read: () => ipcRenderer.invoke('offline:read'),
    write: (actions: unknown) => ipcRenderer.invoke('offline:write', actions),
  },
});
