(function () {
    function setVisibility(button) {
        const input = document.querySelector(button.dataset.passwordToggle);
        if (!input) return;
        const isHidden = input.type === 'password';
        input.type = isHidden ? 'text' : 'password';
        button.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
        const icon = button.querySelector('i');
        if (icon) icon.className = isHidden ? 'bi bi-eye-slash' : 'bi bi-eye';
    }

    function passwordScore(password) {
        let score = 0;
        if (password.length >= 10) score++;
        if (password.length >= 14) score++;
        if (/[A-Z]/.test(password)) score++;
        if (/[a-z]/.test(password)) score++;
        if (/[0-9]/.test(password)) score++;
        if (/[^A-Za-z0-9]/.test(password)) score++;
        return Math.min(4, Math.floor(score * 2 / 3));
    }

    async function checkBreach(password, target) {
        if (!password) {
            target.textContent = '';
            return;
        }
        if (!window.crypto || !window.crypto.subtle) {
            target.textContent = 'Breach check unavailable';
            return;
        }
        const bytes = new TextEncoder().encode(password);
        const digest = await crypto.subtle.digest('SHA-1', bytes);
        const hash = Array.from(new Uint8Array(digest))
            .map(byte => byte.toString(16).padStart(2, '0')).join('').toUpperCase();
        const response = await fetch('https://api.pwnedpasswords.com/range/' + hash.slice(0, 5), {
            headers: { 'Add-Padding': 'true' }
        });
        if (!response.ok) throw new Error('Breach check failed');
        const suffix = hash.slice(5);
        const match = (await response.text()).split(/\r?\n/).find(line => line.split(':')[0] === suffix);
        target.textContent = match ? 'Found in breach data — choose another.' : 'Not found in known breaches.';
        target.className = match ? 'text-danger text-end' : 'text-success text-end';
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-password-toggle]').forEach(button => {
            button.addEventListener('click', () => setVisibility(button));
        });

        const input = document.querySelector('[data-password-meter]');
        const password = document.querySelector('.password-strength-input');
        const label = document.querySelector('[data-password-strength]');
        const breach = document.querySelector('[data-password-breach]');
        if (!password || !input || !label) return;

        let timer;
        password.addEventListener('input', function () {
            const score = passwordScore(password.value);
            input.style.width = (score * 25) + '%';
            input.dataset.score = score;
            label.textContent = ['Too weak', 'Weak', 'Fair', 'Good', 'Strong'][score];
            label.className = score >= 3 ? 'text-success' : score >= 2 ? 'text-warning' : 'text-danger';
            clearTimeout(timer);
            timer = setTimeout(() => checkBreach(password.value, breach).catch(() => {
                breach.textContent = 'Breach check unavailable';
                breach.className = 'text-muted text-end';
            }), 450);
        });
    });
})();
