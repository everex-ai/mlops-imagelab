// Copyright (C) 2019-2022 Intel Corporation
// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { HistoryActions } from './enums';

const MAX_HISTORY_LENGTH = 32;

interface ActionItem {
    action: HistoryActions;
    undo: Function;
    redo: Function;
    clientIDs: number[];
    frame: number;
}

export default class AnnotationHistory {
    private frozen: boolean;
    private _undo: ActionItem[];
    private _redo: ActionItem[];
    // INNO-156: while a batch is open, do() buffers items here instead of pushing
    // them, so several object saves (a group drag) become one undo/redo entry.
    // Independent from `frozen`, which skeleton save() toggles internally.
    private batchBuffer: ActionItem[] | null;

    constructor() {
        this.frozen = false;
        this.batchBuffer = null;
        this.clear();
    }

    public startBatch(): void {
        this.batchBuffer = [];
    }

    public commitBatch(): void {
        const buffer = this.batchBuffer;
        this.batchBuffer = null;
        if (!buffer || !buffer.length) return;

        if (buffer.length === 1) {
            this.push(buffer[0]);
            return;
        }

        const clientIDs = Array.from(new Set(buffer.flatMap((item) => item.clientIDs)));
        this.push({
            action: buffer[0].action,
            frame: buffer[0].frame,
            clientIDs,
            undo: async () => {
                for (let i = buffer.length - 1; i >= 0; i--) {
                    await buffer[i].undo();
                }
            },
            redo: async () => {
                for (const item of buffer) {
                    await item.redo();
                }
            },
        });
    }

    public freeze(frozen: boolean): void {
        this.frozen = frozen;
    }

    public get(): { undo: [HistoryActions, number][], redo: [HistoryActions, number][] } {
        return {
            undo: this._undo.map((undo) => [undo.action, undo.frame]),
            redo: this._redo.map((redo) => [redo.action, redo.frame]),
        };
    }

    public do(action: HistoryActions, undo: Function, redo: Function, clientIDs: number[], frame: number): void {
        if (this.frozen) return;
        const actionItem = {
            clientIDs,
            action,
            undo,
            redo,
            frame,
        };

        if (this.batchBuffer) {
            this.batchBuffer.push(actionItem);
            return;
        }

        this.push(actionItem);
    }

    private push(actionItem: ActionItem): void {
        this._undo = this._undo.slice(-MAX_HISTORY_LENGTH + 1);
        this._undo.push(actionItem);
        this._redo = [];
    }

    public async undo(count: number): Promise<number[]> {
        const affectedObjects = [];
        for (let i = 0; i < count; i++) {
            const action = this._undo.pop();
            if (action) {
                await action.undo();
                this._redo.push(action);
                affectedObjects.push(...action.clientIDs);
            } else {
                break;
            }
        }

        return affectedObjects;
    }

    public async redo(count: number): Promise<number[]> {
        const affectedObjects = [];
        for (let i = 0; i < count; i++) {
            const action = this._redo.pop();
            if (action) {
                await action.redo();
                this._undo.push(action);
                affectedObjects.push(...action.clientIDs);
            } else {
                break;
            }
        }

        return affectedObjects;
    }

    public clear(): void {
        this._undo = [];
        this._redo = [];
    }
}
