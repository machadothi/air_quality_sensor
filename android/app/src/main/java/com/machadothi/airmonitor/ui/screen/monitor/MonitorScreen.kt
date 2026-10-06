package com.machadothi.airmonitor.ui.screen.monitor

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Dashboard
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Tv
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.machadothi.airmonitor.mqtt.BrokerStatus
import com.machadothi.airmonitor.ui.theme.Amber
import com.machadothi.airmonitor.ui.theme.Coral
import com.machadothi.airmonitor.ui.theme.Lime

private enum class Tab(val label: String, val icon: ImageVector) {
    LIVE("Live", Icons.Rounded.Dashboard),
    DISPLAY("Display", Icons.Rounded.Tv),
    DEVICE("Device", Icons.Rounded.Memory),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MonitorScreen(onEditConnection: () -> Unit, viewModel: MonitorViewModel = hiltViewModel()) {
    val broker by viewModel.brokerStatus.collectAsStateWithLifecycle()
    val online by viewModel.boardOnline.collectAsStateWithLifecycle()
    val lastUpdate by viewModel.lastUpdateMs.collectAsStateWithLifecycle()
    val now by viewModel.now.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableStateOf(Tab.LIVE) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(Unit) { viewModel.events.collect { snackbar.showSnackbar(it) } }
    LifecycleStartEffect(viewModel) {
        viewModel.setVisible(true)
        onStopOrDispose { viewModel.setVisible(false) }
    }

    val (statusText, statusColor) = connectionLine(broker, online, lastUpdate, now)

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Air Monitor", style = MaterialTheme.typography.titleMedium)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            StatusDot(statusColor)
                            Spacer(Modifier.width(6.dp))
                            Text(statusText, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                },
                actions = {
                    IconButton(onClick = { viewModel.disconnect(); onEditConnection() }) {
                        Icon(Icons.Rounded.Settings, "Connection settings")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                Tab.entries.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t,
                        onClick = { tab = t },
                        icon = { Icon(t.icon, null) },
                        label = { Text(t.label) },
                    )
                }
            }
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Box(Modifier.padding(padding).fillMaxSize()) {
            AnimatedContent(
                targetState = tab,
                transitionSpec = {
                    val forward = targetState.ordinal > initialState.ordinal
                    (slideInHorizontally(tween(300)) { if (forward) it / 4 else -it / 4 } + fadeIn(tween(300)))
                        .togetherWith(slideOutHorizontally(tween(300)) { if (forward) -it / 4 else it / 4 } + fadeOut(tween(200)))
                },
                label = "tab",
            ) { t ->
                when (t) {
                    Tab.LIVE -> LiveTab(viewModel)
                    Tab.DISPLAY -> DisplayTab(viewModel)
                    Tab.DEVICE -> DeviceTab(viewModel)
                }
            }
        }
    }
}

/** Status line under the title: broker first, then the board. */
@Composable
private fun connectionLine(broker: BrokerStatus, online: Boolean?, lastUpdate: Long?, now: Long): Pair<String, Color> {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    return when (broker) {
        BrokerStatus.Connecting -> "Connecting to the broker…" to Amber
        BrokerStatus.Reconnecting -> "Broker connection lost, reconnecting…" to Amber
        BrokerStatus.Disconnected -> "Disconnected" to muted
        is BrokerStatus.Failed -> broker.message to Coral
        BrokerStatus.Connected -> when (online) {
            false -> "Board offline" to Coral
            null -> "Waiting for the board…" to Amber
            true -> "Online · " + ago(lastUpdate, now) to Lime
        }
    }
}

internal fun ago(timeMs: Long?, now: Long): String {
    if (timeMs == null) return "no reading yet"
    val s = ((now - timeMs) / 1000).coerceAtLeast(0)
    return when {
        s < 5 -> "updated just now"
        s < 60 -> "updated $s s ago"
        else -> "updated ${s / 60} min ago"
    }
}

@Composable
private fun StatusDot(color: Color) {
    val animated by animateColorAsState(color, label = "dot")
    Box(Modifier.size(8.dp).background(animated, CircleShape))
}
