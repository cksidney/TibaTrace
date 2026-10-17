# TibaTrace 1.0.0-rc56

Improves POS activation readiness and recovery so operators can see whether a register is available, configured, pending or needs follow-up. Retail and clinical screens received focused layout and readability fixes after review across the POS tabs and narrow screen sizes. Daraja and VSCU server transports now reject redirects, ignore ambient proxy settings and retain bounded response sizes; uncertain payment or fiscal outcomes continue to require reconciliation.

Windows POS **1.0.12 build 12** includes the reviewed retail selector layout and clearer disabled clinical workflow steps. Its signed managed installer is tracked separately by the `pos-windows-v1.0.12` tag; deploying the server does not update installed tills.

Daraja and VSCU live activation remains disabled until provider credentials, the VSCU configuration location, registered-device details, item/tax mappings and live acceptance are supplied and verified. No live provider certification or physical terminal/printer certification is claimed.
