document.addEventListener('DOMContentLoaded', () => {
    const button = document.querySelector('[data-barcode-scan]');
    const stopButton = document.querySelector('[data-barcode-stop]');
    const video = document.querySelector('[data-barcode-video]');
    const status = document.querySelector('[data-barcode-status]');
    const input = document.querySelector('input[name="barcode"]');
    const lookupButton = document.querySelector('[data-barcode-lookup]');
    if (!button || !stopButton || !video || !status || !input) {
        return;
    }
    if (lookupButton) {
        lookupButton.addEventListener('click', async () => {
            const barcode = input.value.trim();
            if (!barcode) {
                status.textContent = 'Enter or scan a barcode first.';
                return;
            }
            lookupButton.disabled = true;
            status.textContent = 'Looking up inventory...';
            try {
                const response = await fetch(
                    `${lookupButton.dataset.barcodeLookupUrl}?barcode=${encodeURIComponent(barcode)}`,
                    {headers: {'Accept': 'application/json'}},
                );
                const data = await response.json();
                if (!response.ok) {
                    status.textContent = data.detail || 'No matching inventory item found.';
                    return;
                }
                status.textContent = `Found ${data.name} (${data.quantity} ${data.unit}), expires ${data.expiry_date}.`;
                const fields = {
                    name: data.name,
                    category: data.category,
                    quantity: data.quantity,
                    unit: data.unit,
                    expiry_date: data.expiry_date,
                    storage_location: data.storage_location,
                    risk_level: data.risk_level,
                };
                Object.entries(fields).forEach(([name, value]) => {
                    const field = document.querySelector(`[name="${name}"]`);
                    if (field && !field.value) field.value = value;
                });
            } catch (error) {
                status.textContent = 'Inventory lookup failed. Try again.';
                console.error('Barcode inventory lookup failed', error);
            } finally {
                lookupButton.disabled = false;
            }
        });
    }
    if (!('BarcodeDetector' in window) || !navigator.mediaDevices?.getUserMedia) {
        button.disabled = true;
        status.textContent = 'Barcode scanning is not supported by this browser.';
        return;
    }

    let stream = null;
    let animationFrame = null;
    let scanning = false;

    const stopScanning = () => {
        scanning = false;
        if (animationFrame) cancelAnimationFrame(animationFrame);
        if (stream) stream.getTracks().forEach(track => track.stop());
        stream = null;
        video.srcObject = null;
        video.classList.add('d-none');
        stopButton.classList.add('d-none');
        button.disabled = false;
    };

    stopButton.addEventListener('click', () => {
        stopScanning();
        status.textContent = 'Scanner stopped.';
    });

    button.addEventListener('click', async () => {
        if (scanning) return;
        try {
            const detector = new BarcodeDetector();
            stream = await navigator.mediaDevices.getUserMedia({
                video: {facingMode: {ideal: 'environment'}},
                audio: false,
            });
            scanning = true;
            button.disabled = true;
            stopButton.classList.remove('d-none');
            status.textContent = 'Point the camera at a barcode or QR code.';
            video.srcObject = stream;
            video.classList.remove('d-none');
            await video.play();

            const scan = async () => {
                if (!scanning) return;
                try {
                    const codes = await detector.detect(video);
                    if (codes.length && codes[0].rawValue) {
                        input.value = codes[0].rawValue.slice(0, 128);
                        stopScanning();
                        status.textContent = 'Barcode captured.';
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        return;
                    }
                    animationFrame = requestAnimationFrame(scan);
                } catch (error) {
                    stopScanning();
                    status.textContent = 'Unable to read the barcode. Try again.';
                    console.error('Barcode detection failed', error);
                }
            };
            scan();
        } catch (error) {
            stopScanning();
            status.textContent = 'Camera permission is required to scan.';
            console.error('Barcode camera access failed', error);
        }
    });

    window.addEventListener('beforeunload', () => {
        stopScanning();
    });
});
