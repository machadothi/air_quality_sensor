package com.machadothi.airmonitor.mqtt

import com.machadothi.airmonitor.data.AirProtocol
import com.machadothi.airmonitor.data.AirQuality
import com.machadothi.airmonitor.data.DisplayPage
import com.machadothi.airmonitor.data.Response
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Messages as the real board sends them (captured from firmware/commands.py and net.py). */
class AirProtocolTest {
    @Test
    fun readingFromTheStateTopic() {
        val r = AirProtocol.parseReading(
            """{"status": 131, "temperature": 27.2, "eco2": 941, "state": "normal", "aqi": 4, "humidity": 54.0, "tvoc": 764}""",
        )!!
        assertEquals(27.2f, r.temperature!!, 0.001f)
        assertEquals(941f, r.eco2!!, 0.001f)
        assertEquals(AirQuality.POOR, AirQuality.fromAqi(r.aqi))
        assertTrue(!r.warmingUp && !r.sensorMissing)
    }

    @Test
    fun warmUpHasNullAirValues() {
        val r = AirProtocol.parseReading(
            """{"status": 135, "temperature": 27.6, "eco2": null, "state": "warm-up", "aqi": null, "humidity": 52.6, "tvoc": null}""",
        )!!
        assertNull(r.eco2)
        assertNull(AirQuality.fromAqi(r.aqi))
        assertTrue(r.warmingUp)
    }

    @Test
    fun responsesAreTellApartByTheirKeys() {
        val status = AirProtocol.parseResponse(
            """{"ip": "192.168.1.42", "uptime_s": 25, "free_ram": 6128, "lowest_free_ram": 8880, "wifi_rssi": -67, "sensor_errors": 0, "sensor_state": "warm-up"}""",
        )
        assertEquals(-67, (status as Response.Status).status.wifiRssi)

        val display = AirProtocol.parseResponse(
            """{"available": ["air", "eco2", "tvoc", "temperature", "humidity"], "pages": ["temperature", "humidity", "air"], "present": true, "page_s": 3}""",
        )
        assertEquals(
            listOf(DisplayPage.TEMPERATURE, DisplayPage.HUMIDITY, DisplayPage.AIR),
            (display as Response.Display).display.shownPages,
        )

        val error = AirProtocol.parseResponse("""{"error": "/display {\"pages\": [...], \"page_s\": 1-60}"}""")
        assertEquals("""/display {"pages": [...], "page_s": 1-60}""", (error as Response.Error).message)

        assertTrue(AirProtocol.parseResponse("""{"rebooting": true}""") is Response.Rebooting)
        assertTrue(AirProtocol.parseResponse("not json") == null)
    }

    @Test
    fun setDisplayRequestMatchesTheFirmware() {
        assertEquals(
            """/display {"pages": ["air","temperature"], "page_s": 8}""",
            AirProtocol.setDisplay(listOf(DisplayPage.AIR, DisplayPage.TEMPERATURE), 8f),
        )
        assertEquals(
            """/display {"pages": ["eco2"], "page_s": 2.5}""",
            AirProtocol.setDisplay(listOf(DisplayPage.ECO2), 2.5f),
        )
    }
}
