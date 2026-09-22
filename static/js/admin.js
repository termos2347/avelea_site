(function () {
    'use strict';
    if (window.__avelea_admin_init) return;
    window.__avelea_admin_init = true;

    let hideTimer = null;

    // ===== HTMX: прогресс-бар =====
    document.body.addEventListener('htmx:beforeRequest', () => {
        const bar = document.getElementById('htmx-progress');
        if (!bar) return;
        clearTimeout(hideTimer);
        bar.classList.remove('opacity-0');
        bar.style.width = '20%';
        setTimeout(() => { bar.style.width = '70%'; }, 120);
    });

    document.body.addEventListener('htmx:afterRequest', () => {
        const bar = document.getElementById('htmx-progress');
        if (!bar) return;
        bar.style.width = '100%';
        hideTimer = setTimeout(() => {
            bar.classList.add('opacity-0');
            setTimeout(() => { bar.style.width = '0'; }, 200);
        }, 150);
    });

    // ===== HTMX: разрешаем свап 401/403 (неверный пароль, CSRF) =====
    document.body.addEventListener('htmx:beforeSwap', (e) => {
        const s = e.detail.xhr.status;
        if (s === 401 || s === 403) {
            e.detail.shouldSwap = true;
            e.detail.isError = false;
        }
    });

    // ===== Скролл наверх после смены страницы =====
    document.body.addEventListener('htmx:afterSettle', () => {
        window.scrollTo({ top: 0, behavior: 'instant' });
    });

    // ===== Не дёргать запрос по клику на активную ссылку =====
    document.addEventListener('click', (e) => {
        const a = e.target.closest('a[href]');
        if (!a) return;
        if (a.getAttribute('hx-boost') === 'false') return;
        const href = a.getAttribute('href');
        if (!href || href.startsWith('http') || href.startsWith('#')) return;
        if (href === window.location.pathname + window.location.search) {
            e.preventDefault();
        }
    });

    // ===== Диалоги =====
    function openDialog(id, focusSelector) {
        const dlg = document.getElementById(id);
        if (!dlg) return;
        dlg.showModal();
        if (focusSelector) {
            setTimeout(() => {
                const el = dlg.querySelector(focusSelector);
                if (el) el.focus();
            }, 0);
        }
    }

    function closeDialog(id) {
        const dlg = document.getElementById(id);
        if (dlg) dlg.close();
    }

    // ===== Делегирование кликов по data-action =====
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        switch (btn.dataset.action) {
            case 'open-product-dialog':
                openDialog('create-product-dialog', 'input[name="name"]');
                break;
            case 'close-product-dialog':
                closeDialog('create-product-dialog');
                break;
            case 'open-create-dialog':
                openDialog('create-dialog', '#create-name');
                break;
            case 'close-create-dialog':
                closeDialog('create-dialog');
                break;
        }
    });

    // ===== Живой фильтр строк в таблицах =====
    document.addEventListener('input', (e) => {
        const input = e.target.closest('input[data-action="filter-rows"]');
        if (!input) return;
        const q = input.value.trim().toLowerCase();
        const rows = document.querySelectorAll('.row-item');
        let visible = 0;
        rows.forEach(r => {
            const match = !q || (r.dataset.name || '').includes(q);
            r.style.display = match ? '' : 'none';
            if (match) visible++;
        });
        const no = document.getElementById('no-results');
        if (no) no.classList.toggle('hidden', visible > 0);
    });
})();