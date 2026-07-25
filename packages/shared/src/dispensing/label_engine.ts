import { LabelPrintFormat } from './types.js';

export interface LabelDataInput {
  patientName: string;
  medicineName: string;
  dosageInstructions: string;
  quantity: string;
  batchNumber: string;
  expiryDate: string;
  pharmacistInitials: string;
  prescriptionRef: string;
  dispensingRef: string;
  dateDispensed: string;
  pharmacyName?: string;
}

export interface FormattedLabelOutput {
  format: LabelPrintFormat;
  title: string;
  htmlTemplate: string;
  qrPayload: string;
  checksum: string;
}

export class IntelligentLabelEngine {
  static generateLabel(input: LabelDataInput, format: LabelPrintFormat = '70x40'): FormattedLabelOutput {
    const qrPayload = JSON.stringify({
      rx: input.prescriptionRef,
      disp: input.dispensingRef,
      batch: input.batchNumber,
      exp: input.expiryDate,
      qty: input.quantity,
    });

    const checksum = `LBL-${input.dispensingRef}-${input.batchNumber.slice(0, 6)}`;

    let htmlTemplate = '';
    if (format === '58x40') {
      htmlTemplate = `
        <div style="width: 58mm; height: 40mm; font-family: monospace; font-size: 8pt; padding: 2mm; box-sizing: border-box; border: 1px solid #000;">
          <div style="font-weight: bold; border-bottom: 1px solid #000;">${input.pharmacyName || 'TIBA PHARMACY'}</div>
          <div><b>Patient:</b> ${input.patientName}</div>
          <div><b>Rx:</b> ${input.medicineName} (Qty: ${input.quantity})</div>
          <div><b>Directions:</b> ${input.dosageInstructions}</div>
          <div style="margin-top: 1mm; font-size: 7pt;">
            <span>B: ${input.batchNumber}</span> | <span>E: ${input.expiryDate}</span> | <span>RPh: ${input.pharmacistInitials}</span>
          </div>
        </div>
      `.trim();
    } else if (format === 'A4_MULTI') {
      htmlTemplate = `
        <div style="width: 210mm; min-height: 297mm; padding: 10mm; font-family: sans-serif; box-sizing: border-box;">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 5mm;">
            <div style="border: 1px solid #333; padding: 4mm; border-radius: 2mm;">
              <h3 style="margin: 0 0 2mm 0; border-bottom: 1px solid #333;">${input.pharmacyName || 'TIBA PHARMACY'} DISPENSING LABEL</h3>
              <p><strong>Patient:</strong> ${input.patientName}</p>
              <p><strong>Medication:</strong> ${input.medicineName} &mdash; Qty: ${input.quantity}</p>
              <p><strong>Dosage:</strong> ${input.dosageInstructions}</p>
              <hr />
              <p><small>Batch: ${input.batchNumber} | Expiry: ${input.expiryDate} | Pharmacist: ${input.pharmacistInitials}</small></p>
              <p><small>Ref: ${input.dispensingRef} | Date: ${input.dateDispensed}</small></p>
            </div>
          </div>
        </div>
      `.trim();
    } else {
      // Default 70x40mm
      htmlTemplate = `
        <div style="width: 70mm; height: 40mm; font-family: sans-serif; font-size: 9pt; padding: 3mm; box-sizing: border-box; border: 1px solid #000;">
          <div style="font-weight: bold; font-size: 10pt; border-bottom: 1px solid #000; margin-bottom: 1mm;">${input.pharmacyName || 'TIBA PHARMACY'}</div>
          <div><strong>Patient:</strong> ${input.patientName}</div>
          <div><strong>Rx:</strong> ${input.medicineName} (${input.quantity})</div>
          <div style="margin: 1mm 0; font-weight: bold;">${input.dosageInstructions}</div>
          <div style="font-size: 7.5pt; border-top: 1px dashed #666; padding-top: 1mm; margin-top: 1mm; display: flex; justify-content: space-between;">
            <span>Batch: ${input.batchNumber}</span>
            <span>Exp: ${input.expiryDate}</span>
            <span>RPh: ${input.pharmacistInitials}</span>
          </div>
        </div>
      `.trim();
    }

    return {
      format,
      title: `Label for ${input.medicineName} (${input.patientName})`,
      htmlTemplate,
      qrPayload,
      checksum,
    };
  }
}
