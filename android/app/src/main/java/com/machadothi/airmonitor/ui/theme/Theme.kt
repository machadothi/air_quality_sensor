package com.machadothi.airmonitor.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val DarkColors = darkColorScheme(
    primary = Teal,
    onPrimary = Navy950,
    primaryContainer = TealDim,
    onPrimaryContainer = Snow,
    // "secondary" drives selected tabs, segmented buttons, tonal buttons and
    // slider tracks in Material 3; keep it in the teal family.
    secondary = Teal,
    onSecondary = Navy950,
    secondaryContainer = TealDim.copy(alpha = 0.45f),
    onSecondaryContainer = Snow,
    tertiary = Violet,
    error = Coral,
    background = Navy950,
    onBackground = Snow,
    surface = Navy900,
    onSurface = Snow,
    surfaceVariant = Navy800,
    onSurfaceVariant = Mist,
    surfaceContainer = Navy800,
    surfaceContainerHigh = Navy700,
    surfaceContainerHighest = Navy600,
    outline = Navy600,
    outlineVariant = Navy700,
)

private val LightColors = lightColorScheme(
    primary = TealDeep,
    onPrimary = PaperCard,
    secondary = TealDeep,
    secondaryContainer = TealDeep.copy(alpha = 0.15f),
    onSecondaryContainer = Ink,
    tertiary = Violet,
    error = Coral,
    background = Paper,
    onBackground = Ink,
    surface = PaperCard,
    onSurface = Ink,
    surfaceVariant = Paper,
    onSurfaceVariant = InkMuted,
    surfaceContainer = PaperCard,
    surfaceContainerHigh = Paper,
    outline = InkMuted.copy(alpha = 0.3f),
    outlineVariant = InkMuted.copy(alpha = 0.15f),
)

@Composable
fun AirMonitorTheme(
    // The instrument-panel look is the design; set to isSystemInDarkTheme() to follow the phone.
    darkTheme: Boolean = true,
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = AppTypography,
        content = content,
    )
}
