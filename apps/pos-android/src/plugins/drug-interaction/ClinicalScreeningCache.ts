/**
 * Cache with expiry for Android POS
 */
export class ClinicalScreeningCache {
  private cache = new Map<string, { result: any; expiresAt: number }>();

  public get(contextHash: string): any {
    const item = this.cache.get(contextHash);
    if (!item) return null;
    if (Date.now() > item.expiresAt) {
      this.cache.delete(contextHash);
      return null;
    }
    return item.result;
  }

  public set(contextHash: string, result: any, ttlMs: number): void {
    this.cache.set(contextHash, { result, expiresAt: Date.now() + ttlMs });
  }

  public invalidate(transactionId: string): void {
    this.cache.clear();
  }

  public invalidateAll(): void {
    this.cache.clear();
  }

  public isExpired(contextHash: string): boolean {
    const item = this.cache.get(contextHash);
    if (!item) return true;
    return Date.now() > item.expiresAt;
  }
}
