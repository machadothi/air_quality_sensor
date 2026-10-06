package com.machadothi.airmonitor.ui.navigation

import androidx.compose.animation.AnimatedContentTransitionScope.SlideDirection
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.machadothi.airmonitor.ui.screen.connect.ConnectScreen
import com.machadothi.airmonitor.ui.screen.monitor.MonitorScreen

private const val TRANSITION_MS = 380

@Composable
fun AppNavHost(modifier: Modifier = Modifier) {
    val navController = rememberNavController()
    NavHost(
        navController = navController,
        startDestination = NavRoutes.Connect(autoConnect = true),
        modifier = modifier,
        enterTransition = { slideIntoContainer(SlideDirection.Start, tween(TRANSITION_MS)) + fadeIn(tween(TRANSITION_MS)) },
        exitTransition = { slideOutOfContainer(SlideDirection.Start, tween(TRANSITION_MS)) + fadeOut(tween(TRANSITION_MS)) },
        popEnterTransition = { slideIntoContainer(SlideDirection.End, tween(TRANSITION_MS)) + fadeIn(tween(TRANSITION_MS)) },
        popExitTransition = { slideOutOfContainer(SlideDirection.End, tween(TRANSITION_MS)) + fadeOut(tween(TRANSITION_MS)) },
    ) {
        composable<NavRoutes.Connect> {
            ConnectScreen(onConnected = {
                navController.navigate(NavRoutes.Monitor) { popUpTo(0) { inclusive = true } }
            })
        }
        composable<NavRoutes.Monitor> {
            MonitorScreen(onEditConnection = {
                navController.navigate(NavRoutes.Connect(autoConnect = false)) { popUpTo(0) { inclusive = true } }
            })
        }
    }
}
