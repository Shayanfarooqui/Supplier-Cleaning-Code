document.addEventListener('DOMContentLoaded', () => {
    const dropzones = document.querySelectorAll('.dropzone');
    const processBtn = document.getElementById('processBtn');
    const fileStore = {};

    // Toast Notification helper
    const showToast = (message, type = 'info') => {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = `toast show ${type}`;
        setTimeout(() => {
            toast.className = 'toast hidden';
        }, 4000);
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
        fileStore[inputName] = file;

        // Update UI
        dropzone.classList.add('has-file');
        const fileNameDiv = dropzone.querySelector('.file-name');
        fileNameDiv.textContent = file.name;
    };

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

    let currentJobId = null;

    // Handle Processing Step 1
    processBtn.addEventListener('click', async () => {
        // Validation: Ensure we have at least one supplier file
        const supplierKeys = ['chicken_info', 'chicken_cost', 'extra_uk', 'zyrofisher', 'ison'];
        const uploadedSuppliers = supplierKeys.filter(k => fileStore[k]);
        
        if (uploadedSuppliers.length === 0) {
            showToast('Please upload at least one supplier file', 'error');
            return;
        }

        // UI Feedback
        const originalText = processBtn.innerHTML;
        processBtn.innerHTML = '<i class="ph ph-spinner spinning"></i> Processing...';
        processBtn.disabled = true;

        try {
            const formData = new FormData();
            for (const key of uploadedSuppliers) {
                formData.append(key, fileStore[key]);
            }

            const response = await fetch('/api/clean_suppliers', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                showToast('Supplier files cleaned successfully!', 'success');
                
                // Store job ID
                currentJobId = data.job_id;
                
                // Update analysis table
                const tbody = document.querySelector('#analysisTable tbody');
                tbody.innerHTML = '';
                if (data.analysis) {
                    for (const [supplier, counts] of Object.entries(data.analysis)) {
                        if (counts.before > 0 || counts.after > 0) {
                            const tr = document.createElement('tr');
                            const downloadCell = counts.download
                                ? `<td><a href="${counts.download}" class="btn-download-sm" title="Download cleaned ${supplier} file"><i class="ph ph-download-simple"></i> CSV</a></td>`
                                : `<td><span class="btn-download-sm disabled">N/A</span></td>`;
                            tr.innerHTML = `
                                <td>${supplier}</td>
                                <td>${counts.before.toLocaleString()}</td>
                                <td>${counts.after.toLocaleString()}</td>
                                ${downloadCell}
                            `;
                            tbody.appendChild(tr);
                        }
                    }
                }
                
                // Show merged file download if available
                const mergedSection = document.getElementById('mergedDownloadSection');
                if (data.downloads && data.downloads.merged) {
                    document.getElementById('downloadMerged').href = data.downloads.merged;
                    mergedSection.classList.remove('hidden');
                } else {
                    mergedSection.classList.add('hidden');
                }
                
                // Transition UI to Step 2
                document.getElementById('step1').classList.add('step-disabled');
                document.getElementById('step2').classList.remove('hidden');

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

    // Handle Comparison Step 2
    const compareBtn = document.getElementById('compareBtn');
    if (compareBtn) {
        compareBtn.addEventListener('click', async () => {
            if (!fileStore['lightspeed'] || !currentJobId) {
                showToast('Please upload Lightspeed Extract', 'error');
                return;
            }

            const originalText = compareBtn.innerHTML;
            compareBtn.innerHTML = '<i class="ph ph-spinner spinning"></i> Comparing...';
            compareBtn.disabled = true;
            document.getElementById('downloadsSection').classList.add('hidden');

            try {
                const formData = new FormData();
                formData.append('job_id', currentJobId);
                formData.append('lightspeed', fileStore['lightspeed']);

                const response = await fetch('/api/compare_lightspeed', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();

                if (response.ok) {
                    showToast('Comparison complete!', 'success');
                    
                    document.getElementById('downloadsSection').classList.remove('hidden');
                    
                    // Update download links
                    document.getElementById('downloadMatched').href = data.downloads.matched;
                    document.getElementById('downloadNew').href = data.downloads.new_skus;
                    document.getElementById('downloadOutliers').href = data.downloads.outliers;
                    document.getElementById('downloadBox').href = data.downloads.box_qty;
                } else {
                    throw new Error(data.message || 'Error comparing files');
                }
            } catch (error) {
                console.error('Comparison error:', error);
                showToast(error.message, 'error');
            } finally {
                compareBtn.innerHTML = originalText;
                compareBtn.disabled = false;
            }
        });
    }
});
