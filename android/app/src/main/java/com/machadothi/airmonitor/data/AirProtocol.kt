package com.machadothi.airmonitor.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The air monitor's MQTT protocol, as implemented in firmware/net.py and
 * firmware/commands.py (documented in docs/communication.md). Change both
 * sides together.
 */
object AirProtocol {
    const val DEFAULT_STATE_TOPIC = "esp/air_quality_sensor"

    fun requestTopic(clientId: String) = "esp/$clientId/request"
    fun responseTopic(clientId: String) = "esp/$clientId/response"
    fun availabilityTopic(clientId: String) = "esp/$clientId/availability"

    const val READ_ALL = "/read_all"
    const val STATUS = "/status"
    const val DISPLAY = "/display"
    const val DISPLAY_NEXT = "/display/next"
    const val REBOOT = "/reboot"

    const val PAGE_SECONDS_MIN = 1f
    const val PAGE_SECONDS_MAX = 60f

    private val json = Json { ignoreUnknownKeys = true }

    /** `/display {"pages": [...], "page_s": n}` */
    fun setDisplay(pages: List<DisplayPage>, pageSeconds: Float): String {
        val list = pages.joinToString(",") { "\"${it.key}\"" }
        // Whole seconds go out as integers, like the firmware's own defaults.
        val seconds = if (pageSeconds % 1f == 0f) pageSeconds.toInt().toString() else "%.1f".format(java.util.Locale.ROOT, pageSeconds)
        return "$DISPLAY {\"pages\": [$list], \"page_s\": $seconds}"
    }

    fun parseReading(text: String): Reading? = runCatching { json.decodeFromString<Reading>(text) }.getOrNull()

    /** The board answers every request on one topic; the keys say which answer it is. */
    fun parseResponse(text: String): Response? {
        val obj: JsonObject = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return null
        return runCatching {
            when {
                "error" in obj -> Response.Error(obj.getValue("error").jsonPrimitive.content)
                "pages" in obj -> Response.Display(json.decodeFromJsonElement<DisplayState>(obj))
                "uptime_s" in obj -> Response.Status(json.decodeFromJsonElement<DeviceStatus>(obj))
                "temperature" in obj -> Response.Reading(json.decodeFromJsonElement<Reading>(obj))
                "page" in obj -> Response.PageShown(obj.getValue("page").jsonPrimitive.content)
                "rebooting" in obj -> Response.Rebooting
                else -> null
            }
        }.getOrNull()
    }
}

/** One reading. Air values are null while the ENS160 warms up; all are null for a missing sensor. */
@Serializable
data class Reading(
    val temperature: Float? = null,
    val humidity: Float? = null,
    val eco2: Float? = null,
    val tvoc: Float? = null,
    val aqi: Int? = null,
    val state: String = "",
    val status: Int? = null,
) {
    val warmingUp: Boolean get() = state == "warm-up" || state == "start-up"
    val sensorMissing: Boolean get() = state == "no sensor"
}

@Serializable
data class DeviceStatus(
    val ip: String = "",
    @SerialName("wifi_rssi") val wifiRssi: Int? = null,
    @SerialName("uptime_s") val uptimeS: Long = 0,
    @SerialName("free_ram") val freeRam: Int? = null,
    @SerialName("lowest_free_ram") val lowestFreeRam: Int? = null,
    @SerialName("sensor_errors") val sensorErrors: Int = 0,
    @SerialName("sensor_state") val sensorState: String = "",
)

@Serializable
data class DisplayState(
    val present: Boolean = true,
    val pages: List<String> = emptyList(),
    @SerialName("page_s") val pageSeconds: Float = 5f,
    val available: List<String> = emptyList(),
) {
    val shownPages: List<DisplayPage> get() = pages.mapNotNull(DisplayPage::fromKey)
}

sealed interface Response {
    data class Reading(val reading: com.machadothi.airmonitor.data.Reading) : Response
    data class Status(val status: DeviceStatus) : Response
    data class Display(val display: DisplayState) : Response
    data class PageShown(val page: String) : Response
    data object Rebooting : Response
    data class Error(val message: String) : Response
}

/** The board's display pages (firmware/app.py PAGE_NAMES). */
enum class DisplayPage(val key: String, val label: String) {
    AIR("air", "Air quality"),
    ECO2("eco2", "CO2 (eCO2)"),
    TVOC("tvoc", "TVOC"),
    TEMPERATURE("temperature", "Temperature"),
    HUMIDITY("humidity", "Humidity");

    companion object {
        fun fromKey(key: String): DisplayPage? = entries.firstOrNull { it.key == key }
    }
}

/** The ENS160's 1-5 scale (German UBA). */
enum class AirQuality(val label: String, val advice: String) {
    EXCELLENT("Excellent", "Fresh air"),
    GOOD("Good", "Nothing to do"),
    MODERATE("Moderate", "Ventilate soon"),
    POOR("Poor", "Open a window"),
    UNHEALTHY("Unhealthy", "Ventilate now");

    companion object {
        fun fromAqi(aqi: Int?): AirQuality? = aqi?.takeIf { it in 1..5 }?.let { entries[it - 1] }
    }
}
