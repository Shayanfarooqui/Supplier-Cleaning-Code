document.addEventListener('DOMContentLoaded', () => {
    const fileStore = {};
    let selectedSupplier = null;

    // Toast Notification helper
    const showToast = (message, type = 'info') => {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = `toast show ${type}`;
        setTimeout(() => {
            toast.className = 'toast hidden';
        }, 4000);
    };

    // Screen Navigation
    const showScreen = (screenId) => {
        document.getElementById('homeScreen').classList.add('hidden');
        document.getElementById('uploadScreen').classList.add('hidden');
        document.getElementById('resultsScreen').classList.add('hidden');
        document.getElementById(screenId).classList.remove('hidden');
    };

    // Supplier Selection
    const supplierCards = document.querySelectorAll('.supplier-card');
    supplierCards.forEach(card => {
        card.addEventListener('click', () => {
            selectedSupplier = card.dataset.supplier;

            // Update title
            const supplierName = card.querySelector('h3').textContent;
            document.getElementById('supplierTitle').textContent = `Upload ${supplierName} Files`;

            // Show appropriate file fields
            document.querySelectorAll('.supplier-fields').forEach(f => f.classList.add('hidden'));
            const fieldId = `${selectedSupplier}-fields`;
            const fieldsElement = document.getElementById(fieldId);
            if (fieldsElement) {
                fieldsElement.classList.remove('hidden');
            }

            // Clear previous files
            fileStore[selectedSupplier] = {};

            showScreen('uploadScreen');
        });
    });

    // File Handling
    const setupDropzones = () => {
        const dropzones = document.querySelectorAll('.dropzone');

        dropzones.forEach(dropzone => {
            const input = dropzone.querySelector('input[type="file"]');

            // Click to browse
            dropzone.addEventListener('click', (e) => {
                if (e.target !== input) {
                    input.click();
                }
            });

            // File input change
            input.addEventListener('change', (e) => {
                handleFile(dropzone, e.target.files[0]);
            });

            // Drag and drop events
            dropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropzone.classList.add('drag-active');
            });

            dropzone.addEventListener('dragleave', (e) => {
                e.preventDefault();
                dropzone.classList.remove('drag-active');
            });

            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('drag-active');

                if (e.dataTransfer.files.length) {
                    input.files = e.dataTransfer.files;
                    handleFile(dropzone, e.dataTransfer.files[0]);
                }
            });
        });
    };

    const handleFile = (dropzone, file) => {
        if (!file) return;

        // Basic validation
        const validExts = ['.csv', '.xlsx', '.xls'];
        const fileName = file.name;
        const ext = fileName.substring(fileName.lastIndexOf('.')).toLowerCase();

        if (!validExts.includes(ext)) {
            showToast('Please upload a valid CSV or Excel file', 'error');
            return;
        }

        const inputName = dropzone.dataset.inputName;

        // Store file
        if (!fileStore[selectedSupplier]) {
            fileStore[selectedSupplier] = {};
        }
        fileStore[selectedSupplier][inputName] = file;

        // Update UI
        dropzone.classList.add('has-file');
        const fileNameDiv = dropzone.querySelector('.file-name');
        fileNameDiv.textContent = file.name;
    };

    setupDropzones();

    // Supplier Configuration
    const supplierConfig = {
        chicken: {
            requiredFields: ['chicken_info', 'chicken_cost'],
            apiEndpoint: '/api/clean',
            files: ['chicken_info', 'chicken_cost']
        },
        extra_uk: {
            requiredFields: ['extra_uk'],
            apiEndpoint: '/api/clean_extra_uk',
            files: ['extra_uk']
        },
        zyrofisher: {
            requiredFields: ['zyro_info', 'zyro_price'],
            apiEndpoint: '/api/clean_zyrofisher',
            files: ['zyro_info', 'zyro_price']
        },
        ison: {
            requiredFields: ['ison'],
            apiEndpoint: '/api/clean_ison',
            files: ['ison']
        }
    };

    // Process Button
    const processBtn = document.getElementById('processBtn');
    processBtn.addEventListener('click', async () => {
        const config = supplierConfig[selectedSupplier];

        // Validation: Check required fields
        const supplierFiles = fileStore[selectedSupplier] || {};
        const missingFields = config.requiredFields.filter(f => !supplierFiles[f]);

        if (missingFields.length > 0) {
            showToast(`Please upload all required files for ${selectedSupplier}`, 'error');
            return;
        }

        // UI Feedback
        const originalText = processBtn.innerHTML;
        processBtn.innerHTML = '<i class="ph ph-spinner spinning"></i> Processing...';
        processBtn.disabled = true;

        try {
            const formData = new FormData();
            config.files.forEach(fileKey => {
                if (supplierFiles[fileKey]) {
                    formData.append(fileKey, supplierFiles[fileKey]);
                }
            });

            const response = await fetch(config.apiEndpoint, {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                showToast('Files cleaned successfully!', 'success');

                // Update insights
                if (data.insights) {
                    document.getElementById('infoFileRows').textContent = (data.insights.info_file_rows || 0).toLocaleString();
                    document.getElementById('costFileRows').textContent = (data.insights.cost_file_rows || 0).toLocaleString();
                    document.getElementById('matchedWithPrice').textContent = (data.insights.matched_with_price || 0).toLocaleString();
                    document.getElementById('missingVitalInfo').textContent = (data.insights.missing_vital_info || 0).toLocaleString();
                    document.getElementById('removedRows').textContent = (data.insights.removed_rows || 0).toLocaleString();
                    document.getElementById('finalCount').textContent = (data.after_rows || 0).toLocaleString();
                }

                // Update download links
                if (data.downloads.cleaned) {
                    document.getElementById('downloadCleaned').href = data.downloads.cleaned;
                }

                if (data.downloads.removed) {
                    const removedCard = document.getElementById('downloadRemoved');
                    removedCard.href = data.downloads.removed;
                    removedCard.classList.remove('hidden');
                } else {
                    document.getElementById('downloadRemoved').classList.add('hidden');
                }

                // Show results screen
                showScreen('resultsScreen');

            } else {
                throw new Error(data.message || 'Error processing files');
            }
        } catch (error) {
            console.error('Processing error:', error);
            showToast(error.message, 'error');
        } finally {
            processBtn.innerHTML = originalText;
            processBtn.disabled = false;
        }
    });

    // Back Button (from upload to home)
    const backBtn = document.getElementById('backBtn');
    backBtn.addEventListener('click', () => {
        showScreen('homeScreen');
        selectedSupplier = null;
    });

    // Home Button (from results to home)
    const homeBtn = document.getElementById('homeBtn');
    homeBtn.addEventListener('click', () => {
        showScreen('homeScreen');
        selectedSupplier = null;
        fileStore = {};
    });
});
