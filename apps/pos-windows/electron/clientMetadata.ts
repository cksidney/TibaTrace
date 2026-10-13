export function installedClientMetadata(version: string, manifest: unknown): { version: string; buildNumber: number } {
  const data = manifest as { version?: unknown; tibatraceBuildNumber?: unknown } | null;
  if (!data || data.version !== version || !version || version === '0.0.0'
    || typeof data.tibatraceBuildNumber !== 'number' || !Number.isSafeInteger(data.tibatraceBuildNumber)
    || data.tibatraceBuildNumber < 1) {
    throw new Error('Installed till release metadata is missing or inconsistent. Reinstall the approved managed kit.');
  }
  return { version, buildNumber: data.tibatraceBuildNumber };
}
