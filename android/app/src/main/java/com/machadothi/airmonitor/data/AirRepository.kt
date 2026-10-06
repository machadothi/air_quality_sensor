package com.machadothi.airmonitor.data

import com.machadothi.airmonitor.mqtt.BrokerStatus
import com.machadothi.airmonitor.mqtt.MqttConnection
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

/** Readings that get a chart. */
enum class Metric { ECO2, TVOC, TEMPERATURE, HUMIDITY }

data class Point(val timeMs: Long, val value: Float)

/**
 * Everything the app knows about the air monitor, fed by MQTT:
 * readings (retained state topic + answers to /read_all), online/offline
 * (availability topic), device status, display settings. The UI only reads
 * these flows and calls the request functions.
 */
@Singleton
class AirRepository @Inject constructor(private val store: SettingsStore) {
    private val mqtt = MqttConnection()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var settings = BrokerSettings()

    val brokerStatus: StateFlow<BrokerStatus> = mqtt.status

    /** true = online, false = offline (the broker's last will), null = not known yet. */
    private val _boardOnline = MutableStateFlow<Boolean?>(null)
    val boardOnline: StateFlow<Boolean?> = _boardOnline.asStateFlow()

    private val _reading = MutableStateFlow<Reading?>(null)
    val reading: StateFlow<Reading?> = _reading.asStateFlow()

    private val _lastUpdateMs = MutableStateFlow<Long?>(null)
    val lastUpdateMs: StateFlow<Long?> = _lastUpdateMs.asStateFlow()

    private val _history = MutableStateFlow<Map<Metric, List<Point>>>(emptyMap())
    val history: StateFlow<Map<Metric, List<Point>>> = _history.asStateFlow()

    private val _status = MutableStateFlow<DeviceStatus?>(null)
    val status: StateFlow<DeviceStatus?> = _status.asStateFlow()

    private val _display = MutableStateFlow<DisplayState?>(null)
    val display: StateFlow<DisplayState?> = _display.asStateFlow()

    /** One-off messages for a snackbar (errors from the board, "rebooting"). */
    private val _events = MutableSharedFlow<String>(extraBufferCapacity = 8, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val events: SharedFlow<String> = _events.asSharedFlow()

    val currentSettings: BrokerSettings get() = settings

    init {
        scope.launch { mqtt.messages.collect { onMessage(it.topic, it.text) } }
    }

    suspend fun savedSettings(): BrokerSettings = store.load()

    /** Saves the settings and connects; throws with a readable message on failure. */
    suspend fun connect(newSettings: BrokerSettings) {
        store.save(newSettings)
        if (newSettings.clientId != settings.clientId || newSettings.stateTopic != settings.stateTopic) clearBoardData()
        settings = newSettings
        mqtt.connect(
            host = newSettings.host.trim(),
            port = newSettings.port,
            username = newSettings.username,
            password = newSettings.password,
            subscribeTo = listOf(
                newSettings.stateTopic,
                AirProtocol.responseTopic(newSettings.clientId),
                AirProtocol.availabilityTopic(newSettings.clientId),
            ),
        )
        refreshAll()
    }

    fun disconnect() = mqtt.disconnect()

    suspend fun forgetSettings() {
        disconnect()
        store.clear()
        settings = BrokerSettings()
        clearBoardData()
    }

    // --- requests (answers arrive on the response topic) ---------------------------

    fun refreshAll() {
        request(AirProtocol.READ_ALL)
        request(AirProtocol.STATUS)
        request(AirProtocol.DISPLAY)
    }

    fun requestReading() = request(AirProtocol.READ_ALL)
    fun requestStatus() = request(AirProtocol.STATUS)
    fun nextPage() = request(AirProtocol.DISPLAY_NEXT)
    fun reboot() = request(AirProtocol.REBOOT)

    fun setDisplay(pages: List<DisplayPage>, pageSeconds: Float) {
        // Show the choice at once; the board's answer confirms or corrects it.
        _display.update { it?.copy(pages = pages.map(DisplayPage::key), pageSeconds = pageSeconds) }
        request(AirProtocol.setDisplay(pages, pageSeconds))
    }

    private fun request(text: String) {
        if (settings.clientId.isNotEmpty()) mqtt.publish(AirProtocol.requestTopic(settings.clientId), text)
    }

    // --- incoming ----------------------------------------------------------------------

    private fun onMessage(topic: String, text: String) {
        when (topic) {
            settings.stateTopic -> AirProtocol.parseReading(text)?.let(::onReading)
            AirProtocol.availabilityTopic(settings.clientId) -> _boardOnline.value = text.trim() == "online"
            AirProtocol.responseTopic(settings.clientId) -> when (val response = AirProtocol.parseResponse(text)) {
                is Response.Reading -> onReading(response.reading)
                is Response.Status -> _status.value = response.status
                is Response.Display -> _display.value = response.display
                is Response.PageShown -> Unit
                Response.Rebooting -> _events.tryEmit("The board is restarting; back in about 10 s")
                is Response.Error -> {
                    _events.tryEmit("Board: ${response.message}")
                    request(AirProtocol.DISPLAY)   // undo an optimistic display change
                }
                null -> Unit
            }
        }
    }

    private fun onReading(reading: Reading) {
        val now = System.currentTimeMillis()
        _reading.value = reading
        _lastUpdateMs.value = now
        _boardOnline.value = _boardOnline.value ?: true
        _history.update { old ->
            buildMap {
                for (metric in Metric.entries) {
                    val value = when (metric) {
                        Metric.ECO2 -> reading.eco2
                        Metric.TVOC -> reading.tvoc
                        Metric.TEMPERATURE -> reading.temperature
                        Metric.HUMIDITY -> reading.humidity
                    }
                    val points = old[metric].orEmpty()
                    put(metric, if (value == null) points else (points + Point(now, value)).takeLast(HISTORY_POINTS))
                }
            }
        }
    }

    private fun clearBoardData() {
        _boardOnline.value = null
        _reading.value = null
        _lastUpdateMs.value = null
        _history.value = emptyMap()
        _status.value = null
        _display.value = null
    }

    private companion object {
        /** At one reading every 5 s: the last hour. */
        const val HISTORY_POINTS = 720
    }
}
