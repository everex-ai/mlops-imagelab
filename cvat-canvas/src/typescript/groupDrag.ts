// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// INNO-156: one drag that moves every selected object and keypoint together.
//
// A session is started from canvasView.draggable() when the dragged element
// (the "primary": a shape body, a skeleton bbox or a keypoint circle) is part
// of the current selection and the selection has other movable members. The
// primary is moved by svg.draggable as usual; the session moves every other
// member by the same delta and, on dragend, produces one edit per object so
// cvat-ui can save them as ONE undo entry (annotations.batchSave).
//
// INNO-158: the delta is limited once per tick by clampGroupDelta over the
// drag-start extents of the primary and of every member, so the whole group
// stops together (keeping its spacing) as soon as any member reaches the
// image border. `outside` keypoints do not limit the group; each is clamped
// on its own (clampMovedPoint) instead.

import * as SVG from 'svg.js';
import { DrawnState } from './shared';
import {
    Bounds, Delta, Extent, clampGroupDelta, clampMovedPoint, skeletonMemberExtent,
} from './imageBounds';

export interface Point {
    x: number;
    y: number;
}

// Start state of a shape moved by a drag (canvasView.captureDragStart); every
// tick the shape is placed at "start + delta" (INNO-158)
export interface DragStartSnapshot {
    x: number;
    y: number;
    points?: number[][];
    cuboidPoints?: { x: number; y: number }[];
    xtl?: number;
    ytl?: number;
    circles?: Map<SVG.Element, { cx: number; cy: number; outside: boolean }>;
}

export interface GroupDragEdit {
    state: any;
    points: number[];
    bbox?: number[];
}

// the narrow part of canvasView the session needs
export interface GroupDragHost {
    svgShapes: Record<number, SVG.Shape>;
    drawnStates: Record<number, DrawnState>;
    objects: () => any[];
    selectedClientIDs: () => number[];
    selectedElementClientIDs: () => number[];
    moveShapeVisually: (
        shape: SVG.Shape, state: DrawnState, start: DragStartSnapshot, dx: number, dy: number,
    ) => void;
    captureDragStart: (shape: SVG.Shape, state: DrawnState) => DragStartSnapshot;
    // the drag-start extent of a non-skeleton member, null when that shape
    // type is not clamped (rotated rectangles, polygons, masks, ...)
    collectClampExtent: (state: any, shape: SVG.Shape, includeLockedKeypoints: boolean) => Extent | null;
    redrawSkeletonEdges: (clientID: number) => void;
    collectShapePoints: (objState: any, shape: SVG.Shape) => number[];
    collectSkeletonBbox: (group: SVG.G) => number[] | undefined;
}

interface CircleStart {
    circle: SVG.Circle;
    cx: number;
    cy: number;
    // outside keypoints are clamped one by one, not part of the group limit
    outside: boolean;
}

interface SkeletonMember {
    kind: 'skeleton';
    clientID: number;
    // whole: the bbox rect and every keypoint (hidden/outside too) translate,
    // the edit carries the bbox. Otherwise only the listed keypoints move and
    // cvat-core soft-snaps the bbox on save.
    whole: boolean;
    rect: SVG.Rect | null;
    rectStart: { xtl: number; ytl: number; xbr: number; ybr: number } | null;
    circles: CircleStart[];
}

interface ShapeMember {
    kind: 'shape';
    clientID: number;
    start: DragStartSnapshot;
}

type Member = SkeletonMember | ShapeMember;

function findWrappingRect(group: SVG.G): SVG.Rect | null {
    return (group.children().find((child: SVG.Element) => child.type === 'rect') as SVG.Rect) ?? null;
}

function circleOf(group: SVG.G, elementClientID: number): SVG.Circle | null {
    return (group.children().find(
        (child: SVG.Element) => child.type === 'circle' && +child.attr('data-client-id') === elementClientID,
    ) as SVG.Circle) ?? null;
}

export class GroupDragSession {
    private host: GroupDragHost;
    private primaryState: any;
    private primaryIsElement: boolean;
    // top-level clientID of the primary (the skeleton for a keypoint)
    private primaryTopID: number;
    // whether the primary keypoint's skeleton translates as a whole
    private primaryParentWhole: boolean;
    private members: Member[];
    // drag-start extents of every member (the primary's own extent is passed
    // in by canvasView, which also clamps single drags with it)
    private extents: Extent[];

