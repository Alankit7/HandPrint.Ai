/// go_router configuration with a bottom-nav shell and a push route for results.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/convert/convert_screen.dart';
import '../../features/history/history_screen.dart';
import '../../features/profiles/profiles_screen.dart';
import '../../features/result/result_screen.dart';
import '../../features/settings/settings_screen.dart';

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/profiles',
    routes: [
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) {
          return _ScaffoldWithNav(navigationShell: navigationShell);
        },
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/profiles',
              name: 'profiles',
              builder: (context, state) => const ProfilesScreen(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/convert',
              name: 'convert',
              builder: (context, state) => const ConvertScreen(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/history',
              name: 'history',
              builder: (context, state) => const HistoryScreen(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/settings',
              name: 'settings',
              builder: (context, state) => const SettingsScreen(),
            ),
          ]),
        ],
      ),
      GoRoute(
        path: '/result/:jobId',
        name: 'result',
        builder: (context, state) =>
            ResultScreen(jobId: state.pathParameters['jobId']!),
      ),
    ],
  );
});

class _ScaffoldWithNav extends StatelessWidget {
  const _ScaffoldWithNav({required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: navigationShell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: navigationShell.currentIndex,
        onDestinationSelected: (index) {
          navigationShell.goBranch(
            index,
            initialLocation: index == navigationShell.currentIndex,
          );
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: 'Profiles',
          ),
          NavigationDestination(
            icon: Icon(Icons.auto_fix_normal_outlined),
            selectedIcon: Icon(Icons.auto_fix_high),
            label: 'Convert',
          ),
          NavigationDestination(
            icon: Icon(Icons.history),
            selectedIcon: Icon(Icons.history_outlined),
            label: 'History',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}
