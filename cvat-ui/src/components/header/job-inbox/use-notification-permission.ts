// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { useCallback, useEffect, useState } from 'react';

import {
    autoRequestAllowed,
    BrowserNotificationPermission,
    browserNotificationPermission,
    rememberAutoRequest,
    requestBrowserNotificationPermission,
} from './browser-notifications';

interface NotificationPermissionState {
    permission: BrowserNotificationPermission;
    refresh(): void;
    request(): Promise<void>;
}

/**
 * OS notification permission for the header bell. Asks once on the first user gesture
 * anywhere in the app (the bell is mounted only for signed-in users), and exposes the
 * current state so the dropdown can explain why OS notifications are missing.
 */
export function useNotificationPermission(): NotificationPermissionState {
    const [permission, setPermission] = useState(browserNotificationPermission);

    const refresh = useCallback((): void => {
        setPermission(browserNotificationPermission());
    }, []);

    const request = useCallback(async (): Promise<void> => {
        setPermission(await requestBrowserNotificationPermission());
    }, []);

    useEffect(() => {
        if (browserNotificationPermission() !== 'default' || !autoRequestAllowed()) {
            return undefined;
        }

        const onGesture = (event: Event): void => {
            // Escape and modifier-only presses do not count as user activation, so the
            // browser would silently drop the request: wait for the next gesture.
            if (event instanceof KeyboardEvent && (
                event.key === 'Escape' || ['Control', 'Shift', 'Alt', 'Meta'].includes(event.key)
            )) {
                return;
            }
            window.removeEventListener('click', onGesture, true);
            window.removeEventListener('keydown', onGesture, true);
            rememberAutoRequest();
            request();
        };

        window.addEventListener('click', onGesture, true);
        window.addEventListener('keydown', onGesture, true);
        return () => {
            window.removeEventListener('click', onGesture, true);
            window.removeEventListener('keydown', onGesture, true);
        };
    }, [request]);

    return { permission, refresh, request };
}
