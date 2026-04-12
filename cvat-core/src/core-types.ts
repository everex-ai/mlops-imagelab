// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import {
    RQStatus,
} from './enums';

export interface UpdateStatusData {
    status: RQStatus;
    progress: number;
    message: string;
}

export type PaginatedResource<T> = T[] & {
    count: number;
    next?: string;
};
