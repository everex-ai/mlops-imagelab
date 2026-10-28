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
    frameNumber: number;
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

function IssueMarkers(props: Props): JSX.Element {
    const {
        startFrame, stopFrame, frameNumber, interactive, onMarkerClick, children,
    } = props;

    const issues = useSelector((state: CombinedState) => state.review.issues);
    const issuesHidden = useSelector((state: CombinedState) => state.review.issuesHidden);
    const issuesResolvedHidden = useSelector((state: CombinedState) => state.review.issuesResolvedHidden);

    const areaRef = useRef<HTMLDivElement>(null);
    const [rail, setRail] = useState<RailGeometry | null>(null);
    const [snappedFrame, setSnappedFrame] = useState<number | null>(null);
    const cursorXRef = useRef<number | null>(null);
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

    const snapAt = useCallback((clientX: number): PlacedIssueMarker | null => {
        const railElement = getRailElement();
        if (!interactive || !rail || !railElement || !markers.length) {
            return null;
        }

        const cursorX = clientX - railElement.getBoundingClientRect().left;
        return findSnappedIssueFrame(markers, cursorX, startFrame, stopFrame, rail.width);
    }, [interactive, rail, markers, startFrame, stopFrame, getRailElement]);

    // markers changed under a still cursor (new/resolved/deleted issue, "T R", "T I"):
    // recompute the snap so a marker that disappeared does not stay highlighted or clickable
    useEffect(() => {
        if (cursorXRef.current === null || draggingRef.current) {
            setSnappedFrame(null);
            return;
        }

        setSnappedFrame(snapAt(cursorXRef.current)?.frame ?? null);
    }, [snapAt]);

    const onMouseMove = useCallback((event: React.MouseEvent): void => {
        cursorXRef.current = event.clientX;
        if (!draggingRef.current) {
            setSnappedFrame(snapAt(event.clientX)?.frame ?? null);
        }
    }, [snapAt]);

    const onMouseLeave = useCallback((): void => {
        cursorXRef.current = null;
        setSnappedFrame(null);
    }, []);

    const onMouseDownCapture = useCallback((event: React.MouseEvent): void => {
        if (!interactive || event.button !== 0) {
            return;
        }

        const snapped = snapAt(event.clientX);
        const onHandle = !!(event.target as HTMLElement).closest('.ant-slider-handle');

        if (snapped && !onHandle) {
            // a marker click replaces the default slider jump
            event.preventDefault();
            event.stopPropagation();
            onMarkerClick(snapped.frame);
            return;
        }

        // the slider handles this press as usual (rail click or handle drag); no highlight while dragging
        draggingRef.current = true;
        setSnappedFrame(null);
        const { clientX: startX, clientY: startY } = event;
        // the current frame marker sits under the handle, so a still click on the handle opens its issues
        const handleOverCurrentMarker = onHandle && snapped?.frame === frameNumber;

        const onMouseUp = (upEvent: MouseEvent): void => {
            window.removeEventListener('mouseup', onMouseUp);
            draggingRef.current = false;
            if (
                handleOverCurrentMarker &&
                Math.abs(upEvent.clientX - startX) < CLICK_TOLERANCE &&
                Math.abs(upEvent.clientY - startY) < CLICK_TOLERANCE
            ) {
                onMarkerClick(frameNumber);
            }

            if (cursorXRef.current !== null) {
                setSnappedFrame(snapAt(cursorXRef.current)?.frame ?? null);
            }
        };
        window.addEventListener('mouseup', onMouseUp);
    }, [interactive, snapAt, onMarkerClick, frameNumber]);

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
