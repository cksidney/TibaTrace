package co.ke.esenai.tibatrace.pos

import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule

class TibaTraceConfigModule(
    reactContext: ReactApplicationContext
) : ReactContextBaseJavaModule(reactContext) {
  override fun getName(): String = "TibaTraceConfig"

  override fun getConstants(): Map<String, Any> =
      mapOf(
          "apiBaseUrl" to BuildConfig.TIBATRACE_API_BASE_URL,
          "versionName" to BuildConfig.VERSION_NAME,
          "isDebug" to BuildConfig.DEBUG,
      )
}
