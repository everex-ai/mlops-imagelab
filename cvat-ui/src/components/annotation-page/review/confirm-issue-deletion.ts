// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import Modal from 'antd/lib/modal';
import { useDispatch } from 'react-redux';

import { deleteIssueAsync } from 'actions/review-actions';

type AppDispatch = ReturnType<typeof useDispatch>;

// Modal.confirm mounts asynchronously, so the `ant-modal` check in Mousetrap's stopCallback
// cannot suppress a second shortcut press that arrives before the first dialog is in the DOM.
// This flag closes that gap; it is released once the dialog has fully closed.
let confirmationOpened = false;

/**
 * Single delete-issue confirmation shared by the Remove button and the DELETE_ISSUE shortcut.
 * Delete is focused (Enter deletes, Esc cancels) and styled as a dangerous action.
 */
export function confirmIssueDeletion(id: number, collapse: () => void, dispatch: AppDispatch): void {
    if (confirmationOpened) {
        return;
    }

    confirmationOpened = true;
    Modal.confirm({
        title: `The issue #${id} will be deleted.`,
        content: '삭제한 이슈는 되돌릴 수 없습니다.',
        className: 'cvat-modal-confirm-remove-issue',
        onOk: () => {
            collapse();
            dispatch(deleteIssueAsync(id));
        },
        afterClose: () => {
            confirmationOpened = false;
        },
        okButtonProps: {
            type: 'primary',
            danger: true,
        },
        autoFocusButton: 'ok',
        okText: 'Delete',
    });
}

const MAC_KEY_SYMBOLS: Record<string, string> = {
    command: '⌘',
    meta: '⌘',
    shift: '⇧',
    ctrl: '⌃',
    alt: '⌥',
    option: '⌥',
    backspace: '⌫',
    del: '⌦',
    delete: '⌦',
};

const OTHER_KEY_NAMES: Record<string, string> = {
    command: 'Meta',
    meta: 'Meta',
    ctrl: 'Ctrl',
    shift: 'Shift',
    alt: 'Alt',
    del: 'Del',
    delete: 'Del',
    backspace: 'Backspace',
};

function formatKey(key: string, isMac: boolean): string {
    const lowered = key.toLowerCase();
    const known = (isMac ? MAC_KEY_SYMBOLS : OTHER_KEY_NAMES)[lowered];
    if (known) {
        return known;
    }
    return lowered.length === 1 ? lowered.toUpperCase() : lowered.charAt(0).toUpperCase() + lowered.slice(1);
}

/**
 * Picks the configured sequence that fits the OS (mac: command/meta, others: ctrl), falling back
 * to the first one, and renders it as `⌘⌫` on mac or `Ctrl+Del` elsewhere.
 * Returns null when no sequence is configured, so the hint can be hidden.
 */
export function formatIssueDeleteShortcutHint(sequences: string[] | undefined, isMac: boolean): string | null {
    const candidates = (sequences ?? []).filter((sequence) => !!sequence.trim());
    if (!candidates.length) {
        return null;
    }

    const preferred = candidates.find((sequence) => {
        const keys = sequence.toLowerCase().split(/[+\s]+/);
        return isMac ? keys.includes('command') || keys.includes('meta') : keys.includes('ctrl');
    }) ?? candidates[0];

    // a sequence may consist of several steps separated by spaces ("t i"), each step is a combination
    return preferred.trim().split(/\s+/).map((step) => {
        const keys = step.split('+').map((key) => formatKey(key, isMac));
        return isMac ? keys.join('') : keys.join('+');
    }).join(' ');
}
