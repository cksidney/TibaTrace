import { contextBridge } from 'electron';

/**
 * Deliberately minimal. The renderer talks to the DawaTrace API over HTTPS like
 * any other client; it does not get privileged main-process helpers, because
 * anything exposed here becomes reachable from page content.
 */
contextBridge.exposeInMainWorld('tibatrace', {
  platform: 'windows' as const,
  version: process.env['npm_package_version'] ?? '0.0.0',
});
