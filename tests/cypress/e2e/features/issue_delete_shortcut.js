// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/// <reference types="cypress" />

// INNO-127: delete the issue of the opened issue dialog with ⌘⌫ (mac) / Ctrl+Del (others)

context('Delete issue shortcut', { scrollBehavior: false }, () => {
    const taskName = 'Issue delete shortcut';
    const serverFiles = ['images/image_1.jpg', 'images/image_2.jpg', 'images/image_3.jpg'];
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

    const issueParams = {
        type: 'rectangle',
        description: 'issue to delete',
        firstX: 300,
        firstY: 200,
        secondX: 400,
        secondY: 300,
    };

    const rectangleParams = {
        points: 'By 2 Points',
        type: 'Shape',
        labelName: 'label 1',
        firstX: 150,
        firstY: 350,
        secondX: 250,
        secondY: 450,
    };

    const MAC = 'mac';
    const WINDOWS = 'windows';

    function stubPlatform(win, platform) {
        const value = platform === MAC ? 'MacIntel' : 'Win32';
        Object.defineProperty(win.navigator, 'platform', { value, configurable: true });
        Object.defineProperty(win.navigator, 'userAgentData', {
            value: { platform: platform === MAC ? 'macOS' : 'Windows' },
            configurable: true,
        });
    }

    function openJob(workspace = 'Review', platform = MAC) {
        cy.visit(`/tasks/${taskID}/jobs/${jobID}`, {
            onBeforeLoad: (win) => stubPlatform(win, platform),
        });
        cy.get('.cvat-canvas-container').should('exist').and('be.visible');
        cy.get('.cvat-spinner').should('not.exist');
        cy.changeWorkspace(workspace);
    }

    function createIssue() {
        cy.createIssueFromControlButton(issueParams);
        cy.get('.cvat-hidden-issue-label').should('have.length', 1);
    }

    function blurActiveElement() {
        cy.document().then((doc) => {
            if (doc.activeElement && doc.activeElement !== doc.body) {
                doc.activeElement.blur();
            }
        });
    }

    function openIssueDialog() {
        cy.get('.cvat-hidden-issue-label').first().click();
        cy.get('.cvat-issue-dialog').should('be.visible');
        // shortcuts are ignored while an input is focused, so make sure the focus is outside the dialog
        blurActiveElement();
        cy.get('.cvat-issue-dialog').should('be.visible');
    }

    // negative assertions ("no confirmation appeared") would otherwise pass before the app reacts to the key
    const SHORTCUT_SETTLE_MS = 300;

    function pressMacShortcut() {
        cy.realPress(['Meta', 'Backspace']);
        cy.wait(SHORTCUT_SETTLE_MS);
    }

    function pressWindowsShortcut() {
        cy.realPress(['Control', 'Delete']);
        cy.wait(SHORTCUT_SETTLE_MS);
    }

    // Two keydowns in the same task, before antd mounts the first confirmation,
    // so the ant-modal check in stopCallback cannot be what prevents the second dialog
    function pressWindowsShortcutTwiceSynchronously() {
        cy.document().then((doc) => {
            for (let i = 0; i < 2; i++) {
                const event = new KeyboardEvent('keydown', {
                    key: 'Delete', code: 'Delete', ctrlKey: true, bubbles: true, cancelable: true,
                });
                Object.defineProperty(event, 'keyCode', { get: () => 46 });
                Object.defineProperty(event, 'which', { get: () => 46 });
                doc.body.dispatchEvent(event);
            }
        });
        cy.wait(SHORTCUT_SETTLE_MS);
    }

    function removeAllIssues() {
        cy.window().then(async (win) => {
            const [job] = await win.cvat.jobs.get({ jobID });
            const issues = await job.issues();
            await Promise.all(issues.map((issue) => issue.delete()));
        });
    }

    function shortcutsTableContains(target) {
        return cy.get('.cvat-shortcuts-modal-window-table').then(($table) => $table.text().includes(target));
    }

    function findInShortcutsTable(target) {
        shortcutsTableContains(target).then((found) => {
            if (found) {
                cy.contains('.cvat-shortcuts-modal-window-table tr', target)
                    .should('be.visible')
                    .and('contain', 'ctrl+del')
                    .and('contain', 'command+backspace');
                return;
            }
            cy.get('.cvat-shortcuts-modal-window-table .ant-pagination-next').then(($next) => {
                if ($next.hasClass('ant-pagination-disabled')) {
                    throw new Error(`"${target}" is not listed in the shortcuts table`);
                }
                cy.wrap($next).click();
                findInShortcutsTable(target);
            });
        });
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
        cy.intercept('DELETE', '/api/issues/**').as('deleteIssue');
    });

    afterEach(() => {
        removeAllIssues();
    });

    after(() => {
        if (taskID) {
            cy.headlessDeleteTask(taskID);
        }
        cy.logout();
    });

    describe('Confirmation dialog', () => {
        it('Remove button opens the shared confirmation: Delete is focused, dangerous, with a warning', () => {
            openJob();
            createIssue();
            openIssueDialog();
            cy.get('.cvat-issue-dialog').should('have.css', 'outline-style', 'solid');
            cy.get('.cvat-issue-dialog-remove-button').click();
            cy.get('.cvat-modal-confirm-remove-issue').should('have.length', 1).within(() => {
                cy.contains('삭제한 이슈는 되돌릴 수 없습니다.').should('be.visible');
                cy.contains('button', 'Delete')
                    .should('have.class', 'ant-btn-dangerous')
                    .and('have.focus');
            });
            cy.realPress('Escape');
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            cy.get('.cvat-issue-dialog').should('be.visible');
            cy.get('@deleteIssue.all').should('have.length', 0);
        });
    });

    describe('Shortcut', () => {
        it('AE1: ⌘⌫ then Enter deletes the opened issue (review workspace)', () => {
            openJob('Review');
            createIssue();
            openIssueDialog();
            pressMacShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('be.visible');
            cy.realPress('Enter');
            cy.wait('@deleteIssue').its('response.statusCode').should('equal', 204);
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            cy.get('.cvat-issue-dialog').should('not.exist');
            cy.get('.cvat-hidden-issue-label').should('not.exist');
            cy.get('.cvat_canvas_issue_region').should('not.exist');
        });

        it('AE1: ⌘⌫ then Enter deletes the opened issue (standard workspace)', () => {
            openJob('Review');
            createIssue();
            cy.changeWorkspace('Standard');
            openIssueDialog();
            pressMacShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('be.visible');
            cy.realPress('Enter');
            cy.wait('@deleteIssue').its('response.statusCode').should('equal', 204);
            cy.get('.cvat-hidden-issue-label').should('not.exist');
            cy.get('.cvat-objects-sidebar-issues-list-header').should('contain', 'Items: 0');
        });

        it('AE6: Ctrl+Del then Esc only closes the confirmation', () => {
            openJob('Review', WINDOWS);
            createIssue();
            openIssueDialog();
            pressWindowsShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('be.visible');
            cy.realPress('Escape');
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            cy.get('.cvat-issue-dialog').should('be.visible');
            cy.get('@deleteIssue.all').should('have.length', 0);
        });

        it('Pressing the shortcut again while the confirmation is opened does not open another one', () => {
            openJob();
            createIssue();
            openIssueDialog();
            pressWindowsShortcutTwiceSynchronously();
            cy.get('.cvat-modal-confirm-remove-issue').should('have.length', 1);
            pressMacShortcut();
            pressWindowsShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('have.length', 1);
            cy.realPress('Escape');
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            // the guard is released after closing, so the shortcut works again
            pressMacShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('have.length', 1);
            cy.realPress('Escape');
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
        });

        it('AE3: the shortcut is ignored while the comment input is focused', () => {
            openJob();
            createIssue();
            openIssueDialog();
            cy.get('.cvat-issue-dialog-input input').type('keypoint position');
            cy.get('.cvat-issue-dialog-input input').should('have.focus');
            pressMacShortcut();
            pressWindowsShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            cy.get('@deleteIssue.all').should('have.length', 0);
        });

        it('AE4: nothing happens when no issue dialog is opened, an active object is kept', () => {
            openJob();
            createIssue();
            cy.changeWorkspace('Standard');
            cy.createRectangle(rectangleParams);
            cy.get('.cvat_canvas_shape').should('have.length', 1);
            cy.get('.cvat_canvas_shape').first().trigger('mousemove');
            cy.get('.cvat_canvas_shape').first().trigger('mouseover');
            cy.get('.cvat_canvas_shape_activated').should('exist');
            cy.get('.cvat-issue-dialog').should('not.exist');
            pressMacShortcut();
            pressWindowsShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            cy.get('.cvat_canvas_shape').should('have.length', 1);
            cy.get('.cvat-hidden-issue-label').should('have.length', 1);
        });

        it('AE5: nothing happens after moving to another frame with the dialog opened', () => {
            openJob();
            createIssue();
            openIssueDialog();
            cy.goCheckFrameNumber(1);
            cy.get('.cvat-issue-dialog').should('not.exist');
            blurActiveElement();
            pressMacShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            cy.get('.ant-notification-notice-error').should('not.exist');
            cy.goCheckFrameNumber(0);
            cy.get('.cvat-issue-dialog').should('be.visible');
        });

        it('Nothing happens when issues are hidden', () => {
            openJob('Standard');
            cy.changeWorkspace('Review');
            createIssue();
            cy.changeWorkspace('Standard');
            openIssueDialog();
            cy.contains('.cvat-objects-sidebar .ant-tabs-tab', 'Issues').click();
            cy.get('.cvat-objects-sidebar-issues-list-header').should('be.visible');
            blurActiveElement();
            cy.realPress('t');
            cy.realPress('i');
            cy.get('.cvat-issue-dialog').should('not.exist');
            pressMacShortcut();
            cy.get('.cvat-modal-confirm-remove-issue').should('not.exist');
            cy.realPress('t');
            cy.realPress('i');
            cy.get('.cvat-issue-dialog').should('be.visible');
        });

        it('AE2: a rejected deletion shows the error notification and keeps the issue', () => {
            openJob();
            createIssue();
            // only the first request is rejected, so that the cleanup in afterEach can remove the issue
            cy.intercept(
                { method: 'DELETE', url: '/api/issues/**', times: 1 },
                { statusCode: 403, body: { detail: 'forbidden' } },
            ).as('deleteIssueForbidden');
            openIssueDialog();
            pressMacShortcut();
            cy.realPress('Enter');
            cy.wait('@deleteIssueForbidden');
            cy.contains('Could not remove issue from the server').should('be.visible');
            openJob();
            cy.get('.cvat-hidden-issue-label').should('have.length', 1);
        });
    });

    describe('Shortcut hint and F1', () => {
        it('Shows ⌘⌫ next to Remove on mac', () => {
            openJob('Review', MAC);
            createIssue();
            openIssueDialog();
            cy.get('.cvat-issue-dialog-remove-shortcut').should('have.text', '⌘⌫');
        });

        it('Shows Ctrl+Del next to Remove on other platforms', () => {
            openJob('Review', WINDOWS);
            createIssue();
            openIssueDialog();
            cy.get('.cvat-issue-dialog-remove-shortcut').should('have.text', 'Ctrl+Del');
        });

        it('"Delete issue" is listed in F1 without an opened issue dialog', () => {
            openJob();
            cy.get('.cvat-issue-dialog').should('not.exist');
            cy.realPress('F1');
            cy.get('.cvat-shortcuts-modal-window').should('be.visible');
            findInShortcutsTable('Delete issue');
            cy.realPress('F1');
            cy.get('.cvat-shortcuts-modal-window').should('not.be.visible');
        });
    });
});
