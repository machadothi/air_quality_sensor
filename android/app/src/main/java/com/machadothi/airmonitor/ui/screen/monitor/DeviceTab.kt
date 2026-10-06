package com.machadothi.airmonitor.ui.screen.monitor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Hub
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.RestartAlt
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.machadothi.airmonitor.data.AirProtocol
import com.machadothi.airmonitor.data.DeviceStatus
import com.machadothi.airmonitor.ui.components.CardHeader
import com.machadothi.airmonitor.ui.components.ConfirmDialog
import com.machadothi.airmonitor.ui.components.GlowCard
import com.machadothi.airmonitor.ui.components.Labeled
import com.machadothi.airmonitor.ui.components.SignalBars
import com.machadothi.airmonitor.ui.theme.Coral
import com.machadothi.airmonitor.ui.theme.Sky
import com.machadothi.airmonitor.ui.theme.Violet

/** The ESP8266 has about 36 KB of RAM for MicroPython; used to scale the RAM bar. */
private const val TOTAL_RAM = 36_000f

@Composable
fun DeviceTab(viewModel: MonitorViewModel) {
    val status by viewModel.status.collectAsStateWithLifecycle()
    var confirmReboot by rememberSaveable { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        StatusCard(status, onRefresh = viewModel::refresh)

        GlowCard(Modifier.fillMaxWidth(), accent = Violet) {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                CardHeader(Icons.Rounded.Hub, "MQTT", Violet)
                Labeled("Broker", viewModel.brokerHost)
                Labeled("Requests", AirProtocol.requestTopic(viewModel.clientId))
                Labeled("Responses", AirProtocol.responseTopic(viewModel.clientId))
                Labeled("Online / offline", AirProtocol.availabilityTopic(viewModel.clientId))
            }
        }

        OutlinedButton(onClick = { confirmReboot = true }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Rounded.RestartAlt, null, tint = Coral)
            Spacer(Modifier.width(8.dp))
            Text("Restart the board")
        }
        Text(
            "After a restart the air sensor warms up again for about 3 minutes.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    if (confirmReboot) {
        ConfirmDialog(
            title = "Restart the board?",
            text = "It is back in about 10 s; air readings return after the 3-minute warm-up.",
            confirmLabel = "Restart",
            onConfirm = viewModel::reboot,
            onDismiss = { confirmReboot = false },
        )
    }
}

@Composable
private fun StatusCard(status: DeviceStatus?, onRefresh: () -> Unit) {
    GlowCard(Modifier.fillMaxWidth(), accent = Sky) {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CardHeader(Icons.Rounded.Memory, "BOARD", Sky, Modifier.weight(1f))
                IconButton(onClick = onRefresh) { Icon(Icons.Rounded.Refresh, "Refresh") }
            }
            if (status == null) {
                Text("Waiting for the board's status…", color = MaterialTheme.colorScheme.onSurfaceVariant)
                return@Column
            }
            Row {
                Labeled("IP address", status.ip.ifEmpty { "—" }, Modifier.weight(1f))
                Labeled("Up for", formatUptime(status.uptimeS), Modifier.weight(1f))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Wi-Fi signal", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        SignalBars(status.wifiRssi, color = Sky)
                        Spacer(Modifier.width(8.dp))
                        Text(status.wifiRssi?.let { "$it dBm" } ?: "—", style = MaterialTheme.typography.bodyMedium)
                    }
                }
                Labeled("Sensor", sensorLabel(status), Modifier.weight(1f))
            }
            status.freeRam?.let { free ->
                Column {
                    Row {
                        Text("Free memory", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
                        Text(
                            "%.1f KB · lowest %.1f KB".format(free / 1024f, (status.lowestFreeRam ?: free) / 1024f),
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                    Spacer(Modifier.height(6.dp))
                    LinearProgressIndicator(
                        progress = { ((status.lowestFreeRam ?: free) / TOTAL_RAM).coerceIn(0f, 1f) },
                        color = Sky,
                        trackColor = MaterialTheme.colorScheme.surfaceVariant,
                        strokeCap = StrokeCap.Round,
                        modifier = Modifier.fillMaxWidth().height(6.dp),
                    )
                }
            }
        }
    }
}

private fun sensorLabel(status: DeviceStatus): String {
    val state = when (status.sensorState) {
        "normal" -> "OK"
        "warm-up" -> "Warming up"
        "start-up" -> "First start-up"
        "no sensor" -> "Not found"
        "" -> "—"
        else -> status.sensorState
    }
    return if (status.sensorErrors > 0) "$state · ${status.sensorErrors} errors" else state
}

private fun formatUptime(seconds: Long): String = when {
    seconds < 60 -> "$seconds s"
    seconds < 3600 -> "${seconds / 60} min"
    seconds < 86_400 -> "${seconds / 3600} h ${seconds % 3600 / 60} min"
    else -> "${seconds / 86_400} d ${seconds % 86_400 / 3600} h"
}
