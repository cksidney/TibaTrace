# Windows POS 1.0.16 (build 16)

Includes RX intake, uploads and explicit deferred-scanning status. Direct manual
intake records now open as readable, escaped text and are labelled **Intake
record**, rather than opening as an image. Photo/PDF previews remain available;
unrecognised source MIME types are refused. The upload helper describes file
validation without claiming that malware scanning occurred.

Compatible with server rc59. This client-only correction changes no backend
code or database schema. Publish the signed managed package after its Windows
gates pass and the rc59 backend is active. Builds 14 and 15 are superseded before
tenant publication; the upgrade is advisory and minimum supported build unchanged.
