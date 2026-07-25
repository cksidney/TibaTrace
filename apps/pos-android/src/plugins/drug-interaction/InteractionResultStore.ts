/**
 * Local state management for interaction results
 */
export class InteractionResultStore {
  private store = new Map<string, any>();

  public setScreeningResult(transactionId: string, result: any): void {
    this.store.set(transactionId, result);
  }

  public getScreeningResult(transactionId: string): any {
    return this.store.get(transactionId);
  }

  public clearResults(): void {
    this.store.clear();
  }

  public getBlockingFindings(transactionId: string): any[] {
    return [];
  }

  public getIndicatorForLine(lineId: string): any {
    return null;
  }
}
