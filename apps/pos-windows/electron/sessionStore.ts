import { existsSync } from 'node:fs';
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

import { app, safeStorage } from 'electron';

export interface StoredPosSession {
  readonly access: string;
  readonly refresh: string;
  readonly tenantId: string;
  readonly userId: string;
}

interface SessionEnvelope extends StoredPosSession {
  readonly version: 1;
  readonly writtenAt: string;
}

export class EncryptedSessionStore {
  private readonly directory = join(app.getPath('userData'), 'session');
  private readonly file = join(this.directory, 'session.enc');
  private readonly temp = join(this.directory, 'session.enc.tmp');
  private readonly backup = join(this.directory, 'session.enc.bak');

  async load(): Promise<StoredPosSession | null> {
    if (!existsSync(this.file) && existsSync(this.backup)) {
      await rename(this.backup, this.file);
    }
    if (!existsSync(this.file)) return null;
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error('Windows secure storage is unavailable.');
    }

    try {
      const envelope = JSON.parse(
        safeStorage.decryptString(await readFile(this.file)),
      ) as SessionEnvelope;
      if (
        envelope.version !== 1 ||
        !envelope.access ||
        !envelope.refresh ||
        !envelope.tenantId ||
        !envelope.userId
      ) {
        throw new Error('The stored session is incomplete.');
      }
      return {
        access: envelope.access,
        refresh: envelope.refresh,
        tenantId: envelope.tenantId,
        userId: envelope.userId,
      };
    } catch (cause) {
      throw new Error('The encrypted sign-in session could not be read.', { cause });
    }
  }

  async save(session: StoredPosSession): Promise<void> {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error('Windows secure storage is unavailable.');
    }
    await mkdir(this.directory, { recursive: true });
    const envelope: SessionEnvelope = {
      version: 1,
      writtenAt: new Date().toISOString(),
      ...session,
    };
    await writeFile(
      this.temp,
      safeStorage.encryptString(JSON.stringify(envelope)),
    );
    await replaceFile(this.file, this.temp, this.backup);
  }

  async clear(): Promise<void> {
    for (const path of [this.file, this.temp, this.backup]) {
      if (existsSync(path)) await unlink(path);
    }
  }
}

async function replaceFile(file: string, temp: string, backup: string): Promise<void> {
  if (existsSync(backup)) await unlink(backup);
  if (existsSync(file)) await rename(file, backup);
  try {
    await rename(temp, file);
  } catch (cause) {
    if (!existsSync(file) && existsSync(backup)) await rename(backup, file);
    throw cause;
  }
  if (existsSync(backup)) await unlink(backup);
}
