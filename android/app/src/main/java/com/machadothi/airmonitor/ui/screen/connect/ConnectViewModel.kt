package com.machadothi.airmonitor.ui.screen.connect

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.toRoute
import com.machadothi.airmonitor.data.AirRepository
import com.machadothi.airmonitor.data.BrokerSettings
import com.machadothi.airmonitor.ui.navigation.NavRoutes
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ConnectUiState(
    val loaded: Boolean = false,
    val settings: BrokerSettings = BrokerSettings(),
    val portText: String = "1883",
    val connecting: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class ConnectViewModel @Inject constructor(
    private val repository: AirRepository,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {
    private val _state = MutableStateFlow(ConnectUiState())
    val state: StateFlow<ConnectUiState> = _state.asStateFlow()

    /** Set once connected; the screen navigates on it. */
    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected.asStateFlow()

    init {
        val autoConnect = savedStateHandle.toRoute<NavRoutes.Connect>().autoConnect
        viewModelScope.launch {
            val saved = repository.savedSettings()
            _state.value = ConnectUiState(loaded = true, settings = saved, portText = saved.port.toString())
            if (autoConnect && saved.isComplete) connect()
        }
    }

    fun edit(change: BrokerSettings.() -> BrokerSettings) = _state.update { it.copy(settings = it.settings.change(), error = null) }

    fun editPort(text: String) = _state.update {
        val digits = text.filter(Char::isDigit).take(5)
        it.copy(portText = digits, settings = it.settings.copy(port = digits.toIntOrNull() ?: 0), error = null)
    }

    fun connect() {
        val settings = _state.value.settings
        if (!settings.isComplete || _state.value.connecting) return
        _state.update { it.copy(connecting = true, error = null) }
        viewModelScope.launch {
            try {
                repository.connect(settings)
                _connected.value = true
            } catch (e: Exception) {
                _state.update { it.copy(error = e.message ?: "Couldn't connect") }
            } finally {
                _state.update { it.copy(connecting = false) }
            }
        }
    }

    fun forget() {
        viewModelScope.launch {
            repository.forgetSettings()
            _state.value = ConnectUiState(loaded = true)
        }
    }
}
