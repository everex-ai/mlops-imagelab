// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/// <reference types="cypress" />

// INNO-125: reviewer-only shortcut (Z) toggling the workspace between Standard and Review.
// Reviewer status is decided on the client from `user.groups`, so the reviewer is simulated by
// adding `reviewer` to the /api/users/self response.

context('Reviewer Standard/Review workspace toggle shortcut', () => {
    const taskName = 'INNO-125 workspace toggle shortcut';
    const serverFiles = ['images/image_1.jpg'];
    const toggleName = 'Switch Standard/Review';
    const rectangle = {
        points: 'By 2 Points',
        type: 'Shape',
        labelName: 'label 1',
        firstX: 250,
        firstY: 350,
        secondX: 350,
        secondY: 450,
    };
    let taskID = null;
    let jobID = null;

    const task = {
        labels: [{ name: 'label 1', attributes: [], type: 'any' }],
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

    function simulateReviewer(isReviewer) {
        cy.intercept('GET', '/api/users/self*', (req) => {
            req.continue((res) => {
                const groups = (res.body.groups || []).filter((group) => group !== 'reviewer');
                res.body.groups = isReviewer ? [...groups, 'reviewer'] : groups;
            });
        }).as('getSelf');
    }

    function openJob() {
        cy.visit(`/tasks/${taskID}/jobs/${jobID}`);
        cy.get('.cvat-canvas-container').should('exist').and('be.visible');
    }

    function workspaceShouldBe(workspace) {
        cy.get('.cvat-workspace-selector .ant-select-selection-item').should('have.text', workspace);
    }

    function clearCustomShortcuts() {
        cy.window().then((win) => {
            const raw = win.localStorage.getItem('clientSettings');
            if (raw) {
                const settings = JSON.parse(raw);
                delete settings.shortcuts;
                win.localStorage.setItem('clientSettings', JSON.stringify(settings));
            }
        });
    }

    function openShortcutsSettings() {
        cy.openSettings();
        cy.contains('Shortcuts').click();
        cy.get('.cvat-shortcuts-settings-search input').should('be.visible');
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

    after(() => {
        cy.headlessDeleteTask(taskID);
        cy.logout();
    });

    describe('Reviewer', () => {
        beforeEach(() => {
            simulateReviewer(true);
            clearCustomShortcuts();
            openJob();
        });

        it('Z toggles Standard <-> Review, keeps the active object and highlights the selector', () => {
            cy.changeWorkspace('Standard');
            cy.createRectangle(rectangle);
            cy.get('#cvat_canvas_shape_1').trigger('mousemove');
            cy.get('#cvat_canvas_shape_1').trigger('mouseover');
            cy.get('#cvat_canvas_shape_1').should('have.class', 'cvat_canvas_shape_activated');

            cy.get('body').type('z');
            workspaceShouldBe('Review');
            cy.get('.cvat-workspace-selector').should('have.class', 'cvat-workspace-selector-toggled');
            cy.get('.cvat-workspace-selector').should('not.have.class', 'cvat-workspace-selector-toggled');

            cy.get('body').type('z');
            workspaceShouldBe('Standard');
        });

        it('Z from Attribute annotation goes to Review, then back to Standard', () => {
            cy.changeWorkspace('Attribute annotation');
            cy.get('body').type('z');
            workspaceShouldBe('Review');
            cy.get('body').type('z');
            workspaceShouldBe('Standard');
        });

        it('Mouse workspace change does not highlight the selector', () => {
            cy.changeWorkspace('Standard');
            cy.changeWorkspace('Review');
            cy.get('.cvat-workspace-selector').should('not.have.class', 'cvat-workspace-selector-toggled');
        });

        it('Z is ignored while drawing', () => {
            cy.changeWorkspace('Standard');
            cy.interactControlButton('draw-rectangle');
            cy.get('.cvat-draw-rectangle-popover').within(() => {
                cy.contains('button', 'Shape').click();
            });
            cy.get('body').type('z');
            workspaceShouldBe('Standard');
            cy.get('body').type('{esc}');
        });

        it('Dropdown shows the key next to Standard and Review only; closed selector shows plain name', () => {
            cy.changeWorkspace('Standard');
            workspaceShouldBe('Standard');
            cy.get('.cvat-workspace-selector').click();
            cy.get('.cvat-workspace-selector-dropdown').within(() => {
                cy.get('.ant-select-item-option[title="Standard"] .cvat-workspace-selector-shortcut')
                    .should('have.text', 'Z');
                cy.get('.ant-select-item-option[title="Review"] .cvat-workspace-selector-shortcut')
                    .should('have.text', 'Z');
                cy.get('.ant-select-item-option[title="Tag annotation"] .cvat-workspace-selector-shortcut')
                    .should('not.exist');
            });
            cy.get('body').type('{esc}');
        });

        it('F1 lists the shortcut', () => {
            cy.get('.cvat-canvas-container').click();
            cy.realPress(['F1']);
            cy.get('.cvat-shortcuts-modal-window').should('be.visible');
            cy.get('.cvat-shortcuts-modal-window .ant-pagination-options-size-changer').click();
            cy.get('.ant-select-dropdown').not('.ant-select-dropdown-hidden').within(() => {
                cy.contains('100 / page').click();
            });
            cy.get('.cvat-shortcuts-modal-window-table').should('contain.text', toggleName);
            cy.contains('.cvat-shortcuts-modal-window [type="button"]', 'OK').click();
        });

        it('F2 lists the shortcut', () => {
            openShortcutsSettings();
            cy.get('.cvat-shortcuts-settings-search input').type('Switch Standard');
            cy.get('.cvat-shortcuts-settings-item-title').should('have.length', 1).and('have.text', toggleName);
            cy.closeSettings();
        });
    });

    describe('Non-reviewer', () => {
        beforeEach(() => {
            simulateReviewer(false);
            clearCustomShortcuts();
            openJob();
        });

        it('Z does nothing and the key is not shown in the dropdown', () => {
            cy.changeWorkspace('Standard');
            cy.get('body').type('z');
            workspaceShouldBe('Standard');
            cy.get('.cvat-workspace-selector').click();
            cy.get('.cvat-workspace-selector-dropdown .cvat-workspace-selector-shortcut').should('not.exist');
            cy.get('body').type('{esc}');
        });

        it('F2 does not list the shortcut', () => {
            openShortcutsSettings();
            cy.get('.cvat-shortcuts-settings-search input').type('Switch Standard');
            cy.get('.cvat-shortcuts-settings-item-title').should('not.exist');
            cy.closeSettings();
        });
    });
});
