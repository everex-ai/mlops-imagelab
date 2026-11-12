// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/// <reference types="cypress" />

// INNO-157: Shift+drag box selection can start inside objects (skeleton bbox, shape bodies);
// a Shift press is a click or a box by one 5 screen px rule.

context('Box selection started inside objects', { scrollBehavior: false }, () => {
    const taskName = 'INNO-157 box select inside bbox';
    const serverFiles = ['images/image_1.jpg'];
    let taskID = null;
    let jobID = null;

    const svg = '<line x1="30" y1="20" x2="30" y2="90" stroke="black" data-type="edge" ' +
        'data-node-from="1" stroke-width="0.5" data-node-to="2"></line>' +
        '<circle r="1.5" stroke="black" fill="#b3b3b3" cx="30" cy="20" stroke-width="0.1" ' +
        'data-type="element node" data-element-id="1" data-node-id="1" data-label-name="head"></circle>' +
        '<circle r="1.5" stroke="black" fill="#b3b3b3" cx="30" cy="90" stroke-width="0.1" ' +
        'data-type="element node" data-element-id="2" data-node-id="2" data-label-name="ankle"></circle>';

    const task = {
        labels: [{
            name: 'person',
            attributes: [],
            type: 'skeleton',
            svg,
            sublabels: ['head', 'ankle'].map((name) => ({ name, attributes: [], type: 'points' })),
        }, { name: 'box', attributes: [], type: 'rectangle' }],
        name: taskName,
        project_id: null,
        source_storage: { location: 'local' },
        target_storage: { location: 'local' },
    };
    const storage = {
        server_files: serverFiles,
        image_quality: 70,
        use_zip_chunks: true,
        use_cache: true,
        sorting_method: 'lexicographical',
    };

    function createObjects() {
        cy.window().then(async ($win) => {
            const [job] = await $win.cvat.jobs.get({ jobID });
            await job.annotations.clear({ reload: true });
            const skeletonLabel = job.labels.find((label) => label.name === 'person');
            const boxLabel = job.labels.find((label) => label.name === 'box');
            const common = {
                frame: 0,
                occluded: false,
                outside: false,
                source: 'manual',
                attributes: [],
                rotation: 0,
                group: 0,
                z_order: 0,
            };
            const sublabel = (name) => skeletonLabel.structure.sublabels.find((_label) => _label.name === name);
            await job.annotations.import({
                shapes: [{
                    ...common,
                    type: 'skeleton',
                    label_id: skeletonLabel.id,
                    points: [],
                    bbox: [100, 50, 300, 450],
                    elements: [['head', 200, 100], ['ankle', 200, 400]].map(([name, x, y]) => ({
                        ...common, type: 'points', label_id: sublabel(name).id, points: [x, y],
                    })),
                }, {
                    ...common,
                    type: 'rectangle',
                    label_id: boxLabel.id,
                    points: [450, 100, 650, 300],
                }],
                tracks: [],
                tags: [],
            });
            await job.annotations.save();
        });
    }

    function openJob() {
        cy.visit(`/tasks/${taskID}/jobs/${jobID}`);
        cy.get('.cvat-canvas-container').should('exist').and('be.visible');
        cy.get('.cvat-spinner').should('not.exist');
        cy.get('.cvat_canvas_shape_skeleton').should('have.length', 1);
    }

    function centerOf(element) {
        const rect = element.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    }

    // Shift press on `selector` at its center, moves by the given screen offsets, release at the last one
    function shiftGesture(selector, moves) {
        cy.get(selector).then(($element) => {
            const start = centerOf($element[0]);
            const at = ([dx, dy]) => ({ clientX: start.x + dx, clientY: start.y + dy });
            const last = moves.length ? moves[moves.length - 1] : [0, 0];
            cy.get(selector).trigger('mousedown', {
                button: 0, which: 1, shiftKey: true, ...at([0, 0]),
            });
            moves.forEach((move) => {
                cy.get(selector).trigger('mousemove', { buttons: 1, shiftKey: true, ...at(move) });
            });
            cy.get(selector).trigger('mouseup', { button: 0, shiftKey: true, ...at(last) });
        });
    }

    function geometryOf(selector) {
        return cy.get(selector).then(($element) => ['x', 'y', 'width', 'height']
            .map((attr) => $element.attr(attr)).join(','));
    }

    before(() => {
        cy.visit('/auth/login');
        cy.login();
        cy.get('.cvat-tasks-page').should('exist').and('be.visible');
        cy.headlessCreateTask(task, storage).then((response) => {
            taskID = response.taskID;
            [jobID] = response.jobIDs;
        });
    });

    beforeEach(() => {
        createObjects();
        openJob();
    });

    after(() => {
        cy.headlessDeleteTask(taskID);
        cy.logout();
    });

    it('Shift+drag inside a rectangle body draws a box and does not move it (AE7)', () => {
        const rectangle = 'rect.cvat_canvas_shape';
        geometryOf(rectangle).then((before) => {
            cy.get(rectangle).trigger('mousemove');
            cy.get(rectangle).trigger('mouseover');
            cy.get(rectangle).should('have.class', 'cvat_canvas_shape_activated');
            cy.get(rectangle).then(($rect) => {
                const start = centerOf($rect[0]);
                cy.get(rectangle).trigger('mousedown', {
                    button: 0, which: 1, shiftKey: true, clientX: start.x, clientY: start.y,
                });
                cy.get(rectangle).trigger('mousemove', {
                    buttons: 1, shiftKey: true, clientX: start.x + 40, clientY: start.y + 40,
                });
                cy.get('.cvat_canvas_multiselect_box').should('exist');
                cy.get(rectangle).trigger('mouseup', {
                    button: 0, shiftKey: true, clientX: start.x + 40, clientY: start.y + 40,
                });
            });
            cy.get('.cvat_canvas_multiselect_box').should('not.exist');
            geometryOf(rectangle).should('equal', before);
            cy.get(rectangle).should('have.class', 'cvat_canvas_shape_multiselected');
        });
    });

    it('Shift+click inside an inactive skeleton bbox toggles the person (AE5)', () => {
        const wrappingRect = '.cvat_canvas_skeleton_wrapping_rect';
        shiftGesture(wrappingRect, [[3, 0]]);
        cy.get('.cvat_canvas_shape_skeleton').should('have.class', 'cvat_canvas_shape_multiselected');
        cy.get('.cvat_canvas_multiselect_box').should('not.exist');
        shiftGesture(wrappingRect, []);
        cy.get('.cvat_canvas_shape_skeleton').should('not.have.class', 'cvat_canvas_shape_multiselected');
    });

    it('A gesture that went 10px away and came back is a box, not a click (R12)', () => {
        const wrappingRect = '.cvat_canvas_skeleton_wrapping_rect';
        shiftGesture(wrappingRect, [[10, 0], [2, 0]]);
        cy.get('.cvat_canvas_multiselect_box').should('not.exist');
        cy.get('.cvat_canvas_shape_skeleton').should('not.have.class', 'cvat_canvas_shape_multiselected');
    });

    it('Shift+drag inside an active skeleton bbox does not move the person (AE1)', () => {
        const wrappingRect = '.cvat_canvas_skeleton_wrapping_rect';
        cy.get(wrappingRect).trigger('mousemove');
        cy.get('.cvat_canvas_shape_skeleton').should('have.class', 'cvat_canvas_shape_activated');
        geometryOf(wrappingRect).then((before) => {
            shiftGesture(wrappingRect, [[20, 20], [60, 60]]);
            geometryOf(wrappingRect).should('equal', before);
        });
    });

    it('Esc during a box cancels it and keeps the selection (AE9)', () => {
        const wrappingRect = '.cvat_canvas_skeleton_wrapping_rect';
        cy.get(wrappingRect).then(($rect) => {
            const start = centerOf($rect[0]);
            cy.get(wrappingRect).trigger('mousedown', {
                button: 0, which: 1, shiftKey: true, clientX: start.x, clientY: start.y,
            });
            cy.get(wrappingRect).trigger('mousemove', {
                buttons: 1, shiftKey: true, clientX: start.x + 30, clientY: start.y + 30,
            });
        });
        cy.get('.cvat_canvas_multiselect_box').should('exist');
        cy.get('body').trigger('keydown', { code: 'Escape', key: 'Escape' });
        cy.get('.cvat_canvas_multiselect_box').should('not.exist');
        cy.get('.cvat_canvas_keypoint_selected').should('not.exist');
    });
});
