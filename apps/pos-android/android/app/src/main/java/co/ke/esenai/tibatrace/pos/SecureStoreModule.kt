package co.ke.esenai.tibatrace.pos

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureStoreModule(
    reactContext: ReactApplicationContext
) : ReactContextBaseJavaModule(reactContext) {
  private val preferences =
      reactContext.getSharedPreferences("tibatrace_secure_store", Context.MODE_PRIVATE)

  override fun getName(): String = "TibaTraceSecureStore"

  @ReactMethod
  fun isAvailable(promise: Promise) {
    try {
      getOrCreateKey()
      promise.resolve(true)
    } catch (error: Exception) {
      promise.resolve(false)
    }
  }

  @ReactMethod
  fun getItem(key: String, promise: Promise) {
    try {
      val encoded = preferences.getString(key, null)
      if (encoded == null) {
        promise.resolve(null)
        return
      }
      val parts = encoded.split(":", limit = 2)
      require(parts.size == 2)
      val cipher = Cipher.getInstance(TRANSFORMATION)
      cipher.init(
          Cipher.DECRYPT_MODE,
          getOrCreateKey(),
          GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)),
      )
      cipher.updateAAD(key.toByteArray(Charsets.UTF_8))
      val plaintext = cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP))
      promise.resolve(plaintext.toString(Charsets.UTF_8))
    } catch (error: Exception) {
      promise.reject("SECURE_STORE_READ_FAILED", "Encrypted data could not be read.", error)
    }
  }

  @ReactMethod
  fun setItem(key: String, value: String, promise: Promise) {
    try {
      val cipher = Cipher.getInstance(TRANSFORMATION)
      cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
      cipher.updateAAD(key.toByteArray(Charsets.UTF_8))
      val encoded =
          Base64.encodeToString(cipher.iv, Base64.NO_WRAP) +
              ":" +
              Base64.encodeToString(
                  cipher.doFinal(value.toByteArray(Charsets.UTF_8)),
                  Base64.NO_WRAP,
              )
      if (!preferences.edit().putString(key, encoded).commit()) {
        throw IllegalStateException("Encrypted value was not committed.")
      }
      promise.resolve(null)
    } catch (error: Exception) {
      promise.reject("SECURE_STORE_WRITE_FAILED", "Encrypted data could not be stored.", error)
    }
  }

  @ReactMethod
  fun removeItem(key: String, promise: Promise) {
    if (preferences.edit().remove(key).commit()) {
      promise.resolve(null)
    } else {
      promise.reject("SECURE_STORE_DELETE_FAILED", "Encrypted data could not be removed.")
    }
  }

  private fun getOrCreateKey(): SecretKey {
    val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER)
    keyStore.load(null)
    val existing = keyStore.getKey(KEY_ALIAS, null)
    if (existing is SecretKey) return existing

    val generator =
        KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER)
    generator.init(
        KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build()
    )
    return generator.generateKey()
  }

  private companion object {
    const val KEYSTORE_PROVIDER = "AndroidKeyStore"
    const val KEY_ALIAS = "tibatrace-pos-v1"
    const val TRANSFORMATION = "AES/GCM/NoPadding"
  }
}
