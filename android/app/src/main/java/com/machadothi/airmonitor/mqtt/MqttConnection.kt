package com.machadothi.airmonitor.mqtt

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import org.eclipse.paho.client.mqttv3.IMqttActionListener
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken
import org.eclipse.paho.client.mqttv3.IMqttToken
import org.eclipse.paho.client.mqttv3.MqttAsyncClient
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttException
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence
import android.util.Log
import java.util.UUID
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Connection to the MQTT broker, as seen by the UI. */
sealed interface BrokerStatus {
    data object Disconnected : BrokerStatus
    data object Connecting : BrokerStatus
    data object Connected : BrokerStatus
    /** Lost after being connected; Paho is reconnecting by itself. */
    data object Reconnecting : BrokerStatus
    data class Failed(val message: String) : BrokerStatus
}

data class IncomingMessage(val topic: String, val text: String, val retained: Boolean)

/**
 * Thin coroutine wrapper around Eclipse Paho's MqttAsyncClient (MQTT 3.1.1).
 * Paho does the protocol, keepalive and automatic reconnects; this turns its
 * callbacks into flows and suspend functions. QoS 0 throughout, like the board.
 */
class MqttConnection {
    private var client: MqttAsyncClient? = null
    private var topics: List<String> = emptyList()

    private val _status = MutableStateFlow<BrokerStatus>(BrokerStatus.Disconnected)
    val status: StateFlow<BrokerStatus> = _status.asStateFlow()

    private val _messages = MutableSharedFlow<IncomingMessage>(
        extraBufferCapacity = 64,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val messages: SharedFlow<IncomingMessage> = _messages.asSharedFlow()

    /** Connects and subscribes to [subscribeTo]; throws with a readable message on failure. */
    suspend fun connect(host: String, port: Int, username: String, password: String, subscribeTo: List<String>) {
        disconnect()
        _status.value = BrokerStatus.Connecting
        topics = subscribeTo
        // A unique id per app start: two clients with the same id kick each other off the broker.
        val mqtt = MqttAsyncClient("tcp://$host:$port", "air-monitor-app-" + UUID.randomUUID().toString().take(8), MemoryPersistence())
        mqtt.setCallback(object : MqttCallbackExtended {
            override fun connectComplete(reconnect: Boolean, serverURI: String) {
                if (reconnect) {
                    Log.i(TAG, "reconnected")
                    // A clean session forgets subscriptions: subscribe again.
                    runCatching { topics.forEach { mqtt.subscribe(it, 0) } }
                    _status.value = BrokerStatus.Connected
                }
            }

            override fun connectionLost(cause: Throwable?) {
                Log.w(TAG, "connection lost", cause)
                _status.value = BrokerStatus.Reconnecting
            }

            override fun messageArrived(topic: String, message: MqttMessage) {
                _messages.tryEmit(IncomingMessage(topic, message.payload.decodeToString(), message.isRetained))
            }

            override fun deliveryComplete(token: IMqttDeliveryToken?) = Unit
        })
        val options = MqttConnectOptions().apply {
            isCleanSession = true
            isAutomaticReconnect = true
            connectionTimeout = 10
            keepAliveInterval = 30
            if (username.isNotEmpty()) userName = username
            if (password.isNotEmpty()) this.password = password.toCharArray()
        }
        client = mqtt
        Log.i(TAG, "connecting to tcp://$host:$port")
        try {
            // Paho has its own 10 s connect timeout; this is the backstop so the
            // UI can never wait forever.
            withTimeout(CONNECT_TIMEOUT_MS) {
                awaitAction { listener -> mqtt.connect(options, null, listener) }
                subscribeTo.forEach { topic -> awaitAction { listener -> mqtt.subscribe(topic, 0, null, listener) } }
            }
            Log.i(TAG, "connected, subscribed to $subscribeTo")
            _status.value = BrokerStatus.Connected
        } catch (e: Exception) {
            val message = when (e) {
                is MqttException -> describe(e)
                is TimeoutCancellationException -> "No answer from the broker"
                else -> e.message ?: e.javaClass.simpleName
            }
            Log.w(TAG, "connect failed: $message", e)
            runCatching { mqtt.disconnectForcibly(0, 0) }
            runCatching { mqtt.close(true) }
            client = null
            _status.value = BrokerStatus.Failed(message)
            throw IllegalStateException(message, e)
        }
    }

    fun publish(topic: String, text: String) {
        val mqtt = client ?: return
        if (!mqtt.isConnected) return
        runCatching { mqtt.publish(topic, text.encodeToByteArray(), 0, false) }
    }

    fun disconnect() {
        val mqtt = client ?: return
        client = null
        runCatching { mqtt.disconnectForcibly(500, 500) }
        runCatching { mqtt.close(true) }
        _status.value = BrokerStatus.Disconnected
    }

    private fun describe(e: MqttException): String = when (e.reasonCode.toShort()) {
        MqttException.REASON_CODE_FAILED_AUTHENTICATION, MqttException.REASON_CODE_NOT_AUTHORIZED ->
            "The broker refused the username or password"
        MqttException.REASON_CODE_CLIENT_TIMEOUT -> "No answer from the broker (wrong address, or not on the home network?)"
        MqttException.REASON_CODE_SERVER_CONNECT_ERROR -> {
            val cause = e.cause?.message.orEmpty()
            when {
                "EPERM" in cause -> "Network access is blocked for this app (GrapheneOS: allow the Network permission)"
                "ECONNREFUSED" in cause -> "The broker refused the connection (wrong port?)"
                "EHOSTUNREACH" in cause || "ENETUNREACH" in cause -> "Broker not reachable: are you on the home Wi-Fi?"
                e.cause is java.net.SocketTimeoutException ->
                    "No answer from the broker: check the address, the home Wi-Fi, and \"Nearby devices\" permission"
                else -> "Can't reach the broker" + if (cause.isNotEmpty()) " ($cause)" else ""
            }
        }
        else -> e.message ?: "MQTT error ${e.reasonCode}"
    }
}

/**
 * Runs a Paho action, handing it the listener up front (so its result can't be
 * missed), and suspends until it succeeds or fails.
 */
private suspend fun awaitAction(start: (IMqttActionListener) -> Unit): Unit = suspendCancellableCoroutine { cont ->
    start(object : IMqttActionListener {
        override fun onSuccess(asyncActionToken: IMqttToken?) {
            if (cont.isActive) cont.resume(Unit)
        }

        override fun onFailure(asyncActionToken: IMqttToken?, exception: Throwable?) {
            if (cont.isActive) cont.resumeWithException(exception ?: MqttException(MqttException.REASON_CODE_UNEXPECTED_ERROR.toInt()))
        }
    })
}

private const val TAG = "AirMqtt"
private const val CONNECT_TIMEOUT_MS = 20_000L
