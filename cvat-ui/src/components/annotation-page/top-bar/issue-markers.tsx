// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, {
    useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState,
} from 'react';
import { useSelector } from 'react-redux';

import { CombinedState } from 'reducers';
import {
    filterVisibleIssueFrames, findSnappedIssueFrame, placeIssueMarkers, PlacedIssueMarker, summarizeIssues,
} from 'utils/issue-markers';

interface Props {
    startFrame: number;
    stopFrame: number;
    // false where the slider itself is read-only (single shape workspace): markers are drawn, but not clickable
    interactive: boolean;
    onMarkerClick(frame: number): void;
    children: React.ReactNode;
}

interface RailGeometry {
    left: number;
    top: number;
    width: number;
    height: number;
}

// pointer travel (px) under which a mousedown/mouseup on the slider handle still counts as a click
const CLICK_TOLERANCE = 3;
const LAYER_HEIGHT = 16;
// vertical distance (px) from the rail centre within which the pointer snaps to markers
const SNAP_BAND_HALF_HEIGHT = 10;

interface CursorPoint {
    x: number;
    y: number;
}

function IssueMarkers(props: Props): JSX.Element {
    const {
        startFrame, stopFrame, interactive, onMarkerClick, children,
    } = props;

    const issues = useSelector((state: CombinedState) => state.review.issues);
    const issuesHidden = useSelector((state: CombinedState) => state.review.issuesHidden);
    const issuesResolvedHidden = useSelector((state: CombinedState) => state.review.issuesResolvedHidden);

    const areaRef = useRef<HTMLDivElement>(null);
    const [rail, setRail] = useState<RailGeometry | null>(null);
    const [snappedFrame, setSnappedFrame] = useState<number | null>(null);
    const cursorRef = useRef<CursorPoint | null>(null);
    const draggingRef = useRef(false);

    const getRailElement = useCallback((): HTMLElement | null => (
        areaRef.current?.querySelector('.ant-slider-rail') ?? null
    ), []);

    useLayoutEffect(() => {
        const area = areaRef.current;
        if (!area) {
            return undefined;
        }

        const measure = (): void => {
            const railElement = getRailElement();
            if (!railElement) {
                setRail(null);
                return;
            }

            const areaRect = area.getBoundingClientRect();
            const railRect = railElement.getBoundingClientRect();
            const next = {
                left: Math.round(railRect.left - areaRect.left),
                top: Math.round(railRect.top - areaRect.top),
                width: Math.round(railRect.width),
                height: Math.round(railRect.height),
            };

            setRail((prev) => (
                prev && prev.left === next.left && prev.top === next.top &&
                prev.width === next.width && prev.height === next.height ? prev : next
            ));
        };

        measure();
        const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
        observer?.observe(area);
        window.addEventListener('resize', measure);
        return () => {
            observer?.disconnect();
            window.removeEventListener('resize', measure);
        };
    }, [getRailElement]);

    const summary = useMemo(() => summarizeIssues(issues), [issues]);
    const markers = useMemo((): PlacedIssueMarker[] => {
        if (!rail) {
            return [];
        }

        const visible = filterVisibleIssueFrames(summary.frames, issuesHidden, issuesResolvedHidden);
        return placeIssueMarkers(visible, startFrame, stopFrame, rail.width);
    }, [summary, issuesHidden, issuesResolvedHidden, startFrame, stopFrame, rail]);

    const snapAt = useCallback((point: CursorPoint): PlacedIssueMarker | null => {
        const railElement = getRailElement();
        if (!interactive || !rail || !railElement || !markers.length) {
            return null;
        }

        // only the band around the rail snaps, so chapter marks above the rail and plugin
        // content keep their own clicks
        const railRect = railElement.getBoundingClientRect();
        const railCenterY = railRect.top + railRect.height / 2;
        if (Math.abs(point.y - railCenterY) > SNAP_BAND_HALF_HEIGHT) {
            return null;
        }

        return findSnappedIssueFrame(markers, point.x - railRect.left, startFrame, stopFrame, rail.width);
    }, [interactive, rail, markers, startFrame, stopFrame, getRailElement]);

    // the window mouseup listener outlives the render that registered it, so it reads the latest values
    const snapAtRef = useRef(snapAt);
    snapAtRef.current = snapAt;
    const onMarkerClickRef = useRef(onMarkerClick);
    onMarkerClickRef.current = onMarkerClick;
    const removeMouseUpListenerRef = useRef<(() => void) | null>(null);
    useEffect(() => () => {
        removeMouseUpListenerRef.current?.();
    }, []);

    // markers changed under a still cursor (new/resolved/deleted issue, "T R", "T I"):
    // recompute the snap so a marker that disappeared does not stay highlighted or clickable
    useEffect(() => {
        if (cursorRef.current === null || draggingRef.current) {
            setSnappedFrame(null);
            return;
        }

        setSnappedFrame(snapAt(cursorRef.current)?.frame ?? null);
    }, [snapAt]);

    const onMouseMove = useCallback((event: React.MouseEvent): void => {
        cursorRef.current = { x: event.clientX, y: event.clientY };
        if (!draggingRef.current) {
            setSnappedFrame(snapAt(cursorRef.current)?.frame ?? null);
        }
    }, [snapAt]);

    const onMouseLeave = useCallback((): void => {
        cursorRef.current = null;
        setSnappedFrame(null);
    }, []);

    const onMouseDownCapture = useCallback((event: React.MouseEvent): void => {
        if (!interactive || event.button !== 0) {
            return;
        }

        const snapped = snapAt({ x: event.clientX, y: event.clientY });
        const onHandle = !!(event.target as HTMLElement).closest('.ant-slider-handle');

        if (snapped && !onHandle) {
            // a marker click replaces the default slider jump; the slider would also blur
            // a focused input on its own mousedown, keep that so frame shortcuts keep working
            event.preventDefault();
            event.stopPropagation();
            (window.document.activeElement as HTMLElement | null)?.blur?.();
            onMarkerClick(snapped.frame);
            return;
        }

        // the slider handles this press as usual (rail click or handle drag); no highlight while dragging
        draggingRef.current = true;
        setSnappedFrame(null);
        const { clientX: startX, clientY: startY } = event;
        // markers under the handle (the current frame one and close neighbours) can only be reached
        // through the handle: a still click on it counts as a click on the snapped marker
        const handleClickTarget = onHandle && snapped ? snapped.frame : null;

        removeMouseUpListenerRef.current?.();
        const onMouseUp = (upEvent: MouseEvent): void => {
            removeMouseUpListenerRef.current?.();
            draggingRef.current = false;
            if (
                handleClickTarget !== null &&
                Math.abs(upEvent.clientX - startX) < CLICK_TOLERANCE &&
                Math.abs(upEvent.clientY - startY) < CLICK_TOLERANCE
            ) {
                onMarkerClickRef.current(handleClickTarget);
            }

            if (cursorRef.current !== null) {
                setSnappedFrame(snapAtRef.current(cursorRef.current)?.frame ?? null);
            }
        };
        window.addEventListener('mouseup', onMouseUp);
        removeMouseUpListenerRef.current = () => {
            window.removeEventListener('mouseup', onMouseUp);
            removeMouseUpListenerRef.current = null;
        };
    }, [interactive, snapAt, onMarkerClick]);

    return (
        <div
            ref={areaRef}
            className={`cvat-issue-markers-area ${snappedFrame !== null ? 'cvat-issue-markers-area-snapped' : ''}`}
            onMouseMove={onMouseMove}
            onMouseLeave={onMouseLeave}
            onMouseDownCapture={onMouseDownCapture}
        >
            {children}
            {rail && markers.length > 0 && (
                <div
                    aria-hidden
                    className='cvat-issue-markers'
                    style={{
                        left: rail.left,
                        top: rail.top + Math.round((rail.height - LAYER_HEIGHT) / 2),
                        width: rail.width,
                        height: LAYER_HEIGHT,
                    }}
                >
                    {markers.map((marker) => {
                        const snapped = marker.frame === snappedFrame;
                        const classes = [
                            'cvat-issue-marker',
                            marker.hasUnresolved ? 'cvat-issue-marker-unresolved' : 'cvat-issue-marker-resolved',
                            ...(snapped ? ['cvat-issue-marker-snapped'] : []),
                        ];
                        return (
                            <div
                                key={marker.frame}
                                data-frame={marker.frame}
                                className={classes.join(' ')}
                                // 2px wide at [x - 1, x + 1); 4px when snapped at [x - 2, x + 2) — integer pixels
                                style={{ left: marker.x - (snapped ? 2 : 1) }}
                            />
                        );
                    })}
                </div>
            )}
        </div>
    );
}

export default React.memo(IssueMarkers);
