package com.machadothi.airmonitor.ui.screen.monitor

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Air
import androidx.compose.material.icons.rounded.Co2
import androidx.compose.material.icons.rounded.Science
import androidx.compose.material.icons.rounded.Thermostat
import androidx.compose.material.icons.rounded.WaterDrop
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.machadothi.airmonitor.data.AirQuality
import com.machadothi.airmonitor.data.Metric
import com.machadothi.airmonitor.data.Reading
import com.machadothi.airmonitor.ui.components.AnimatedNumber
import com.machadothi.airmonitor.ui.components.CardHeader
import com.machadothi.airmonitor.ui.components.GlowCard
import com.machadothi.airmonitor.ui.components.Sparkline
import com.machadothi.airmonitor.ui.theme.Amber
import com.machadothi.airmonitor.ui.theme.Coral
import com.machadothi.airmonitor.ui.theme.Lime
import com.machadothi.airmonitor.ui.theme.Sky
import com.machadothi.airmonitor.ui.theme.Teal
import com.machadothi.airmonitor.ui.theme.Violet
import kotlin.math.cos
import kotlin.math.sin

/** Gauge colors, excellent → unhealthy. */
private val AqiColors = listOf(Teal, Lime, Amber, Coral, Violet)

@Composable
fun LiveTab(viewModel: MonitorViewModel) {
    val reading by viewModel.reading.collectAsStateWithLifecycle()
    val history by viewModel.history.collectAsStateWithLifecycle()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        AirQualityCard(reading)
        val r = reading
        val airReady = r != null && !r.warmingUp && !r.sensorMissing
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            MetricCard(
                "eCO2", Icons.Rounded.Co2, Sky, r?.eco2.takeIf { airReady }, "ppm", 0,
                eco2Hint(r?.eco2.takeIf { airReady }), history[Metric.ECO2].orEmpty().map { it.value }, Modifier.weight(1f),
            )
            MetricCard(
                "TVOC", Icons.Rounded.Science, Violet, r?.tvoc.takeIf { airReady }, "ppb", 0,
                tvocHint(r?.tvoc.takeIf { airReady }), history[Metric.TVOC].orEmpty().map { it.value }, Modifier.weight(1f),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            MetricCard(
                "Temperature", Icons.Rounded.Thermostat, Amber, r?.temperature, "°C", 1,
                null, history[Metric.TEMPERATURE].orEmpty().map { it.value }, Modifier.weight(1f),
            )
            MetricCard(
                "Humidity", Icons.Rounded.WaterDrop, Teal, r?.humidity, "%", 1,
                humidityHint(r?.humidity), history[Metric.HUMIDITY].orEmpty().map { it.value }, Modifier.weight(1f),
            )
        }
        Text(
            "Charts show readings since the app connected. The board publishes once a minute; " +
                "while this screen is open the app asks for a fresh reading every 5 s.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(vertical = 8.dp),
        )
    }
}

