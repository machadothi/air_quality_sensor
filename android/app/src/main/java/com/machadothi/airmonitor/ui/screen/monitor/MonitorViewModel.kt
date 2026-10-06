package com.machadothi.airmonitor.ui.screen.monitor

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.machadothi.airmonitor.data.AirRepository
import com.machadothi.airmonitor.data.DisplayPage
import com.machadothi.airmonitor.mqtt.BrokerStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MonitorViewModel @Inject constructor(private val repository: AirRepository) : ViewModel() {
    val brokerStatus = repository.brokerStatus
    val boardOnline = repository.boardOnline
    val reading = repository.reading
    val lastUpdateMs = repository.lastUpdateMs
    val history = repository.history
    val status = repository.status
    val display = repository.display
    val events = repository.events

    val brokerHost: String get() = repository.currentSettings.host
    val clientId: String get() = repository.currentSettings.clientId

    /** Polling only runs while the screen is visible (set from MonitorScreen). */
    @Volatile
    private var visible = true

    fun setVisible(visible: Boolean) {
        if (visible && !this.visible) repository.refreshAll()
        this.visible = visible
    }

    /** Ticks every second so "updated 12 s ago" stays current. */
    private val _now = MutableStateFlow(System.currentTimeMillis())
    val now: StateFlow<Long> = _now.asStateFlow()

    init {
        // While this screen exists: fresh readings every 5 s (the board itself
        // only publishes once a minute), status every 30 s.
        viewModelScope.launch {
            var tick = 0
            while (isActive) {
                if (visible && brokerStatus.value == BrokerStatus.Connected) {
                    if (tick % POLL_READING_S == 0) repository.requestReading()
                    if (tick % POLL_STATUS_S == 0) repository.requestStatus()
                }
                _now.value = System.currentTimeMillis()
                delay(1000)
                tick++
            }
        }
    }

    fun refresh() = repository.refreshAll()
    fun nextPage() = repository.nextPage()
    fun reboot() = repository.reboot()
    fun setDisplay(pages: List<DisplayPage>, pageSeconds: Float) = repository.setDisplay(pages, pageSeconds)

    fun disconnect() = repository.disconnect()

    private companion object {
        const val POLL_READING_S = 5
        const val POLL_STATUS_S = 30
    }
}
