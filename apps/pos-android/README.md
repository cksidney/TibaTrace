# TibaTrace Android POS

The Android client is a React Native application for authenticated dispensing,
clinical screening, payment, counselling, and collection.

## Runtime guarantees

- Session tokens and the action journal are encrypted with an AES-GCM key held
  by Android Keystore.
- App data is excluded from cloud backup and device transfer.
- Release builds reject cleartext traffic and default to
  `https://tibatrace.esenai.co.ke`.
- Payments and collections are persisted before transmission. Unknown outcomes
  block progression rather than retrying blindly.
- Release builds use R8 shrinking and cannot fall back to the debug signing key.

## Development

Requirements:

- Node.js 22.13 or newer in the Node 22 release line
- JDK 17
- Android SDK 36, Build Tools 36, and NDK 27.1.12297006

```bash
npm run build --workspace @dawatrace/shared
npm run typecheck --workspace @dawatrace/pos-android
npm run test --workspace @dawatrace/pos-android
npm run build --workspace @dawatrace/pos-android
npm run android:assemble:debug --workspace @dawatrace/pos-android
```

The default native target is ARM64. For an x86_64 emulator:

```bash
cd apps/pos-android/android
./gradlew assembleDebug -PreactNativeArchitectures=x86_64
```

Set `TIBATRACE_API_BASE_URL=http://10.0.2.2:8000` before a debug Gradle build to
connect an Android emulator to the local backend.

## Android release

```bash
export TIBATRACE_ANDROID_KEYSTORE=/secure/tibatrace-upload.jks
export TIBATRACE_ANDROID_STORE_PASSWORD='<secret>'
export TIBATRACE_ANDROID_KEY_ALIAS='tibatrace'
export TIBATRACE_ANDROID_KEY_PASSWORD='<secret>'
npm run release:android --workspace @dawatrace/pos-android
```

The command creates a signed Android App Bundle. It fails when any signing value
is missing. The upload key and Play App Signing configuration remain external
release assets and must never be committed.