    private constructor(
        host: GroupDragHost,
        primaryState: any,
        primaryTopID: number,
        primaryParentWhole: boolean,
        members: Member[],
        extents: Extent[],
    ) {
        this.host = host;
        this.primaryState = primaryState;
        this.primaryIsElement = Number.isInteger(primaryState.parentID);
        this.primaryTopID = primaryTopID;
        this.primaryParentWhole = primaryParentWhole;
        this.members = members;
        this.extents = extents;
    }

    // Returns a session when the drag should move a group, null for the
    // regular single-object drag.
    public static begin(
        host: GroupDragHost,
        primaryState: any,
        shiftKey: boolean,
    ): GroupDragSession | null {
        // Shift+drag on a selected keypoint moves only that keypoint
        // (user decision 2026-11-12)
        if (shiftKey) return null;

        const selectedIDs = host.selectedClientIDs();
        const selectedElementIDs = host.selectedElementClientIDs();
        const isElement = Number.isInteger(primaryState.parentID);

        // the group moves only when the drag starts on an explicit member:
        // a box / ⌘-Ctrl-click selected keypoint, or a selected object's body
        // (user decision 2026-11-12)
        if (isElement ? !selectedElementIDs.includes(primaryState.clientID) :
            !selectedIDs.includes(primaryState.clientID)) {
            return null;
        }

        const objects = host.objects();
        const parentOf = new Map<number, any>();
        for (const obj of objects) {
            if (obj.shapeType === 'skeleton') {
                for (const element of obj.elements) parentOf.set(element.clientID, obj);
            }
        }

        const primaryTopID = isElement ? primaryState.parentID : primaryState.clientID;
        const topIDs: number[] = [...selectedIDs];
        for (const elementID of selectedElementIDs) {
            const parent = parentOf.get(elementID);
            if (parent && !topIDs.includes(parent.clientID)) topIDs.push(parent.clientID);
        }
        if (!topIDs.includes(primaryTopID)) topIDs.push(primaryTopID);

        const members: Member[] = [];
        const extents: Extent[] = [];
        let primaryParentWhole = false;
        let movesSomethingElse = false;

        for (const topID of topIDs) {
            const obj = objects.find((_obj: any) => _obj.clientID === topID);
            const shape = host.svgShapes[topID];
            const isPrimaryTop = topID === primaryTopID;
            if (!obj || !shape || obj.hidden || obj.outside) continue;
            // locked and pinned objects never move with the group (R16)
            if (!isPrimaryTop && (obj.lock || obj.pinned)) continue;

            if (obj.shapeType !== 'skeleton') {
                if (isPrimaryTop) continue;
                const drawnState = host.drawnStates[topID];
                if (!drawnState) continue;
                members.push({ kind: 'shape', clientID: topID, start: host.captureDragStart(shape, drawnState) });
                const extent = host.collectClampExtent(obj, shape, true);
                if (extent) extents.push(extent);
                movesSomethingElse = true;
                continue;
            }

            // the skeleton's own bbox is being dragged: svg.draggable and the
            // regular dragmove handler already translate it (locked keypoints
            // stay in place, exactly like a single skeleton drag)
            if (isPrimaryTop && !isElement) continue;

            const group = shape as SVG.G;
            const personSelected = selectedIDs.includes(topID);
            const visible = obj.elements.filter((el: any) => !el.hidden && !el.outside);
            const hasLocked = obj.elements.some((el: any) => el.lock);
            const allVisibleSelected = visible.length > 0 &&
                visible.every((el: any) => selectedElementIDs.includes(el.clientID));
            const whole = (personSelected || allVisibleSelected) && !hasLocked && !obj.pinned;

            let moving: any[];
            if (whole) {
                moving = obj.elements;
            } else {
                moving = visible.filter((el: any) => !el.lock &&
                    (personSelected || selectedElementIDs.includes(el.clientID)));
            }

            const circles: CircleStart[] = [];
            for (const element of moving) {
                if (isElement && element.clientID === primaryState.clientID) continue;
                const circle = circleOf(group, element.clientID);
                if (circle) {
                    circles.push({
                        circle, cx: circle.cx(), cy: circle.cy(), outside: !!element.outside,
                    });
                }
            }

            const rect = whole ? findWrappingRect(group) : null;
            const rectStart = rect ? {
                xtl: +rect.attr('data-xtl'),
                ytl: +rect.attr('data-ytl'),
                xbr: +rect.attr('data-xbr'),
                ybr: +rect.attr('data-ybr'),
            } : null;

            const extent = skeletonMemberExtent(rectStart, circles);
            if (extent) extents.push(extent);

            if (isPrimaryTop) primaryParentWhole = whole;
            if (circles.length || rect) movesSomethingElse = true;
            members.push({
                kind: 'skeleton', clientID: topID, whole, rect, rectStart, circles,
            });
        }

        if (!movesSomethingElse) return null;
        return new GroupDragSession(
            host, primaryState, primaryTopID, primaryParentWhole, members, extents,
        );
    }

