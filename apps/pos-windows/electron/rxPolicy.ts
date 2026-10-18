export function rxRequestLimit(path: string, method: string): number {
  return method === 'POST' && /^\/api\/pos\/dispensing\/intake\/(?:import\/)?$/.test(path)
    ? 12 * 1024 * 1024 : 1024 * 1024;
}

export function allowsRxCamera({ page, requestingUrl, packagedPage, devServer, focused, isMainFrame, permission, mediaTypes }: {
  page: string; requestingUrl: string; packagedPage: string; devServer: string | undefined;
  focused: boolean; isMainFrame: boolean; permission: string; mediaTypes: readonly string[];
}): boolean {
  const trusted = (url: string) => {
    if (url === packagedPage) return true;
    try { return Boolean(devServer && new URL(url).origin === new URL(devServer).origin); }
    catch { return false; }
  };
  return trusted(page) && trusted(requestingUrl) && focused && isMainFrame
    && permission === 'media' && mediaTypes.length === 1 && mediaTypes[0] === 'video';
}
