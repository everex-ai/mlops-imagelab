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

import * as SVG from 'svg.js';
import { DrawnState } from './shared';

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
    redrawSkeletonEdges: (clientID: number) => void;
    collectShapePoints: (objState: any, shape: SVG.Shape) => number[];
    collectSkeletonBbox: (group: SVG.G) => number[] | undefined;
}

// INNO-156 KTD5: every member — the primary included — is placed at
// "start + constrainGroupDelta(raw delta)". It is the identity here on purpose:
// at integration INNO-158 (separate branch, not merged yet) replaces the body
// with its clampGroupDelta (imageBounds.ts on that branch) to stop the whole
// group at the image border, using the member start positions recorded here.
export function constrainGroupDelta(delta: Point): Point {
    return delta;
}

interface CircleStart {
    circle: SVG.Circle;
    cx: number;
    cy: number;
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
    private primaryShape: SVG.Shape;
    private primaryIsElement: boolean;
    // top-level clientID of the primary (the skeleton for a keypoint)
    private primaryTopID: number;
    // whether the primary keypoint's skeleton translates as a whole
    private primaryParentWhole: boolean;
    private primaryStart: Point;
    private members: Member[];

    private constructor(
        host: GroupDragHost,
        primaryState: any,
        primaryShape: SVG.Shape,
        primaryTopID: number,
        primaryParentWhole: boolean,
        members: Member[],
    ) {
        this.host = host;
        this.primaryState = primaryState;
        this.primaryShape = primaryShape;
        this.primaryIsElement = Number.isInteger(primaryState.parentID);
        this.primaryTopID = primaryTopID;
        this.primaryParentWhole = primaryParentWhole;
        this.members = members;
        this.primaryStart = this.primaryPosition();
    }

    // Returns a session when the drag should move a group, null for the
    // regular single-object drag.
    public static begin(
        host: GroupDragHost,
        primaryState: any,
        primaryShape: SVG.Shape,
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
                if (circle) circles.push({ circle, cx: circle.cx(), cy: circle.cy() });
            }

            const rect = whole ? findWrappingRect(group) : null;
            const rectStart = rect ? {
                xtl: +rect.attr('data-xtl'),
                ytl: +rect.attr('data-ytl'),
                xbr: +rect.attr('data-xbr'),
                ybr: +rect.attr('data-ybr'),
            } : null;

            if (isPrimaryTop) primaryParentWhole = whole;
            if (circles.length || rect) movesSomethingElse = true;
            members.push({
                kind: 'skeleton', clientID: topID, whole, rect, rectStart, circles,
            });
        }

        if (!movesSomethingElse) return null;
        return new GroupDragSession(host, primaryState, primaryShape, primaryTopID, primaryParentWhole, members);
    }

    private primaryPosition(): Point {
        if (this.primaryIsElement) {
            const circle = this.primaryShape as SVG.Circle;
            return { x: circle.cx(), y: circle.cy() };
        }
        if (this.primaryState.shapeType === 'skeleton') {
            const rect = findWrappingRect(this.primaryShape as SVG.G);
            if (rect) return { x: +rect.attr('data-xtl'), y: +rect.attr('data-ytl') };
        }
        const { cx, cy } = this.primaryShape.bbox();
        return { x: cx, y: cy };
    }

    public move(): void {
        const current = this.primaryPosition();
        const raw = { x: current.x - this.primaryStart.x, y: current.y - this.primaryStart.y };
        const delta = constrainGroupDelta(raw);
        this.placePrimary(delta.x - raw.x, delta.y - raw.y);
        this.placeMembers(delta.x, delta.y);
    }

    // Shifts the primary by the correction constrainGroupDelta applied on top
    // of where svg.draggable put it. A no-op while the function is the identity.
    private placePrimary(cdx: number, cdy: number): void {
        if (!cdx && !cdy) return;
        const { host } = this;
        if (this.primaryIsElement) {
            const circle = this.primaryShape as SVG.Circle;
            circle.center(circle.cx() + cdx, circle.cy() + cdy);
            return;
        }

        if (this.primaryState.shapeType === 'skeleton') {
            const group = this.primaryShape as SVG.G;
            const rect = findWrappingRect(group);
            if (rect) {
                const xtl = +rect.attr('data-xtl') + cdx;
                const ytl = +rect.attr('data-ytl') + cdy;
                rect.move(xtl, ytl);
                rect.attr({
                    'data-xtl': xtl,
                    'data-ytl': ytl,
                    'data-xbr': +rect.attr('data-xbr') + cdx,
                    'data-ybr': +rect.attr('data-ybr') + cdy,
                });
            }
            for (const child of group.children()) {
                if (child.type !== 'circle') continue;
                const element = this.primaryState.elements
                    .find((el: any) => el.clientID === +child.attr('data-client-id'));
                if (element?.lock) continue;
                (child as SVG.Circle).center((child as SVG.Circle).cx() + cdx, (child as SVG.Circle).cy() + cdy);
            }
            host.redrawSkeletonEdges(this.primaryTopID);
            return;
        }

        const drawnState = host.drawnStates[this.primaryState.clientID];
        if (drawnState) {
            const current = host.captureDragStart(this.primaryShape, drawnState);
            host.moveShapeVisually(this.primaryShape, drawnState, current, cdx, cdy);
        }
    }

    private placeMembers(dx: number, dy: number): void {
        const { host } = this;
        for (const member of this.members) {
            if (member.kind === 'shape') {
                const shape = host.svgShapes[member.clientID];
                const drawnState = host.drawnStates[member.clientID];
                if (shape && drawnState) host.moveShapeVisually(shape, drawnState, member.start, dx, dy);
                continue;
            }

            for (const { circle, cx, cy } of member.circles) {
                circle.center(cx + dx, cy + dy);
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
        this.placeMembers(0, 0);
    }

    public get topLevelIDs(): number[] {
        const ids = this.members.map((member) => member.clientID);
        return ids.includes(this.primaryTopID) ? ids : [this.primaryTopID, ...ids];
    }
}
