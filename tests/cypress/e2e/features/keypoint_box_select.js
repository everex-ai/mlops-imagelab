// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/// <reference types="cypress" />

// INNO-156: the Shift+drag box selects skeleton keypoints, Ctrl/⌘+click toggles one,
// dragging a selected keypoint moves the whole selection with one undo entry,
// copy/delete expand to the keypoint owners.

context('Keypoint box selection', { scrollBehavior: false }, () => {
    const taskName = 'INNO-156 keypoint box select';
    const serverFiles = ['images/image_1.jpg'];
    let taskID = null;
    let jobID = null;

    const svg = '<line x1="30" y1="20" x2="30" y2="60" stroke="black" data-type="edge" ' +
        'data-node-from="1" stroke-width="0.5" data-node-to="2"></line>' +
        '<line x1="30" y1="60" x2="30" y2="90" stroke="black" data-type="edge" ' +
        'data-node-from="2" stroke-width="0.5" data-node-to="3"></line>' +
        '<circle r="1.5" stroke="black" fill="#b3b3b3" cx="30" cy="20" stroke-width="0.1" ' +
        'data-type="element node" data-element-id="1" data-node-id="1" data-label-name="head"></circle>' +
        '<circle r="1.5" stroke="black" fill="#b3b3b3" cx="30" cy="60" stroke-width="0.1" ' +
        'data-type="element node" data-element-id="2" data-node-id="2" data-label-name="hip"></circle>' +
        '<circle r="1.5" stroke="black" fill="#b3b3b3" cx="30" cy="90" stroke-width="0.1" ' +
        'data-type="element node" data-element-id="3" data-node-id="3" data-label-name="ankle"></circle>';

    const task = {
        labels: [{
            name: 'person',
            attributes: [],
            type: 'skeleton',
            svg,
            sublabels: ['head', 'hip', 'ankle'].map((name) => ({ name, attributes: [], type: 'points' })),
        }],
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

    // three upright people side by side: head / hip / ankle
    const PEOPLE_X = [150, 300, 450];
    const KEYPOINT_Y = { head: 100, hip: 250, ankle: 400 };

    function createPeople() {
        cy.window().then(async ($win) => {
            const [job] = await $win.cvat.jobs.get({ jobID });
            // start every test from an empty job: clear({ reload: true }) only reloads from the
            // server, the objects of the previous test have to be removed and saved
            await job.annotations.clear({ reload: true });
            await job.annotations.clear();
            await job.annotations.save();
            const [label] = job.labels;
            const sublabel = (name) => label.structure.sublabels.find((_label) => _label.name === name);
            const shapes = PEOPLE_X.map((x) => ({
                frame: 0,
                type: 'skeleton',
                label_id: label.id,
                points: [],
                // a bbox with a margin around the keypoints, so no keypoint sits under a bbox handle
                bbox: [x - 60, KEYPOINT_Y.head - 40, x + 60, KEYPOINT_Y.ankle + 40],
                occluded: false,
                outside: false,
                source: 'manual',
                attributes: [],
                rotation: 0,
                group: 0,
                z_order: 0,
                elements: Object.entries(KEYPOINT_Y).map(([name, y]) => ({
                    frame: 0,
                    type: 'points',
                    label_id: sublabel(name).id,
                    points: [x, y],
                    occluded: false,
                    outside: false,
                    source: 'manual',
                    attributes: [],
                    rotation: 0,
                    group: 0,
                    z_order: 0,
                })),
            }));
            await job.annotations.import({ shapes, tracks: [], tags: [] });
            await job.annotations.save();
        });
    }

    function openJob() {
        cy.visit(`/tasks/${taskID}/jobs/${jobID}`, {
            onBeforeLoad: (win) => {
                // Linux CI: Ctrl is the toggle key
                Object.defineProperty(win.navigator, 'platform', { value: 'Linux x86_64', configurable: true });
                Object.defineProperty(win.navigator, 'userAgentData', {
                    value: { platform: 'Linux' }, configurable: true,
                });
            },
        });
        cy.get('.cvat-canvas-container').should('exist').and('be.visible');
        cy.get('.cvat-spinner').should('not.exist');
        cy.get('.cvat_canvas_shape_skeleton').should('have.length', PEOPLE_X.length);
    }

    // keypoint circles of one sublabel, left to right
    function keypoints(name) {
        return cy.get('.cvat_canvas_shape_skeleton circle').then(($circles) => {
            const nodeID = { head: '1', hip: '2', ankle: '3' }[name];
            const filtered = $circles.toArray()
                .filter((circle) => circle.getAttribute('data-node-id') === nodeID)
                .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);
            return cy.wrap(filtered);
        });
    }

    function centerOf(element) {
        const rect = element.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    }

    // Shift+drag box between two client points
    function boxSelect(from, to) {
        cy.get('#cvat_canvas_content').then(($container) => {
            const origin = $container[0].getBoundingClientRect();
            const rel = (point) => [point.x - origin.x, point.y - origin.y];
            cy.get('#cvat_canvas_content').trigger('mousedown', ...rel(from), { button: 0, shiftKey: true });
            // buttons: 1 - the left button is still held (a box gesture ends on a move without it)
            cy.get('#cvat_canvas_content').trigger('mousemove', ...rel(to), { buttons: 1, shiftKey: true });
            cy.get('#cvat_canvas_content').trigger('mouseup', ...rel(to), { button: 0, shiftKey: true });
        });
    }

    function selectAllAnkles() {
        keypoints('ankle').then(($ankles) => {
            const first = centerOf($ankles[0]);
            const last = centerOf($ankles[$ankles.length - 1]);
            boxSelect({ x: first.x - 30, y: first.y - 20 }, { x: last.x + 30, y: last.y + 20 });
        });
        cy.get('.cvat_canvas_keypoint_selected').should('have.length', PEOPLE_X.length);
    }

    function dragElement($element, dx, dy) {
        const start = centerOf($element[0]);
        cy.wrap($element).trigger('mouseover');
        // wait for the hover activation, the keypoint becomes draggable
        cy.get('.cvat_canvas_shape_activated').should('exist');
        const at = (x, y) => ({ clientX: x, clientY: y });
        cy.wrap($element).trigger('mousedown', { button: 0, which: 1, ...at(start.x, start.y) });
        // once the drag runs, the moving keypoint may pass under other elements (e.g. a bbox handle);
        // svg.draggable listens on the window, so the hit target of the moves does not matter
        cy.wrap($element).trigger('mousemove', { buttons: 1, force: true, ...at(start.x + dx / 2, start.y + dy / 2) });
        cy.wrap($element).trigger('mousemove', { buttons: 1, force: true, ...at(start.x + dx, start.y + dy) });
        cy.wrap($element).trigger('mouseup', { button: 0, force: true, ...at(start.x + dx, start.y + dy) });
    }

    function ankleYs() {
        return keypoints('ankle').then(($ankles) => $ankles.toArray().map((circle) => +circle.getAttribute('cy')));
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
        createPeople();
        openJob();
    });

    after(() => {
        cy.headlessDeleteTask(taskID);
        cy.logout();
    });

    it('A box over the ankles selects only the ankle keypoints (AE1)', () => {
        selectAllAnkles();
        cy.get('.cvat_canvas_shape_multiselected').should('not.exist');
        keypoints('head').each(($head) => cy.wrap($head).should('not.have.class', 'cvat_canvas_keypoint_selected'));

        // Esc during a box keeps the selection (AE10)
        keypoints('head').then(($heads) => {
            const from = centerOf($heads[0]);
            cy.get('#cvat_canvas_content').then(($container) => {
                const origin = $container[0].getBoundingClientRect();
                const [x, y] = [from.x - origin.x, from.y - origin.y];
                cy.get('#cvat_canvas_content').trigger('mousedown', x - 20, y - 20, { button: 0, shiftKey: true });
                cy.get('#cvat_canvas_content').trigger('mousemove', x + 20, y + 20, { buttons: 1, shiftKey: true });
            });
            cy.get('.cvat_canvas_multiselect_box').should('exist');
            cy.get('body').trigger('keydown', { code: 'Escape', key: 'Escape' });
            cy.get('.cvat_canvas_multiselect_box').should('not.exist');
        });
        cy.get('.cvat_canvas_keypoint_selected').should('have.length', PEOPLE_X.length);
    });

    it('Ctrl+click toggles a single keypoint', () => {
        selectAllAnkles();
        keypoints('ankle').then(($ankles) => {
            cy.wrap($ankles[0]).click({ ctrlKey: true });
        });
        cy.get('.cvat_canvas_keypoint_selected').should('have.length', PEOPLE_X.length - 1);
        keypoints('head').then(($heads) => {
            cy.wrap($heads[1]).click({ ctrlKey: true });
        });
        cy.get('.cvat_canvas_keypoint_selected').should('have.length', PEOPLE_X.length);
    });

    it('Dragging a selected keypoint moves the whole selection, one undo restores it (AE2)', () => {
        selectAllAnkles();
        ankleYs().then((before) => {
            keypoints('ankle').then(($ankles) => dragElement($ankles.eq(1), 0, 40));
            cy.get('.cvat-spinner').should('not.exist');
            ankleYs().should((after) => {
                after.forEach((y, idx) => expect(y).to.be.greaterThan(before[idx] + 5));
            });

            cy.get('.cvat-annotation-header-undo-button').click();
            ankleYs().should((after) => {
                after.forEach((y, idx) => expect(y).to.be.closeTo(before[idx], 0.5));
            });
        });
    });

    it('Delete removes the owners of the selected keypoints only (AE6)', () => {
        keypoints('ankle').then(($ankles) => {
            const first = centerOf($ankles[0]);
            const second = centerOf($ankles[1]);
            boxSelect({ x: first.x - 30, y: first.y - 20 }, { x: second.x + 30, y: second.y + 20 });
        });
        cy.get('.cvat_canvas_keypoint_selected').should('have.length', 2);
        cy.get('body').type('{del}');
        cy.get('.cvat_canvas_shape_skeleton').should('have.length', 1);
        cy.get('.cvat-annotation-header-undo-button').click();
        cy.get('.cvat_canvas_shape_skeleton').should('have.length', PEOPLE_X.length);
    });
});