@Composable
private fun AirQualityCard(reading: Reading?) {
    val quality = AirQuality.fromAqi(reading?.aqi).takeIf { reading?.warmingUp == false && !reading.sensorMissing }
    val accent by animateColorAsState(quality?.let { AqiColors[it.ordinal] } ?: MaterialTheme.colorScheme.outline, tween(600), label = "accent")
    GlowCard(Modifier.fillMaxWidth(), accent = accent, highlighted = quality != null && quality.ordinal >= 3) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
            CardHeader(Icons.Rounded.Air, "AIR QUALITY", accent)
            Spacer(Modifier.height(8.dp))
            Box(Modifier.fillMaxWidth(0.82f).aspectRatio(2f), contentAlignment = Alignment.BottomCenter) {
                AqiGauge(quality, warmingUp = reading?.warmingUp == true, modifier = Modifier.fillMaxSize())
                AnimatedContent(
                    targetState = when {
                        reading == null -> "—" to "Waiting for the first reading"
                        reading.sensorMissing -> "No sensor" to "Check the board's wiring"
                        reading.warmingUp -> "Warming up" to "The sensor needs about 3 minutes"
                        quality == null -> "—" to ""
                        else -> quality.label to quality.advice
                    },
                    transitionSpec = { fadeIn(tween(400)) togetherWith fadeOut(tween(250)) },
                    label = "rating",
                ) { (title, advice) ->
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(title, style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
                        Text(
                            advice,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
            }
            if (quality != null) {
                Spacer(Modifier.height(4.dp))
                Text(
                    "Index ${quality.ordinal + 1} of 5",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * Half-circle gauge in five colored segments with a needle that springs to
 * the current index. While warming up, a light sweeps along the arc instead.
 */
@Composable
private fun AqiGauge(quality: AirQuality?, warmingUp: Boolean, modifier: Modifier = Modifier) {
    val target = quality?.let { (it.ordinal + 0.5f) / 5f } ?: 0f
    val position by animateFloatAsState(
        target,
        spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessVeryLow),
        label = "needle",
    )
    val needleAlpha by animateFloatAsState(if (quality != null) 1f else 0f, tween(500), label = "needleAlpha")
    val sweep by rememberInfiniteTransition(label = "sweep")
        .animateFloat(0f, 1f, infiniteRepeatable(tween(1800, easing = LinearEasing), RepeatMode.Restart), label = "sweep")
    val track = MaterialTheme.colorScheme.surfaceVariant
    val needleColor = MaterialTheme.colorScheme.onSurface

    Canvas(modifier) {
        val stroke = size.width * 0.07f
        val radius = size.width / 2 - stroke
        val center = Offset(size.width / 2, size.height - stroke / 2)
        val arcSize = Size(radius * 2, radius * 2)
        val topLeft = Offset(center.x - radius, center.y - radius)
        val gap = 3f
        val segment = 180f / 5
        for (i in 0 until 5) {
            val active = quality?.ordinal == i
            val color = when {
                quality == null -> track
                active -> AqiColors[i]
                else -> AqiColors[i].copy(alpha = 0.28f)
            }
            drawArc(color, 180f + i * segment + gap / 2, segment - gap, false, topLeft, arcSize, style = Stroke(stroke, cap = StrokeCap.Butt))
        }
        if (warmingUp) {
            drawArc(Teal.copy(alpha = 0.8f), 180f + sweep * 160f, 20f, false, topLeft, arcSize, style = Stroke(stroke, cap = StrokeCap.Round))
        }
        if (needleAlpha > 0f) {
            val angle = 180f + position * 180f
            rotate(angle - 180f, center) {
                drawLine(needleColor.copy(alpha = needleAlpha), center, Offset(center.x - radius * 0.72f, center.y), strokeWidth = stroke * 0.32f, cap = StrokeCap.Round)
            }
            drawCircle(needleColor.copy(alpha = needleAlpha), stroke * 0.42f, center)
            // A small dot on the arc where the needle points.
            val rad = Math.toRadians(angle.toDouble())
            val tip = Offset(center.x + radius * cos(rad).toFloat(), center.y + radius * sin(rad).toFloat())
            drawCircle(Color.White.copy(alpha = needleAlpha), stroke * 0.22f, tip)
        }
    }
}

@Composable
private fun MetricCard(
    title: String,
    icon: ImageVector,
    accent: Color,
    value: Float?,
    unit: String,
    decimals: Int,
    hint: String?,
    history: List<Float>,
    modifier: Modifier = Modifier,
) {
    GlowCard(modifier, accent = accent) {
        Column {
            CardHeader(icon, title.uppercase(), accent)
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                AnimatedNumber(value, format = { "%.${decimals}f".format(it) })
                Spacer(Modifier.width(4.dp))
                Text(unit, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(bottom = 5.dp))
            }
            Text(
                hint ?: " ",
                style = MaterialTheme.typography.labelSmall,
                color = accent,
                maxLines = 1,
            )
            Spacer(Modifier.height(8.dp))
            Sparkline(history.takeLast(120), accent, Modifier.fillMaxWidth().height(36.dp))
        }
    }
}

private fun eco2Hint(ppm: Float?): String? = when {
    ppm == null -> null
    ppm < 800 -> "Fresh"
    ppm < 1000 -> "Fine"
    ppm < 1500 -> "Getting stuffy"
    else -> "Ventilate"
}

private fun tvocHint(ppb: Float?): String? = when {
    ppb == null -> null
    ppb < 220 -> "Low"
    ppb < 660 -> "Moderate"
    ppb < 2200 -> "High"
    else -> "Very high"
}

private fun humidityHint(pct: Float?): String? = when {
    pct == null -> null
    pct < 30 -> "Dry"
    pct <= 60 -> "Comfortable"
    else -> "Humid"
}
