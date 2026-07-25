import { IntelligentLabelEngine, LabelDataInput, LabelPrintFormat, FormattedLabelOutput } from './types.js';

export class IntelligentLabelPrinter {
  private reprintCount: number = 0;

  generateLabel(input: LabelDataInput, format: LabelPrintFormat = '70x40'): FormattedLabelOutput {
    return IntelligentLabelEngine.generateLabel(input, format);
  }

  recordReprint(reason: string): number {
    this.reprintCount += 1;
    return this.reprintCount;
  }

  getReprintCount(): number {
    return this.reprintCount;
  }
}
