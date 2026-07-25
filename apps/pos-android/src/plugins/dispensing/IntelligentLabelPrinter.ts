import { IntelligentLabelEngine, LabelDataInput, LabelPrintFormat, FormattedLabelOutput } from './types.js';

export class IntelligentLabelPrinter {
  generateLabel(input: LabelDataInput, format: LabelPrintFormat = '58x40'): FormattedLabelOutput {
    return IntelligentLabelEngine.generateLabel(input, format);
  }
}
