import { IntegrationWorkspace } from './IntegrationWorkspace.js';

interface PlatformOwnerConsoleProps {
  csrfToken: string;
}

/** Keep the dedicated Platform Owner entry point on the same audited provider workflow. */
export function PlatformOwnerConsole({ csrfToken }: PlatformOwnerConsoleProps) {
  return <IntegrationWorkspace csrfToken={csrfToken} />;
}
