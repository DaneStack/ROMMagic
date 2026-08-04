document.addEventListener('DOMContentLoaded', () => {
    // Hamburger menu toggle
    const hamburgerToggle = document.getElementById('hamburger-toggle');
    const mainNav = document.getElementById('main-nav');

    if (hamburgerToggle && mainNav) {
        hamburgerToggle.addEventListener('click', () => {
            const isOpen = mainNav.classList.toggle('nav-open');
            hamburgerToggle.classList.toggle('active', isOpen);
            hamburgerToggle.setAttribute('aria-expanded', isOpen);
        });

        // Close menu when a nav link is clicked
        mainNav.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                mainNav.classList.remove('nav-open');
                hamburgerToggle.classList.remove('active');
                hamburgerToggle.setAttribute('aria-expanded', 'false');
            });
        });
    }

    // Confirm deletions
    const deleteForms = document.querySelectorAll('form.delete-form');
    deleteForms.forEach(form => {
        form.addEventListener('submit', (e) => {
            if (!confirm('Are you sure you want to delete this item? This action cannot be undone.')) {
                e.preventDefault();
            }
        });
    });

    // File upload display name (multi-file)
    const fileInput = document.getElementById('rom-file-input');
    const fileNameDisplay = document.getElementById('file-name-display');

    if (fileInput && fileNameDisplay) {
        fileInput.addEventListener('change', (e) => {
            const count = e.target.files.length;
            if (count === 0) {
                fileNameDisplay.textContent = '';
            } else if (count === 1) {
                fileNameDisplay.textContent = `Selected: ${e.target.files[0].name}`;
            } else {
                const names = Array.from(e.target.files).map(f => f.name);
                fileNameDisplay.innerHTML = `<strong>Selected ${count} files:</strong><br>` + names.join('<br>');
            }
        });
    }

    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setupAlertDismissal(alert);
    });

    // Helper for dismissing alerts
    function setupAlertDismissal(alert) {
        setTimeout(() => {
            alert.style.opacity = '0';
            alert.style.transition = 'opacity 0.5s ease-out';
            setTimeout(() => {
                alert.remove();
            }, 500);
        }, 5000);
    }

    // Helper to dynamically show flash messages
    function showFlashMessage(message, category) {
        const flashMessagesContainer = document.querySelector('.flash-messages');
        if (!flashMessagesContainer) return;
        
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert ${category}`;
        alertDiv.textContent = message;
        
        flashMessagesContainer.appendChild(alertDiv);
        setupAlertDismissal(alertDiv);
    }

    // ROM Upload Form Interceptor for multi-file progress bar
    const uploadForm = document.getElementById('rom-upload-form');
    if (uploadForm) {
        uploadForm.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const fileInput = document.getElementById('rom-file-input');
            const platformSelect = document.getElementById('platform_id');
            const progressContainer = document.getElementById('progress-container');
            const progressBar = document.getElementById('progress-bar');
            const statusText = document.getElementById('upload-status-text');
            const submitBtn = document.getElementById('upload-submit-btn');
            const formButtons = document.getElementById('form-buttons');
            const summaryPanel = document.getElementById('upload-summary');
            const summaryContent = document.getElementById('upload-summary-content');
            const uploadAnotherBtn = document.getElementById('upload-another-btn');
            
            if (!fileInput || !platformSelect) return;
            
            const files = Array.from(fileInput.files);
            if (files.length === 0) {
                showFlashMessage('Please select at least one file to upload.', 'error');
                return;
            }
            
            let uploadQueue = files;
            let initialSkipped = [];
            
            // Client-side extension validation per file
            const selectedOption = platformSelect.options[platformSelect.selectedIndex];
            const allowedExtensionsStr = selectedOption.getAttribute('data-extensions') || '';
            
            if (allowedExtensionsStr.trim() !== '') {
                const allowedList = allowedExtensionsStr.split(',').map(item => item.trim().toLowerCase());
                const invalidFiles = files.filter(f => {
                    const ext = f.name.split('.').pop().toLowerCase();
                    return !allowedList.includes(ext);
                });
                if (invalidFiles.length === files.length) {
                    showFlashMessage(`None of the selected files have an allowed extension. Allowed: ${allowedExtensionsStr}`, 'error');
                    return;
                }
                if (invalidFiles.length > 0) {
                    const names = invalidFiles.map(f => f.name).join(', ');
                    if (!confirm(`${invalidFiles.length} file(s) have invalid extensions and will be skipped: ${names}\n\nContinue uploading the remaining files?`)) {
                        return;
                    }
                    uploadQueue = files.filter(f => !invalidFiles.includes(f));
                    initialSkipped = invalidFiles.map(f => ({
                        filename: f.name,
                        reason: `Extension not allowed. Allowed: ${allowedExtensionsStr}`
                    }));
                }
            }
            
            // Disable buttons and inputs to prevent duplicate submission
            submitBtn.disabled = true;
            submitBtn.classList.add('btn-outline');
            
            // Show and reset progress bar
            progressContainer.classList.remove('hidden');
            progressBar.style.width = '0%';
            progressBar.textContent = '0%';
            statusText.textContent = `Uploading ${uploadQueue.length} file${uploadQueue.length > 1 ? 's' : ''}...`;
            
            const CHUNK_SIZE = 25 * 1024 * 1024; // 25MB chunks
            const MAX_CONCURRENT = 4;
            const totalSize = uploadQueue.reduce((acc, file) => acc + file.size, 0);

            const uploadSummary = {
                total: files.length,
                uploaded: 0,
                uploaded_files: [],
                skipped: initialSkipped,
                failed: []
            };

            const baseUrl = uploadForm.action ? uploadForm.action.replace(/\/upload_multiple\/?$/, '/upload_chunk') : '/upload_chunk';

            const fileStates = uploadQueue.map((file, fileIndex) => ({
                file: file,
                fileIndex: fileIndex,
                uploadId: Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15),
                totalChunks: Math.ceil(file.size / CHUNK_SIZE) || 1,
                chunksDispatched: 0,
                chunksCompleted: 0,
                failed: false,
                failedReported: false,
                failReason: '',
                chunkLoaded: {}
            }));
            
            let activeUploads = 0;

            function getNextTask() {
                for (let i = 0; i < fileStates.length; i++) {
                    const state = fileStates[i];
                    if (state.failed) continue;
                    
                    if (state.chunksDispatched < state.totalChunks) {
                        // Guarantee the last chunk is sent sequentially after all previous chunks are COMPLETED
                        if (state.chunksDispatched === state.totalChunks - 1) {
                            if (state.chunksCompleted < state.totalChunks - 1) {
                                continue;
                            }
                        }
                        
                        const chunkIndex = state.chunksDispatched;
                        state.chunksDispatched++;
                        
                        return {
                            file: state.file,
                            fileIndex: state.fileIndex,
                            chunkIndex: chunkIndex,
                            totalChunks: state.totalChunks,
                            start: chunkIndex * CHUNK_SIZE,
                            end: Math.min((chunkIndex + 1) * CHUNK_SIZE, state.file.size)
                        };
                    }
                }
                return null;
            }

            function processQueue() {
                const allDone = fileStates.every(s => s.failed || s.chunksCompleted === s.totalChunks);
                if (allDone && activeUploads === 0) {
                    renderUploadSummary(uploadSummary, summaryContent, summaryPanel, formButtons, progressContainer);
                    return;
                }

                while (activeUploads < MAX_CONCURRENT) {
                    const task = getNextTask();
                    if (!task) break; 
                    
                    activeUploads++;
                    uploadChunkTask(task);
                }
                updateOverallProgress();
            }

            function updateOverallProgress() {
                let overallLoaded = 0;
                for (let i = 0; i < fileStates.length; i++) {
                    const state = fileStates[i];
                    if (state.failed) {
                        overallLoaded += state.file.size;
                    } else {
                        for (const idx in state.chunkLoaded) {
                            overallLoaded += state.chunkLoaded[idx];
                        }
                    }
                }
                
                let percent = 0;
                if (totalSize > 0) {
                    percent = Math.round((overallLoaded / totalSize) * 100);
                    if (percent > 100) percent = 100;
                } else {
                    percent = 100;
                }
                progressBar.style.width = `${percent}%`;
                progressBar.textContent = `${percent}%`;
            }

            function checkFileComplete(state) {
                if (state.failed && !state.failedReported) {
                    state.failedReported = true;
                    uploadSummary.failed.push({
                        filename: state.file.name,
                        reason: state.failReason || 'Upload failed'
                    });
                } else if (!state.failed && state.chunksCompleted === state.totalChunks) {
                    uploadSummary.uploaded++;
                    uploadSummary.uploaded_files.push({
                        filename: state.file.name,
                        saved_as: state.saved_as || state.file.name
                    });
                }
            }

            function uploadChunkTask(task) {
                const chunkData = task.file.slice(task.start, task.end);
                const state = fileStates[task.fileIndex];
                
                const queryParams = new URLSearchParams();
                queryParams.append('filename', task.file.name);
                queryParams.append('chunk_index', task.chunkIndex);
                queryParams.append('total_chunks', task.totalChunks);
                queryParams.append('start_offset', task.start);
                queryParams.append('upload_id', state.uploadId);
                queryParams.append('platform_id', platformSelect.value);

                const urlWithQuery = baseUrl + (baseUrl.includes('?') ? '&' : '?') + queryParams.toString();

                const xhr = new XMLHttpRequest();
                xhr.open('POST', urlWithQuery);
                xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                xhr.setRequestHeader('Content-Type', 'application/octet-stream');

                xhr.upload.addEventListener('progress', (event) => {
                    if (event.lengthComputable && !state.failed) {
                        state.chunkLoaded[task.chunkIndex] = event.loaded;
                        updateOverallProgress();
                    }
                });

                xhr.onload = () => {
                    activeUploads--;
                    
                    if (!state.failed) {
                        state.chunkLoaded[task.chunkIndex] = task.end - task.start;
                    }

                    if (xhr.status >= 200 && xhr.status < 300) {
                        try {
                            const response = JSON.parse(xhr.responseText);
                            if (!response.success) {
                                state.failed = true;
                                state.failReason = response.message || 'Error saving chunk';
                            } else {
                                if (task.chunkIndex === task.totalChunks - 1 && response.saved_as) {
                                    state.saved_as = response.saved_as;
                                }
                            }
                        } catch(e) {
                            state.failed = true;
                            state.failReason = 'Invalid server response';
                        }
                    } else {
                        state.failed = true;
                        let errorMsg = `Server error ${xhr.status}`;
                        try {
                            const response = JSON.parse(xhr.responseText);
                            if (response.message) errorMsg = response.message;
                        } catch(e) {}
                        state.failReason = errorMsg;
                    }
                    
                    state.chunksCompleted++;
                    checkFileComplete(state);
                    processQueue();
                };

                xhr.onerror = () => {
                    activeUploads--;
                    state.failed = true;
                    state.failReason = 'Network error';
                    
                    state.chunksCompleted++;
                    checkFileComplete(state);
                    processQueue();
                };

                xhr.send(chunkData);
            }

            processQueue();

            function resetUploadForm() {
                submitBtn.disabled = false;
                submitBtn.classList.remove('btn-outline');
                progressContainer.classList.add('hidden');
                progressBar.style.width = '0%';
                progressBar.textContent = '0%';
            }
        });

        // "Upload More" button resets form for a new batch
        const uploadAnotherBtn = document.getElementById('upload-another-btn');
        if (uploadAnotherBtn) {
            uploadAnotherBtn.addEventListener('click', () => {
                const summaryPanel = document.getElementById('upload-summary');
                const formButtons = document.getElementById('form-buttons');
                const submitBtn = document.getElementById('upload-submit-btn');
                const progressContainer = document.getElementById('progress-container');
                const fileInput = document.getElementById('rom-file-input');
                const fileNameDisplay = document.getElementById('file-name-display');

                summaryPanel.classList.add('hidden');
                formButtons.classList.remove('hidden');
                uploadForm.classList.remove('hidden');
                progressContainer.classList.add('hidden');
                submitBtn.disabled = false;
                submitBtn.classList.remove('btn-outline');
                fileInput.value = '';
                if (fileNameDisplay) fileNameDisplay.textContent = '';
            });
        }
    }

    function renderUploadSummary(summary, contentEl, panelEl, formButtonsEl, progressEl) {
        const { total, uploaded, uploaded_files, skipped, failed } = summary;
        let html = '';

        // Stats bar
        html += '<div class="summary-stats">';
        html += `<div class="summary-stat summary-stat-success"><span class="summary-stat-value">${uploaded}</span><span class="summary-stat-label">Uploaded</span></div>`;
        if (skipped.length > 0) {
            html += `<div class="summary-stat summary-stat-skip"><span class="summary-stat-value">${skipped.length}</span><span class="summary-stat-label">Skipped</span></div>`;
        }
        if (failed.length > 0) {
            html += `<div class="summary-stat summary-stat-fail"><span class="summary-stat-value">${failed.length}</span><span class="summary-stat-label">Failed</span></div>`;
        }
        html += '</div>';

        // Uploaded files list
        if (uploaded_files && uploaded_files.length > 0) {
            html += '<div class="summary-section">';
            html += '<h3 class="summary-section-title summary-section-success">&#10003; Successfully Uploaded</h3>';
            html += '<ul class="summary-list">';
            uploaded_files.forEach(f => {
                const rename = (f.saved_as !== f.filename) ? ` <span class="summary-rename">&rarr; ${f.saved_as}</span>` : '';
                html += `<li class="summary-item summary-item-success">${f.filename}${rename}</li>`;
            });
            html += '</ul></div>';
        }

        // Skipped files list
        if (skipped.length > 0) {
            html += '<div class="summary-section">';
            html += '<h3 class="summary-section-title summary-section-skip">&#9888; Skipped</h3>';
            html += '<ul class="summary-list">';
            skipped.forEach(f => {
                html += `<li class="summary-item summary-item-skip">${f.filename} <span class="summary-reason">${f.reason}</span></li>`;
            });
            html += '</ul></div>';
        }

        // Failed files list
        if (failed.length > 0) {
            html += '<div class="summary-section">';
            html += '<h3 class="summary-section-title summary-section-fail">&#10007; Failed</h3>';
            html += '<ul class="summary-list">';
            failed.forEach(f => {
                html += `<li class="summary-item summary-item-fail">${f.filename} <span class="summary-reason">${f.reason}</span></li>`;
            });
            html += '</ul></div>';
        }

        contentEl.innerHTML = html;
        formButtonsEl.classList.add('hidden');
        progressEl.classList.add('hidden');
        panelEl.classList.remove('hidden');
    }

    // Inline keywords editing toggle
    const editBtns = document.querySelectorAll('.edit-keywords-btn');
    const cancelBtns = document.querySelectorAll('.cancel-keywords-btn');
    
    editBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const romId = btn.getAttribute('data-rom-id');
            const container = document.getElementById(`keywords-container-${romId}`);
            const form = document.getElementById(`edit-keywords-form-${romId}`);
            if (container && form) {
                container.classList.add('hidden');
                form.classList.remove('hidden');
                const input = form.querySelector('.keywords-input');
                if (input) {
                    input.focus();
                }
            }
        });
    });
    
    cancelBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const romId = btn.getAttribute('data-rom-id');
            const container = document.getElementById(`keywords-container-${romId}`);
            const form = document.getElementById(`edit-keywords-form-${romId}`);
            if (container && form) {
                form.classList.add('hidden');
                container.classList.remove('hidden');
            }
        });
    });

    // ---- Details Modal Logic ----
    const modalOverlay = document.getElementById('details-modal-overlay');
    const modal = document.getElementById('details-modal');
    const modalCloseBtn = document.getElementById('details-modal-close');
    const modalCoverImg = document.getElementById('modal-cover-img');
    const modalCoverPlaceholder = document.getElementById('modal-cover-placeholder');
    const modalTitle = document.getElementById('modal-title');
    const modalPlatform = document.getElementById('modal-platform');
    const modalFilename = document.getElementById('modal-filename');
    const modalBadges = document.getElementById('modal-badges');
    const modalDescription = document.getElementById('modal-description');
    const modalActions = document.getElementById('modal-actions');

    if (modalCoverImg) {
        modalCoverImg.addEventListener('error', () => {
            modalCoverImg.classList.add('hidden');
            if (modalCoverPlaceholder) {
                modalCoverPlaceholder.classList.remove('hidden');
            }
        });
    }

    function openDetailsModal(card) {
        if (!modalOverlay) return;

        const title = card.getAttribute('data-rom-title') || '';
        const filename = card.getAttribute('data-rom-filename') || '';
        const platform = card.getAttribute('data-rom-platform') || '';
        const cover = card.getAttribute('data-rom-cover') || '';
        const esrb = card.getAttribute('data-rom-esrb') || '';
        const genres = card.getAttribute('data-rom-genres') || '';
        const description = card.getAttribute('data-rom-description') || '';
        const downloadUrl = card.getAttribute('data-download-url') || '';
        const rescanUrl = card.getAttribute('data-rom-rescan-url') || '';
        const deleteUrl = card.getAttribute('data-rom-delete-url') || '';

        // Cover image
        if (cover) {
            modalCoverImg.src = cover;
            modalCoverImg.alt = title + ' cover art';
            modalCoverImg.classList.remove('hidden');
            if (modalCoverPlaceholder) modalCoverPlaceholder.classList.add('hidden');
        } else {
            modalCoverImg.classList.add('hidden');
            if (modalCoverPlaceholder) modalCoverPlaceholder.classList.remove('hidden');
        }

        // Title
        modalTitle.textContent = title;

        // Platform
        modalPlatform.textContent = 'Platform: ' + platform;

        // Filename
        modalFilename.textContent = 'File: ' + filename;

        // Badges
        let badgesHtml = '';
        if (esrb) {
            badgesHtml += `<span class="esrb-badge" data-rating="${esrb}">${esrb}</span>`;
        }
        if (genres) {
            genres.split(', ').forEach(genre => {
                if (genre.trim()) {
                    badgesHtml += `<span class="genre-badge">${genre.trim()}</span>`;
                }
            });
        }
        modalBadges.innerHTML = badgesHtml;

        // Description
        if (description) {
            modalDescription.innerHTML = `<h3>Overview</h3><p>${description}</p>`;
            modalDescription.classList.remove('hidden');
        } else {
            modalDescription.innerHTML = '';
            modalDescription.classList.add('hidden');
        }

        // Action buttons
        let actionsHtml = '';
        if (downloadUrl) {
            actionsHtml += `<a href="${downloadUrl}" class="btn btn-primary">Download</a>`;
        }
        if (rescanUrl) {
            actionsHtml += `<form action="${rescanUrl}" method="POST" class="modal-action-form"><button type="submit" class="btn btn-outline">Rescan</button></form>`;
        }
        if (deleteUrl) {
            actionsHtml += `<form action="${deleteUrl}" method="POST" class="modal-action-form delete-form"><button type="submit" class="btn btn-danger">Delete</button></form>`;
        }
        modalActions.innerHTML = actionsHtml;

        // Attach delete confirmation to modal delete forms
        modalActions.querySelectorAll('form.delete-form').forEach(form => {
            form.addEventListener('submit', (e) => {
                if (!confirm('Are you sure you want to delete this item? This action cannot be undone.')) {
                    e.preventDefault();
                }
            });
        });

        // Show modal
        modalOverlay.classList.remove('hidden');
        requestAnimationFrame(() => {
            modalOverlay.classList.add('modal-visible');
        });

        // Prevent body scroll
        document.body.style.overflow = 'hidden';
    }

    function closeDetailsModal() {
        if (!modalOverlay) return;

        modalOverlay.classList.remove('modal-visible');
        
        setTimeout(() => {
            modalOverlay.classList.add('hidden');
            document.body.style.overflow = '';
        }, 300);
    }

    // Close button
    if (modalCloseBtn) {
        modalCloseBtn.addEventListener('click', closeDetailsModal);
    }

    // Click outside modal to close
    if (modalOverlay) {
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) {
                closeDetailsModal();
            }
        });
    }

    // Escape key to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modalOverlay && !modalOverlay.classList.contains('hidden')) {
            closeDetailsModal();
        }
    });

    // ROM card click → open details modal (instead of download)
    const romCards = document.querySelectorAll('.rom-card');

    romCards.forEach(card => {
        // Details button click
        const detailsBtn = card.querySelector('.details-btn');
        if (detailsBtn) {
            detailsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                openDetailsModal(card);
            });
        }

        // Card click → open modal
        card.addEventListener('click', (e) => {
            // Prevent modal if clicking on an interactive element
            if (e.target.closest('button') || 
                e.target.closest('input') || 
                e.target.closest('form') || 
                e.target.closest('a') ||
                e.target.closest('.edit-keywords-form')) {
                return;
            }
            
            // Prevent if user is drag-selecting text
            if (window.getSelection && window.getSelection().toString().trim() !== '') {
                return;
            }

            openDetailsModal(card);
        });
    });

    // ---- Cascading Device + Platform filtering ----
    const deviceFilterTabs = document.querySelectorAll('#device-filter-tabs .filter-tab');
    const platformFilterTabs = document.querySelectorAll('#platform-filter-tabs .filter-tab');
    const noRomsPlaceholder = document.getElementById('no-roms-filtered');
    const resetFiltersBtn = document.getElementById('reset-filters-btn');

    // Restore persisted filter state or default to 'all'
    let activeDeviceId = localStorage.getItem('rommagic_filter_device') || 'all';
    let activePlatformId = localStorage.getItem('rommagic_filter_platform') || 'all';

    function saveFilterState() {
        localStorage.setItem('rommagic_filter_device', activeDeviceId);
        localStorage.setItem('rommagic_filter_platform', activePlatformId);
    }

    function applyFilters() {
        let visibleCount = 0;

        romCards.forEach(card => {
            const cardDeviceId = String(card.getAttribute('data-device-id') || '');
            const cardPlatformId = String(card.getAttribute('data-platform-id') || '');

            const matchesDevice = activeDeviceId === 'all' || cardDeviceId === String(activeDeviceId);
            const matchesPlatform = activePlatformId === 'all' || cardPlatformId === String(activePlatformId);

            if (matchesDevice && matchesPlatform) {
                card.classList.remove('hidden');
                visibleCount++;
            } else {
                card.classList.add('hidden');
            }
        });

        // Show/hide no roms placeholder
        if (noRomsPlaceholder) {
            if (visibleCount === 0) {
                noRomsPlaceholder.classList.remove('hidden');
            } else {
                noRomsPlaceholder.classList.add('hidden');
            }
        }
    }

    function updatePlatformTabs() {
        // Show/hide platform tabs based on active device filter
        // Also update the "All" badge count for platforms
        let relevantRomCount = 0;

        platformFilterTabs.forEach(tab => {
            const tabPlatformId = String(tab.getAttribute('data-platform-id') || '');
            const tabDeviceId = String(tab.getAttribute('data-device-id') || '');

            if (tabPlatformId === 'all') {
                // "All" tab is always visible — badge updated below
                tab.classList.remove('filter-tab-hidden');
                return;
            }

            if (activeDeviceId === 'all' || tabDeviceId === String(activeDeviceId)) {
                tab.classList.remove('filter-tab-hidden');
                // Count ROMs for this platform that match the device filter
                let count = 0;
                romCards.forEach(card => {
                    if (String(card.getAttribute('data-platform-id') || '') === tabPlatformId &&
                        (activeDeviceId === 'all' || String(card.getAttribute('data-device-id') || '') === String(activeDeviceId))) {
                        count++;
                    }
                });
                relevantRomCount += count;
            } else {
                tab.classList.add('filter-tab-hidden');
            }
        });

        // Update the "All" badge in platform tabs
        if (activeDeviceId === 'all') {
            relevantRomCount = romCards.length;
        }
        const allBadge = document.getElementById('platform-all-badge');
        if (allBadge) {
            allBadge.textContent = relevantRomCount;
        }
    }

    function activateFilterTab(tabs, attrName, value) {
        tabs.forEach(t => t.classList.remove('active'));
        let matched = false;
        tabs.forEach(t => {
            if (String(t.getAttribute(attrName) || '') === String(value)) {
                t.classList.add('active');
                matched = true;
            }
        });
        return matched;
    }

    // Restore saved filter UI state on page load
    if (deviceFilterTabs.length > 0 || platformFilterTabs.length > 0) {
        // Validate saved device still exists in the DOM, fall back to 'all'
        if (!activateFilterTab(deviceFilterTabs, 'data-device-id', activeDeviceId)) {
            activeDeviceId = 'all';
            activateFilterTab(deviceFilterTabs, 'data-device-id', 'all');
        }

        updatePlatformTabs();

        // Validate saved platform still exists and is visible, fall back to 'all'
        if (!activateFilterTab(platformFilterTabs, 'data-platform-id', activePlatformId)) {
            activePlatformId = 'all';
            activateFilterTab(platformFilterTabs, 'data-platform-id', 'all');
        } else {
            // Check if the matched platform tab is hidden (device mismatch)
            const activePlatformTab = document.querySelector(`#platform-filter-tabs .filter-tab[data-platform-id="${activePlatformId}"]`);
            if (activePlatformTab && activePlatformTab.classList.contains('filter-tab-hidden')) {
                activePlatformId = 'all';
                activateFilterTab(platformFilterTabs, 'data-platform-id', 'all');
            }
        }

        saveFilterState();
        applyFilters();
    }

    if (deviceFilterTabs.length > 0) {
        deviceFilterTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                deviceFilterTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                activeDeviceId = tab.getAttribute('data-device-id');

                // Reset platform selection to "All" when device changes
                activePlatformId = 'all';
                platformFilterTabs.forEach(t => t.classList.remove('active'));
                const platformAllTab = document.querySelector('#platform-filter-tabs .filter-tab[data-platform-id="all"]');
                if (platformAllTab) platformAllTab.classList.add('active');

                updatePlatformTabs();
                applyFilters();
                saveFilterState();
            });
        });
    }

    if (platformFilterTabs.length > 0) {
        platformFilterTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                platformFilterTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                activePlatformId = tab.getAttribute('data-platform-id') || 'all';
                applyFilters();
                saveFilterState();
            });
        });
    }

    if (resetFiltersBtn) {
        resetFiltersBtn.addEventListener('click', () => {
            activeDeviceId = 'all';
            activePlatformId = 'all';
            activateFilterTab(deviceFilterTabs, 'data-device-id', 'all');
            activateFilterTab(platformFilterTabs, 'data-platform-id', 'all');
            updatePlatformTabs();
            applyFilters();
            saveFilterState();
        });
    }

    // ---- Batch Selection Logic ----
    const selectAllBtn = document.getElementById('select-all-btn');
    const batchActionBar = document.getElementById('batch-action-bar');
    const batchSelectedCount = document.getElementById('batch-selected-count');
    const batchCancelBtn = document.getElementById('batch-cancel-btn');
    const batchDeleteBtn = document.getElementById('batch-delete-btn');
    const batchRescrapeBtn = document.getElementById('batch-rescrape-btn');
    const batchDownloadBtn = document.getElementById('batch-download-btn');
    const batchDownloadForm = document.getElementById('batch-download-form');
    const checkboxes = document.querySelectorAll('.rom-select-cb');

    function updateBatchSelection() {
        const selectedCount = document.querySelectorAll('.rom-select-cb:checked').length;
        if (selectedCount > 0) {
            batchSelectedCount.textContent = `${selectedCount} selected`;
            batchActionBar.classList.remove('hidden');
        } else {
            batchActionBar.classList.add('hidden');
        }
    }

    function getSelectedRomIds() {
        return Array.from(document.querySelectorAll('.rom-select-cb:checked')).map(cb => cb.value);
    }

    if (checkboxes.length > 0) {
        checkboxes.forEach(cb => {
            cb.addEventListener('change', (e) => {
                const card = e.target.closest('.rom-card');
                if (e.target.checked) {
                    card.classList.add('selected');
                } else {
                    card.classList.remove('selected');
                }
                updateBatchSelection();
            });

            // Prevent card click from opening modal when clicking checkbox
            cb.addEventListener('click', (e) => {
                e.stopPropagation();
            });
        });
    }

    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            const isSelectAll = selectAllBtn.textContent === 'Select All Visible';
            
            romCards.forEach(card => {
                // Only act on visible cards
                if (!card.classList.contains('hidden')) {
                    const cb = card.querySelector('.rom-select-cb');
                    if (cb) {
                        cb.checked = isSelectAll;
                        if (isSelectAll) {
                            card.classList.add('selected');
                        } else {
                            card.classList.remove('selected');
                        }
                    }
                }
            });

            if (isSelectAll) {
                selectAllBtn.textContent = 'Deselect All Visible';
            } else {
                selectAllBtn.textContent = 'Select All Visible';
            }
            
            updateBatchSelection();
        });
    }

    if (batchCancelBtn) {
        batchCancelBtn.addEventListener('click', () => {
            checkboxes.forEach(cb => {
                cb.checked = false;
                const card = cb.closest('.rom-card');
                if (card) card.classList.remove('selected');
            });
            if (selectAllBtn) selectAllBtn.textContent = 'Select All Visible';
            updateBatchSelection();
        });
    }

    if (batchDeleteBtn) {
        batchDeleteBtn.addEventListener('click', () => {
            const selectedIds = getSelectedRomIds();
            if (selectedIds.length === 0) return;
            
            if (confirm(`Are you sure you want to delete ${selectedIds.length} selected ROMs? This action cannot be undone.`)) {
                batchDeleteBtn.disabled = true;
                batchDeleteBtn.textContent = 'Deleting...';
                
                fetch('/roms/batch_delete', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ rom_ids: selectedIds })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showFlashMessage(data.message, 'success');
                        // Remove deleted cards from DOM
                        selectedIds.forEach(id => {
                            const card = document.querySelector(`.rom-card[data-rom-id="${id}"]`);
                            if (card) card.remove();
                        });
                        // Update active arrays
                        // We do a simple page reload for simplicity and ensuring state is clean
                        window.location.reload();
                    } else {
                        showFlashMessage(data.message || 'Error deleting ROMs', 'error');
                        batchDeleteBtn.disabled = false;
                        batchDeleteBtn.textContent = 'Delete Selected';
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    showFlashMessage('An error occurred while deleting ROMs', 'error');
                    batchDeleteBtn.disabled = false;
                    batchDeleteBtn.textContent = 'Delete Selected';
                });
            }
        });
    }

    if (batchRescrapeBtn) {
        batchRescrapeBtn.addEventListener('click', () => {
            const selectedIds = getSelectedRomIds();
            if (selectedIds.length === 0) return;
            
            if (confirm(`Are you sure you want to rescrape metadata for ${selectedIds.length} selected ROM(s)?`)) {
                batchRescrapeBtn.disabled = true;
                batchRescrapeBtn.textContent = 'Rescraping...';
                
                fetch('/roms/batch_rescrape', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ rom_ids: selectedIds })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showFlashMessage(data.message, 'success');
                        setTimeout(() => {
                            window.location.reload();
                        }, 2000);
                    } else {
                        showFlashMessage(data.message || 'Error rescraping ROMs', 'error');
                        batchRescrapeBtn.disabled = false;
                        batchRescrapeBtn.textContent = 'Rescrape Selected';
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    showFlashMessage('An error occurred while rescraping ROMs', 'error');
                    batchRescrapeBtn.disabled = false;
                    batchRescrapeBtn.textContent = 'Rescrape Selected';
                });
            }
        });
    }

    if (batchDownloadBtn && batchDownloadForm) {
        batchDownloadBtn.addEventListener('click', () => {
            const selectedIds = getSelectedRomIds();
            if (selectedIds.length === 0) return;
            
            // Clear existing hidden inputs
            batchDownloadForm.innerHTML = '';
            
            // Add an input for each selected ID
            selectedIds.forEach(id => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'rom_ids';
                input.value = id;
                batchDownloadForm.appendChild(input);
            });
            
            // Submit form
            batchDownloadForm.submit();
        });
    }
    // Background ROM Compression Download logic
    const downloadRomsBtns = document.querySelectorAll('.download-roms-btn');
    const compressionModal = document.getElementById('compression-modal');
    const compressionStatusText = document.getElementById('compression-status-text');
    const compressionProgressBar = document.getElementById('compression-progress-bar');
    const compressionErrorText = document.getElementById('compression-error-text');

    if (downloadRomsBtns.length > 0 && compressionModal) {
        downloadRomsBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const url = btn.getAttribute('data-url');
                if (!url) return;
                
                // Show modal
                compressionModal.style.display = 'block';
                compressionProgressBar.style.width = '0%';
                compressionStatusText.textContent = 'Preparing files for download...';
                compressionErrorText.style.display = 'none';
                
                // Start background task
                fetch(url, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        compressionErrorText.textContent = data.error;
                        compressionErrorText.style.display = 'block';
                        compressionStatusText.textContent = 'Error starting compression.';
                    } else if (data.task_id) {
                        pollCompressionStatus(data.task_id);
                    }
                })
                .catch(err => {
                    console.error(err);
                    compressionErrorText.textContent = 'Network error starting compression.';
                    compressionErrorText.style.display = 'block';
                });
            });
        });
        
        function pollCompressionStatus(taskId) {
            const pollInterval = setInterval(() => {
                fetch(`/platforms/download_roms_status/${taskId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        clearInterval(pollInterval);
                        compressionErrorText.textContent = data.error;
                        compressionErrorText.style.display = 'block';
                        compressionStatusText.textContent = 'Error checking status.';
                        return;
                    }
                    
                    compressionProgressBar.style.width = `${data.progress}%`;
                    
                    if (data.status === 'processing') {
                        compressionStatusText.textContent = `Compressing ROMs... ${data.progress}%`;
                    } else if (data.status === 'completed') {
                        clearInterval(pollInterval);
                        compressionStatusText.textContent = 'Compression complete! Downloading...';
                        compressionProgressBar.style.width = '100%';
                        
                        setTimeout(() => {
                            compressionModal.style.display = 'none';
                            window.location.href = `/platforms/download_roms_file/${taskId}`;
                        }, 1000);
                    } else if (data.status === 'error') {
                        clearInterval(pollInterval);
                        compressionErrorText.textContent = data.error_message || 'An error occurred during compression.';
                        compressionErrorText.style.display = 'block';
                        compressionStatusText.textContent = 'Compression failed.';
                    }
                })
                .catch(err => {
                    console.error(err);
                    clearInterval(pollInterval);
                    compressionErrorText.textContent = 'Network error checking status.';
                    compressionErrorText.style.display = 'block';
                });
            }, 1500);
        }
    }

    // ==========================================
    // Game Saves UI and Batch Selection Handlers
    // ==========================================
    const toggleUploadBtn = document.getElementById('toggle-upload-btn');
    const cancelUploadBtn = document.getElementById('cancel-upload-btn');
    const uploadSaveCard = document.getElementById('upload-save-card');

    if (toggleUploadBtn && uploadSaveCard) {
        toggleUploadBtn.addEventListener('click', () => {
            const isHidden = window.getComputedStyle(uploadSaveCard).display === 'none';
            uploadSaveCard.style.display = isHidden ? 'block' : 'none';
            toggleUploadBtn.textContent = isHidden ? '- Hide Upload Form' : '+ Upload Save Files';
        });
    }

    if (cancelUploadBtn && uploadSaveCard) {
        cancelUploadBtn.addEventListener('click', () => {
            uploadSaveCard.style.display = 'none';
            if (toggleUploadBtn) toggleUploadBtn.textContent = '+ Upload Save Files / Folders';
        });
    }

    // Drag & Drop / Selection Preview for Merged Saves Dropzone
    const savesDropzone = document.getElementById('saves-dropzone');
    const saveFilesInput = document.getElementById('save_files');
    const saveFolderFilesInput = document.getElementById('save_folder_files');
    const saveFilePreview = document.getElementById('save-file-preview');

    function updateSavePreview() {
        if (!saveFilePreview) return;
        let count = 0;
        let names = [];

        if (saveFilesInput && saveFilesInput.files.length > 0) {
            count += saveFilesInput.files.length;
            names.push(`${saveFilesInput.files.length} file(s)`);
        }
        if (saveFolderFilesInput && saveFolderFilesInput.files.length > 0) {
            count += saveFolderFilesInput.files.length;
            names.push(`${saveFolderFilesInput.files.length} folder item(s)`);
        }

        if (count > 0) {
            saveFilePreview.style.display = 'block';
            saveFilePreview.textContent = `Selected for upload: ${names.join(', ')} (${count} total items)`;
        } else {
            saveFilePreview.style.display = 'none';
            saveFilePreview.textContent = '';
        }
    }

    if (saveFilesInput) saveFilesInput.addEventListener('change', updateSavePreview);
    if (saveFolderFilesInput) saveFolderFilesInput.addEventListener('change', updateSavePreview);

    if (savesDropzone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            savesDropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                savesDropzone.style.background = 'rgba(56, 189, 248, 0.15)';
                savesDropzone.style.borderColor = '#0284c7';
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            savesDropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                savesDropzone.style.background = 'rgba(56, 189, 248, 0.04)';
                savesDropzone.style.borderColor = 'var(--primary-color, #38bdf8)';
            }, false);
        });
    }

    // Filter Navigation for Game Saves
    const filterDevice = document.getElementById('filter_device');
    const filterPlatform = document.getElementById('filter_platform');

    if (filterDevice && filterPlatform) {
        filterDevice.addEventListener('change', () => {
            const devId = filterDevice.value;
            const currentPlat = filterPlatform.value;
            let url = '/saves/';
            const params = new URLSearchParams();
            if (devId) params.set('device_id', devId);
            if (currentPlat) {
                // Only keep platform if it matches device
                const opt = filterPlatform.querySelector(`option[value="${currentPlat}"]`);
                if (opt && (!devId || opt.getAttribute('data-device') === devId)) {
                    params.set('platform_id', currentPlat);
                }
            }
            if (params.toString()) url += '?' + params.toString();
            window.location.href = url;
        });

        filterPlatform.addEventListener('change', () => {
            const platId = filterPlatform.value;
            const devId = filterDevice.value;
            let url = '/saves/';
            const params = new URLSearchParams();
            if (devId) params.set('device_id', devId);
            if (platId) params.set('platform_id', platId);
            if (params.toString()) url += '?' + params.toString();
            window.location.href = url;
        });
    }

    // Batch Selection Logic for Game Saves
    const savesSelectAll = document.getElementById('saves-select-all');
    const saveCheckboxes = document.querySelectorAll('.save-checkbox');
    const savesSelectedCount = document.getElementById('saves-selected-count');
    const savesBatchDownloadBtn = document.getElementById('batch-download-btn');
    const savesBatchDeleteBtn = document.getElementById('batch-delete-btn');
    const batchDownloadInputs = document.getElementById('batch-download-inputs');
    const batchDeleteInputs = document.getElementById('batch-delete-inputs');

    function updateSavesBatchState() {
        const checkedBoxes = document.querySelectorAll('.save-checkbox:checked');
        const count = checkedBoxes.length;

        if (savesSelectedCount) {
            savesSelectedCount.textContent = `(${count} selected)`;
        }

        if (savesBatchDownloadBtn) savesBatchDownloadBtn.disabled = count === 0;
        if (savesBatchDeleteBtn) savesBatchDeleteBtn.disabled = count === 0;

        if (savesSelectAll && saveCheckboxes.length > 0) {
            savesSelectAll.checked = count === saveCheckboxes.length;
            savesSelectAll.indeterminate = count > 0 && count < saveCheckboxes.length;
        }

        // Populate hidden inputs for batch forms
        if (batchDownloadInputs) {
            batchDownloadInputs.innerHTML = '';
            checkedBoxes.forEach(cb => {
                const hidden = document.createElement('input');
                hidden.type = 'hidden';
                hidden.name = 'save_items';
                hidden.value = cb.value;
                batchDownloadInputs.appendChild(hidden);
            });
        }

        if (batchDeleteInputs) {
            batchDeleteInputs.innerHTML = '';
            checkedBoxes.forEach(cb => {
                const hidden = document.createElement('input');
                hidden.type = 'hidden';
                hidden.name = 'save_items';
                hidden.value = cb.value;
                batchDeleteInputs.appendChild(hidden);
            });
        }
    }

    if (savesSelectAll) {
        savesSelectAll.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            saveCheckboxes.forEach(cb => {
                cb.checked = isChecked;
            });
            updateSavesBatchState();
        });
    }

    saveCheckboxes.forEach(cb => {
        cb.addEventListener('change', updateSavesBatchState);
    });

});
