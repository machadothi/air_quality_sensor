package com.machadothi.airmonitor.ui.screen.monitor

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Air
import androidx.compose.material.icons.rounded.Co2
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.KeyboardArrowUp
import androidx.compose.material.icons.rounded.Science
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material.icons.rounded.Thermostat
import androidx.compose.material.icons.rounded.Tv
import androidx.compose.material.icons.rounded.WaterDrop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.machadothi.airmonitor.data.AirProtocol
import com.machadothi.airmonitor.data.DisplayPage
import com.machadothi.airmonitor.data.DisplayState
import com.machadothi.airmonitor.ui.components.AppSwitch
import com.machadothi.airmonitor.ui.components.CardHeader
import com.machadothi.airmonitor.ui.components.GlowCard
import com.machadothi.airmonitor.ui.components.LabeledSlider
import com.machadothi.airmonitor.ui.theme.Lime
import kotlinx.coroutines.delay

private val DisplayPage.icon: ImageVector
    get() = when (this) {
        DisplayPage.AIR -> Icons.Rounded.Air
        DisplayPage.ECO2 -> Icons.Rounded.Co2
        DisplayPage.TVOC -> Icons.Rounded.Science
        DisplayPage.TEMPERATURE -> Icons.Rounded.Thermostat
        DisplayPage.HUMIDITY -> Icons.Rounded.WaterDrop
    }

/** OLED-ish cyan on black, like the real module. */
private val OledInk = Color(0xFF8FD8FF)

@Composable
fun DisplayTab(viewModel: MonitorViewModel) {
    val display by viewModel.display.collectAsStateWithLifecycle()
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        val d = display
        if (d == null) {
            Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Column
        }
        OledPreview(d)
        DisplayCard(d, onChange = viewModel::setDisplay, onNext = viewModel::nextPage)
    }
}

/**
 * A small stand-in for the board's OLED that cycles through the chosen pages
 * at the chosen pace, sliding like the real one, so a change can be judged
 * before walking over to the board.
 */
@Composable
private fun OledPreview(display: DisplayState) {
    val pages = display.shownPages
    var index by remember(pages) { mutableIntStateOf(0) }
    LaunchedEffect(pages, display.pageSeconds) {
        while (pages.size > 1) {
            delay((display.pageSeconds * 1000).toLong())
            index = (index + 1) % pages.size
        }
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
        Surface(
            shape = RoundedCornerShape(10.dp),
            color = Color(0xFF14181F),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
            modifier = Modifier.fillMaxWidth(0.62f),
        ) {
            Box(
                Modifier
                    .padding(10.dp)
                    .fillMaxWidth()
                    .aspectRatio(2f)
                    .background(Color.Black, RoundedCornerShape(3.dp)),
            ) {
                val page = pages.getOrNull(index % pages.size.coerceAtLeast(1))
                AnimatedContent(
                    targetState = page,
                    transitionSpec = { slideInHorizontally(tween(550)) { it } togetherWith slideOutHorizontally(tween(550)) { -it } },
                    label = "oled",
                ) { p ->
                    Column(Modifier.fillMaxSize().padding(8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (p != null) Icon(p.icon, null, tint = OledInk, modifier = Modifier.size(12.dp))
                            Spacer(Modifier.width(4.dp))
                            Text(p?.label ?: "", color = OledInk, fontSize = 9.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
                        }
                        Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                            Text(
                                if (p == null) "" else "▮▮▮",
                                color = OledInk.copy(alpha = 0.85f),
                                fontSize = 22.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                        }
                        PageDots(pages.size, index % pages.size.coerceAtLeast(1))
                    }
                }
            }
        }
        Text(
            if (display.present) "Preview of the board's display" else "The board found no display at start-up",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 6.dp),
        )
    }
}

@Composable
private fun PageDots(count: Int, active: Int) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
        repeat(count) { i ->
            Box(
                Modifier
                    .padding(horizontal = 2.dp)
                    .size(width = if (i == active) 7.dp else 3.dp, height = 3.dp)
                    .background(OledInk, CircleShape),
            )
        }
    }
}

/**
 * Pages on, off and in order, and seconds per page. Every change is sent at
 * once; the board applies it at its next page change and stores it.
 */
@Composable
private fun DisplayCard(display: DisplayState, onChange: (List<DisplayPage>, Float) -> Unit, onNext: () -> Unit) {
    val shown = display.shownPages
    // The shown pages in their order, then the hidden ones.
    val rows = shown + DisplayPage.entries.filter { it !in shown }
    // Follows the slider while dragging; sent to the board when released.
    var seconds by remember(display.pageSeconds) { mutableFloatStateOf(display.pageSeconds) }

    GlowCard(Modifier.fillMaxWidth(), accent = Lime) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CardHeader(Icons.Rounded.Tv, "DISPLAY", Lime, Modifier.weight(1f))
                FilledTonalButton(onClick = onNext, enabled = display.present) {
                    Icon(Icons.Rounded.SkipNext, null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Next page")
                }
            }
            AnimatedVisibility(visible = !display.present) {
                Text(
                    "No display was found when the board started. Check the OLED's wiring, then reboot the board (Device tab).",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 6.dp),
                )
            }
            LabeledSlider(
                label = "Each page for",
                valueText = formatSeconds(seconds),
                value = seconds,
                range = AirProtocol.PAGE_SECONDS_MIN..AirProtocol.PAGE_SECONDS_MAX,
                logarithmic = true,
                onChange = { seconds = roundSeconds(it) },
                onChangeFinished = { onChange(shown, seconds) },
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            )
            Text(
                "${shown.size} of ${DisplayPage.entries.size} pages, in this order",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 4.dp),
            )
            rows.forEach { page ->
                val on = page in shown
                val position = shown.indexOf(page)
                Row(Modifier.fillMaxWidth().padding(vertical = 1.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(24.dp).border(1.dp, if (on) Lime else MaterialTheme.colorScheme.outline, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(if (on) "${position + 1}" else "", style = MaterialTheme.typography.labelSmall, color = Lime)
                    }
                    Spacer(Modifier.width(10.dp))
                    Icon(page.icon, null, tint = if (on) Lime else MaterialTheme.colorScheme.outline, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(10.dp))
                    Text(
                        page.label,
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (on) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    IconButton(onClick = { onChange(shown.move(position, -1), seconds) }, enabled = on && position > 0) {
                        Icon(Icons.Rounded.KeyboardArrowUp, "Earlier")
                    }
                    IconButton(onClick = { onChange(shown.move(position, +1), seconds) }, enabled = on && position < shown.size - 1) {
                        Icon(Icons.Rounded.KeyboardArrowDown, "Later")
                    }
                    AppSwitch(
                        checked = on,
                        // The board needs at least one page.
                        enabled = display.present && !(on && shown.size == 1),
                        onCheckedChange = { checked -> onChange(if (checked) shown + page else shown - page, seconds) },
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
        }
    }
}

private fun List<DisplayPage>.move(index: Int, by: Int): List<DisplayPage> {
    val target = index + by
    if (index !in indices || target !in indices) return this
    return toMutableList().apply { add(target, removeAt(index)) }
}

/** Half-second steps below 10 s, whole seconds above. */
private fun roundSeconds(s: Float): Float {
    val step = if (s < 10f) 0.5f else 1f
    return (Math.round(s / step) * step).coerceIn(AirProtocol.PAGE_SECONDS_MIN, AirProtocol.PAGE_SECONDS_MAX)
}

private fun formatSeconds(s: Float): String = "%.1f s".format(s).replace(".0 s", " s")
