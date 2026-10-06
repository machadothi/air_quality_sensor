package com.machadothi.airmonitor.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.first
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Where the broker is and which board to talk to. Typed in once on the
 * Connect screen and kept only on the phone (app-private storage, excluded
 * from backups: allowBackup="false"); nothing is built into the app.
 */
data class BrokerSettings(
    val host: String = "",
    val port: Int = 1883,
    val username: String = "",
    val password: String = "",
    /** The board's mqtt.client_id: its topics are esp/<clientId>/... */
    val clientId: String = "",
    val stateTopic: String = AirProtocol.DEFAULT_STATE_TOPIC,
) {
    val isComplete: Boolean get() = host.isNotBlank() && clientId.isNotBlank() && port in 1..65535
}

private val Context.store: DataStore<Preferences> by preferencesDataStore("broker")

@Singleton
class SettingsStore @Inject constructor(@ApplicationContext private val context: Context) {
    private object Keys {
        val host = stringPreferencesKey("host")
        val port = intPreferencesKey("port")
        val username = stringPreferencesKey("username")
        val password = stringPreferencesKey("password")
        val clientId = stringPreferencesKey("client_id")
        val stateTopic = stringPreferencesKey("state_topic")
    }

    suspend fun load(): BrokerSettings {
        val p = context.store.data.first()
        return BrokerSettings(
            host = p[Keys.host] ?: "",
            port = p[Keys.port] ?: 1883,
            username = p[Keys.username] ?: "",
            password = p[Keys.password] ?: "",
            clientId = p[Keys.clientId] ?: "",
            stateTopic = p[Keys.stateTopic] ?: AirProtocol.DEFAULT_STATE_TOPIC,
        )
    }

    suspend fun save(settings: BrokerSettings) {
        context.store.edit {
            it[Keys.host] = settings.host.trim()
            it[Keys.port] = settings.port
            it[Keys.username] = settings.username
            it[Keys.password] = settings.password
            it[Keys.clientId] = settings.clientId.trim()
            it[Keys.stateTopic] = settings.stateTopic.trim()
        }
    }

    suspend fun clear() {
        context.store.edit { it.clear() }
    }
}
