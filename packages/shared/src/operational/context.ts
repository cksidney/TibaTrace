import type {
  BusinessDayDTO,
  DeviceHealthDTO,
  OperatorShiftDTO,
  PosOperationalContext,
  PosRegisterDTO,
  RegisterSessionDTO,
} from './types.js';

export interface OperationalContextInput {
  readonly deviceId: string;
  readonly operatorId: string;
  readonly registers: readonly PosRegisterDTO[];
  readonly businessDays: readonly BusinessDayDTO[];
  readonly openSessions: readonly RegisterSessionDTO[];
  readonly devices: readonly DeviceHealthDTO[];
}

export function resolveOperationalContext(input: OperationalContextInput): PosOperationalContext {
  const register = input.registers.find(
    (candidate) => candidate.device_id !== '' && candidate.device_id === input.deviceId,
  ) ?? null;
  const registerSession = register
    ? input.openSessions.find((candidate) => candidate.register_code === register.code) ?? null
    : null;
  const businessDay = register
    ? input.businessDays.find(
        (candidate) =>
          candidate.branch_code === register.branch_code &&
          (registerSession ? candidate.business_date === registerSession.business_date : candidate.accepts_transactions),
      ) ?? null
    : null;
  const operatorShift = registerSession
    ? registerSession.operator_shifts.find(
        (candidate) =>
          candidate.operator_id === input.operatorId &&
          (candidate.state === 'OPEN' || candidate.state === 'HANDOVER_REQUESTED'),
      ) ?? null
    : null;
  const deviceHealth = input.devices.find((candidate) => candidate.device_id === input.deviceId) ?? null;
  const notices = buildNotices(register, registerSession, businessDay, operatorShift, deviceHealth);

  return {
    readiness: register && registerSession && businessDay?.accepts_transactions && operatorShift && notices.length === 0
      ? 'READY'
      : register
        ? 'ATTENTION'
        : 'UNASSIGNED',
    register,
    businessDay,
    registerSession,
    operatorShift,
    deviceHealth,
    notices,
  };
}

function buildNotices(
  register: PosRegisterDTO | null,
  registerSession: RegisterSessionDTO | null,
  businessDay: BusinessDayDTO | null,
  operatorShift: OperatorShiftDTO | null,
  deviceHealth: DeviceHealthDTO | null,
): readonly string[] {
  const notices: string[] = [];
  if (!register) {
    notices.push('This device is not assigned to a register.');
    return notices;
  }
  if (!registerSession) notices.push(`Register ${register.code} has no open register session.`);
  if (!businessDay?.accepts_transactions) notices.push('The current business day does not accept transactions.');
  if (!operatorShift) notices.push('No active accountable operator shift was found for this session.');
  if (!deviceHealth) notices.push('No current device and printer health report is available.');
  else if (deviceHealth.status === 'ERROR' || deviceHealth.status === 'OFFLINE') {
    notices.push('The device health service reports this terminal as unavailable.');
  } else if (deviceHealth.status === 'WARNING' || deviceHealth.printer_paper_level !== 'OK') {
    notices.push('The device or printer requires attention before continuing.');
  }
  return notices;
}
