package com.machadothi.airmonitor.ui.navigation

import kotlinx.serialization.Serializable

object NavRoutes {
    /** autoConnect: connect right away with the saved settings (app start). */
    @Serializable
    data class Connect(val autoConnect: Boolean = true)

    @Serializable
    data object Monitor
}
