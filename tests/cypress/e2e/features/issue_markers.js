// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/// <reference types="cypress" />

// INNO-124: issue frame markers on the player slider + "unresolved/total" badge on the Issues tab
context('Issue markers on the player slider and the Issues tab badge', () => {
    const caseId = 'inno_124';
    const labelName = `Label ${caseId}`;
    const taskName = `Task ${caseId}`;
    const attrName = `Attr for ${labelName}`;
    const textDefaultValue = 'Some default value for type Text';
    const imagesCount = 10;
    const imageFileName = `image_${caseId}`;
    const width = 800;
    const height = 800;
    const posX = 10;
    const posY = 10;
    const color = 'gray';
    const archiveName = `${imageFileName}.zip`;
    const archivePath = `cypress/fixtures/${archiveName}`;
    const imagesFolder = `cypress/fixtures/${imageFileName}`;

    const issueA = {
        type: 'point', description: 'issue A', firstX: 300, firstY: 300,
    };
    const issueB = {
        type: 'point', description: 'issue B', firstX: 300, firstY: 300,
    };
    const issueC = {
        type: 'point', description: 'issue C', firstX: 500, firstY: 500,
    };
    const issueLabel = (description) => `.cvat-hidden-issue-label:contains("${description}")`;

    function checkBadge(text, unresolved) {
        if (text === null) {
            cy.get('.cvat-objects-sidebar-issues-badge').should('not.exist');
            return;
        }

        cy.get('.cvat-objects-sidebar-issues-badge')
            .should('have.text', text)
            .and(unresolved ? 'have.class' : 'not.have.class', 'cvat-objects-sidebar-issues-badge-unresolved');
    }

    function checkMarkers(expected) {
        // expected: { [frame]: 'unresolved' | 'resolved' }
        const frames = Object.keys(expected);
        if (!frames.length) {
            cy.get('.cvat-issue-marker').should('not.exist');
            return;
        }

        cy.get('.cvat-issue-marker').should('have.length', frames.length);
        for (const frame of frames) {
            cy.get(`.cvat-issue-marker[data-frame="${frame}"]`)
                .should('have.class', `cvat-issue-marker-${expected[frame]}`);
        }
    }

    function openSidebarTab(title) {
        cy.get('.cvat-objects-sidebar-tabs').within(() => {
            cy.contains('.ant-tabs-tab', title).click();
            cy.contains('.ant-tabs-tab', title).should('have.class', 'ant-tabs-tab-active');
        });
    }

    function clickMarker(frame) {
        cy.get(`.cvat-issue-marker[data-frame="${frame}"]`).then(($marker) => {
            const markerRect = $marker[0].getBoundingClientRect();
            cy.get('.cvat-issue-markers-area').then(($area) => {
                const areaRect = $area[0].getBoundingClientRect();
                const x = markerRect.left + markerRect.width / 2 - areaRect.left;
                const y = markerRect.top + markerRect.height / 2 - areaRect.top;
                cy.get('.cvat-issue-markers-area').trigger('mousemove', x, y);
                cy.get(`.cvat-issue-marker[data-frame="${frame}"]`).should('have.class', 'cvat-issue-marker-snapped');
                cy.get('.cvat-issue-markers-area').trigger('mousedown', x, y, { button: 0 });
                cy.get('.cvat-issue-markers-area').trigger('mouseup', x, y, { button: 0 });
            });
        });
    }

    before(() => {
        cy.imageGenerator(imagesFolder, imageFileName, width, height, color, posX, posY, labelName, imagesCount);
        cy.createZipArchive(imagesFolder, archivePath);
        cy.visit('/auth/login');
        cy.login();
        cy.createAnnotationTask(taskName, labelName, attrName, textDefaultValue, archiveName);
        cy.openTaskJob(taskName);
        cy.changeWorkspace('Review');
    });

    after(() => {
        cy.logout();
        cy.task('getAuthHeaders').then((authHeaders) => {
            cy.deleteTasks(authHeaders, [taskName]);
        });
    });

    describe('Markers and badge follow the job issues', { scrollBehavior: false }, () => {
        it('No issues: no markers, no badge', () => {
            checkMarkers({});
            checkBadge(null);
        });

        it('New issues appear immediately as red markers and in the badge', () => {
            cy.createIssueFromControlButton(issueA);
            checkMarkers({ 0: 'unresolved' });
            checkBadge('1/1', true);

            cy.goCheckFrameNumber(5);
            cy.createIssueFromControlButton(issueB);
            cy.createIssueFromControlButton(issueC);
            // one marker per frame, even with two issues on frame 5
            checkMarkers({ 0: 'unresolved', 5: 'unresolved' });
            checkBadge('3/3', true);
        });

        it('Resolve and reopen update the marker colour and the badge (AE1, AE2)', () => {
            cy.resolveIssue(issueLabel(issueB.description), 'Resolved');
            checkMarkers({ 0: 'unresolved', 5: 'unresolved' });
            checkBadge('2/3', true);

            cy.resolveIssue(issueLabel(issueC.description), 'Resolved');
            checkMarkers({ 0: 'unresolved', 5: 'resolved' });
            checkBadge('1/3', true);

            cy.reopenIssue(issueLabel(issueC.description));
            checkMarkers({ 0: 'unresolved', 5: 'unresolved' });
            checkBadge('2/3', true);

            cy.resolveIssue(issueLabel(issueC.description), 'Resolved');
            checkMarkers({ 0: 'unresolved', 5: 'resolved' });
            checkBadge('1/3', true);
        });

        it('"T R" hides grey markers only, "T I" hides all markers; the badge stays (AE4, AE7)', () => {
            openSidebarTab('Issues');
            cy.get('.cvat-issues-sidebar-hidden-resolved-status').click();
            checkMarkers({ 0: 'unresolved' });
            checkBadge('1/3', true);

            cy.get('.cvat-issues-sidebar-shown-issues').click();
            checkMarkers({});
            checkBadge('1/3', true);

            // showing issues again restores the markers according to the "T R" state
            cy.get('.cvat-issues-sidebar-hidden-issues').click();
            checkMarkers({ 0: 'unresolved' });

            cy.get('.cvat-issues-sidebar-hidden-resolved-status').click();
            checkMarkers({ 0: 'unresolved', 5: 'resolved' });
        });

        it('Marker click moves to the frame and opens the Issues tab (AE6)', () => {
            openSidebarTab('Objects');
            cy.checkFrameNum(5);
            clickMarker(0);
            cy.checkFrameNum(0);
            cy.get('.cvat-objects-sidebar-tabs').within(() => {
                cy.contains('.ant-tabs-tab', 'Issues').should('have.class', 'ant-tabs-tab-active');
            });
            cy.get('.cvat-objects-sidebar-issues-list-header').should('contain.text', 'Items: 1');
        });

        it('Removing issues removes markers and updates the badge (AE3)', () => {
            cy.removeIssue(issueLabel(issueA.description));
            checkMarkers({ 5: 'resolved' });
            checkBadge('0/2', false);

            cy.goCheckFrameNumber(5);
            cy.removeIssue(issueLabel(issueB.description));
            cy.removeIssue(issueLabel(issueC.description));
            checkMarkers({});
            checkBadge(null);
        });
    });
});