    // INNO-156 KTD5 / INNO-158: the delta every member (and the primary)
    // moves by this tick: the raw delta clamped so that every drag-start
    // extent, the primary's and the members', stays inside the image (or
    // does not go further out than it started).
    public constrain(primaryExtents: Extent[], dx: number, dy: number, bounds: Bounds | null): Delta {
        if (!bounds) return { dx, dy };
        return clampGroupDelta([...primaryExtents, ...this.extents], dx, dy, bounds);
    }

    // Places every member at "start + (dx, dy)"; the primary is placed by
    // svg.draggable (canvasView's constraint function) with the same delta.
    public move(dx: number, dy: number, bounds: Bounds | null): void {
        this.placeMembers(dx, dy, bounds);
    }

    private placeMembers(dx: number, dy: number, bounds: Bounds | null): void {
        const { host } = this;
        for (const member of this.members) {
            if (member.kind === 'shape') {
                const shape = host.svgShapes[member.clientID];
                const drawnState = host.drawnStates[member.clientID];
                if (shape && drawnState) host.moveShapeVisually(shape, drawnState, member.start, dx, dy);
                continue;
            }

            for (const {
                circle, cx, cy, outside,
            } of member.circles) {
                if (outside && bounds) {
                    circle.center(...clampMovedPoint(cx, cy, cx + dx, cy + dy, bounds));
                } else {
                    circle.center(cx + dx, cy + dy);
                }
            }
            if (member.rect && member.rectStart) {
                const {
                    xtl, ytl, xbr, ybr,
                } = member.rectStart;
                member.rect.move(xtl + dx, ytl + dy);
                member.rect.attr({
                    'data-xtl': xtl + dx,
                    'data-ytl': ytl + dy,
                    'data-xbr': xbr + dx,
                    'data-ybr': ybr + dy,
                });
            }
            host.redrawSkeletonEdges(member.clientID);
        }
    }

    // One edit per object. Whole-moved skeletons carry the translated bbox;
    // keypoint moves carry points only so cvat-core soft-snaps the bbox.
    public commit(): GroupDragEdit[] {
        const { host } = this;
        const objects = host.objects();
        const edits: GroupDragEdit[] = [];
        const editFor = (objState: any, whole: boolean): GroupDragEdit | null => {
            const shape = host.svgShapes[objState.clientID];
            if (!shape) return null;
            const edit: GroupDragEdit = {
                state: objState,
                points: host.collectShapePoints(objState, shape),
            };
            if (objState.shapeType === 'skeleton' && whole) {
                const bbox = host.collectSkeletonBbox(shape as SVG.G);
                if (bbox) edit.bbox = bbox;
            }
            return edit;
        };

        if (!this.primaryIsElement) {
            const edit = editFor(this.primaryState, true);
            if (edit) edits.push(edit);
        }

        for (const member of this.members) {
            const objState = objects.find((obj: any) => obj.clientID === member.clientID);
            if (!objState) continue;
            const isPrimaryParent = member.clientID === this.primaryTopID;
            // a keypoint-moved skeleton with nothing moved needs no save
            if (member.kind === 'skeleton' && !member.whole && !member.circles.length && !isPrimaryParent) {
                continue;
            }
            let whole = true;
            if (member.kind === 'skeleton') {
                whole = isPrimaryParent ? this.primaryParentWhole : member.whole;
            }
            const edit = editFor(objState, whole);
            if (edit) edits.push(edit);
        }

        return edits;
    }

    // Puts every member (not the primary, svg.draggable/abort handles it)
    // back to where the drag started.
    public abort(): void {
        this.placeMembers(0, 0, null);
    }

    public get topLevelIDs(): number[] {
        const ids = this.members.map((member) => member.clientID);
        return ids.includes(this.primaryTopID) ? ids : [this.primaryTopID, ...ids];
    }
}
