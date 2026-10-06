package com.machadothi.airmonitor.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.roundToInt

/**
 * Slider for values spanning orders of magnitude (e.g. 10 ms to 60 s): the
 * position is logarithmic, so every decade gets the same room.
 */
@Composable
fun LabeledSlider(
    label: String,
    valueText: String,
    value: Float,
    range: ClosedFloatingPointRange<Float>,
    onChange: (Float) -> Unit,
    modifier: Modifier = Modifier,
    logarithmic: Boolean = false,
    hint: String? = null,
    onChangeFinished: (() -> Unit)? = null,
) {
    val lo = range.start
    val hi = range.endInclusive
    fun toPosition(v: Float) = if (logarithmic) (ln(v / lo) / ln(hi / lo)) else (v - lo) / (hi - lo)
    fun fromPosition(p: Float) = if (logarithmic) lo * exp(p * ln(hi / lo)) else lo + p * (hi - lo)

    Column(modifier) {
        Row(Modifier.fillMaxWidth()) {
            Text(label, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            Text(valueText, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.primary)
        }
        Slider(
            value = toPosition(value.coerceIn(lo, hi)),
            onValueChange = { onChange(fromPosition(it)) },
            onValueChangeFinished = onChangeFinished,
        )
        if (hint != null) {
            Text(hint, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Rounds to a "nice" step so sliders land on readable values. */
fun niceRound(value: Float): Int = when {
    value < 100 -> (value / 5).roundToInt() * 5
    value < 1000 -> (value / 10).roundToInt() * 10
    value < 10000 -> (value / 100).roundToInt() * 100
    else -> (value / 1000).roundToInt() * 1000
}

fun formatMs(ms: Int): String = if (ms < 1000) "$ms ms" else "%.1f s".format(ms / 1000f).replace(".0 s", " s")
