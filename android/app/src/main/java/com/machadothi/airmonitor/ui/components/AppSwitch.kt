package com.machadothi.airmonitor.ui.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/**
 * Switch with a clearly visible "off" state. Material's default draws the off
 * thumb in `outline` on a `surfaceContainerHighest` track; in this app's dark
 * palette both are the same navy, so the thumb disappeared when off.
 */
@Composable
fun AppSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val colors = MaterialTheme.colorScheme
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        modifier = modifier,
        enabled = enabled,
        colors = SwitchDefaults.colors(
            uncheckedThumbColor = colors.onSurfaceVariant,
            uncheckedBorderColor = colors.onSurfaceVariant,
            uncheckedTrackColor = colors.surfaceVariant,
        ),
    )
}
