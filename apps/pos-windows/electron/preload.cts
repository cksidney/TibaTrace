import { contextBridge, ipcRenderer } from 'electron';

const clientMetadata = ipcRenderer.sendSync('app:metadata') as { version: string; buildNumber: number };

contextBridge.exposeInMainWorld('tibatrace', {
  platform: 'windows' as const,
  version: clientMetadata.version,
  buildNumber: clientMetadata.buildNumber,
  auth: {
    restore: () => ipcRenderer.invoke('auth:restore'),
    login: (username: string, password: string) =>
      ipcRenderer.invoke('auth:login', { username, password }),
    verify: (username: string, password: string) =>
      ipcRenderer.invoke('auth:verify', { username, password }),
    logout: () => ipcRenderer.invoke('auth:logout'),
  },
  api: {
    request: (request: unknown) => ipcRenderer.invoke('api:request', request),
  },
  offline: {
    read: () => ipcRenderer.invoke('offline:read'),
    write: (actions: unknown) => ipcRenderer.invoke('offline:write', actions),
  },
  print: {
    printers: () => ipcRenderer.invoke('print:printers'),
    document: (jobId: string, printer: string) => ipcRenderer.invoke('print:document', { jobId, printer }),
  },
});
