package com.machadothi.airmonitor.ui.screen.connect

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Air
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.machadothi.airmonitor.ui.components.ConfirmDialog
import com.machadothi.airmonitor.ui.components.GlowCard
import com.machadothi.airmonitor.ui.components.SectionTitle

@Composable
fun ConnectScreen(onConnected: () -> Unit, viewModel: ConnectViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val connected by viewModel.connected.collectAsStateWithLifecycle()
    LaunchedEffect(connected) { if (connected) onConnected() }

    // Android 17+ blocks the home network unless the user allows it ("Nearby devices").
    val context = LocalContext.current
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) viewModel.connect() else viewModel.permissionDenied()
    }
    val connectWithPermission = {
        if (hasLocalNetworkPermission(context)) viewModel.connect()
        else permissionLauncher.launch(Manifest.permission.ACCESS_LOCAL_NETWORK)
    }
    LaunchedEffect(state.autoConnect) { if (state.autoConnect) connectWithPermission() }

    var showPassword by rememberSaveable { mutableStateOf(false) }
    var showAdvanced by rememberSaveable { mutableStateOf(false) }
    var confirmForget by rememberSaveable { mutableStateOf(false) }
    val s = state.settings

    Column(
        Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Logo(busy = state.connecting)
        Text(
            "Air Monitor",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onBackground,
            modifier = Modifier.fillMaxWidth(),
            textAlign = TextAlign.Center,
        )
        Text(
            "Connects to the air sensor through your MQTT broker. Works on the home network.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 16.dp),
            textAlign = TextAlign.Center,
        )

        if (!state.loaded) return@Column

        GlowCard(Modifier.fillMaxWidth()) {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                SectionTitle("Broker")
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = s.host,
                        onValueChange = { v -> viewModel.edit { copy(host = v) } },
                        label = { Text("Address") },
                        placeholder = { Text("192.168.1.10") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = state.portText,
                        onValueChange = viewModel::editPort,
                        label = { Text("Port") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
                        modifier = Modifier.width(96.dp),
                    )
                }
                OutlinedTextField(
                    value = s.username,
                    onValueChange = { v -> viewModel.edit { copy(username = v) } },
                    label = { Text("Username") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = s.password,
                    onValueChange = { v -> viewModel.edit { copy(password = v) } },
                    label = { Text("Password") },
                    singleLine = true,
                    visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Next),
                    trailingIcon = {
                        IconButton(onClick = { showPassword = !showPassword }) {
                            Icon(if (showPassword) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility, "Show password")
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )

                SectionTitle("Sensor")
                OutlinedTextField(
                    value = s.clientId,
                    onValueChange = { v -> viewModel.edit { copy(clientId = v) } },
                    label = { Text("Board's client id") },
                    supportingText = { Text("mqtt.client_id in the board's config.json; topics are esp/<id>/…") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    modifier = Modifier.fillMaxWidth(),
                )
                TextButton(onClick = { showAdvanced = !showAdvanced }) {
                    Icon(if (showAdvanced) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore, null)
                    Spacer(Modifier.width(4.dp))
                    Text("Advanced")
                }
                AnimatedVisibility(showAdvanced, enter = expandVertically() + fadeIn(), exit = shrinkVertically() + fadeOut()) {
                    OutlinedTextField(
                        value = s.stateTopic,
                        onValueChange = { v -> viewModel.edit { copy(stateTopic = v) } },
                        label = { Text("Readings topic") },
                        supportingText = { Text("mqtt.topic_state on the board") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }

        AnimatedVisibility(state.error != null) {
            Row(Modifier.fillMaxWidth().padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.ErrorOutline, null, tint = MaterialTheme.colorScheme.error)
                Spacer(Modifier.width(8.dp))
                Text(state.error.orEmpty(), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
        }

        Spacer(Modifier.height(18.dp))
        Button(
            onClick = connectWithPermission,
            enabled = s.isComplete && !state.connecting,
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) {
            if (state.connecting) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                Spacer(Modifier.width(10.dp))
                Text("Connecting…")
            } else {
                Text("Connect")
            }
        }
        Text(
            "Saved on this phone only.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            textAlign = TextAlign.Center,
        )
        if (s.host.isNotEmpty()) {
            TextButton(onClick = { confirmForget = true }, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Text("Forget these settings")
            }
        }
    }

    if (confirmForget) {
        ConfirmDialog(
            title = "Forget settings?",
            text = "Removes the broker address, login and client id from this phone.",
            confirmLabel = "Forget",
            onConfirm = viewModel::forget,
            onDismiss = { confirmForget = false },
        )
    }
}

private fun hasLocalNetworkPermission(context: Context): Boolean =
    Build.VERSION.SDK_INT < 37 ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_LOCAL_NETWORK) == PackageManager.PERMISSION_GRANTED

/** The app's mark; breathes while connecting. */
@Composable
private fun Logo(busy: Boolean) {
    val pulse by rememberInfiniteTransition(label = "logo")
        .animateFloat(0.9f, 1.1f, infiniteRepeatable(tween(800), RepeatMode.Reverse), label = "pulse")
    Box(Modifier.fillMaxWidth().padding(top = 24.dp, bottom = 8.dp), contentAlignment = Alignment.Center) {
        Icon(
            Icons.Rounded.Air,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(72.dp).scale(if (busy) pulse else 1f).alpha(if (busy) 0.6f + (pulse - 0.9f) * 2 else 1f),
        )
    }
}
