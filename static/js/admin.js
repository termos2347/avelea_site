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
        bar.classList.add('is-active');
        bar.style.width = '20%';
        setTimeout(() => { bar.style.width = '70%'; }, 120);
    });

    document.body.addEventListener('htmx:afterRequest', () => {
        const bar = document.getElementById('htmx-progress');
        if (!bar) return;
        bar.style.width = '100%';
        hideTimer = setTimeout(() => {
            bar.classList.remove('is-active');
            setTimeout(() => { bar.style.width = '0'; }, 200);
        }, 150);
    });

    document.body.addEventListener('htmx:beforeSwap', (e) => {
        const s = e.detail.xhr.status;
        if (s === 401 || s === 403) {
            e.detail.shouldSwap = true;
            e.detail.isError = false;
        }
    });

    document.body.addEventListener('htmx:afterSettle', () => {
        window.scrollTo({ top: 0, behavior: 'instant' });
    });

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

    // ============================================================
    // МОДАЛЫ
    // ============================================================
    function getScrollbarWidth() {
        return window.innerWidth - document.documentElement.clientWidth;
    }

    function openModal(el, focusSelector) {
        if (!el) return;
        const sbw = getScrollbarWidth();
        if (sbw > 0) {
            document.body.style.paddingRight = sbw + 'px';
        }
        document.body.classList.add('adm-modal-open');
        el.classList.add('is-open');
        if (focusSelector) {
            setTimeout(() => {
                const input = el.querySelector(focusSelector);
                if (input) input.focus();
            }, 60);
        }
    }

    function closeModal(el) {
        if (!el) return;
        el.classList.remove('is-open');
        const anyOpen = document.querySelector('.adm-modal.is-open');
        if (!anyOpen) {
            document.body.classList.remove('adm-modal-open');
            document.body.style.paddingRight = '';
        }
    }

    function closeAllModals() {
        document.querySelectorAll('.adm-modal.is-open').forEach((m) => {
            m.classList.remove('is-open');
        });
        document.body.classList.remove('adm-modal-open');
        document.body.style.paddingRight = '';
    }

    document.addEventListener('click', (e) => {
        const backdrop = e.target.closest('[data-modal-close]');
        if (!backdrop) return;
        closeModal(document.getElementById(backdrop.dataset.modalClose));
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeAllModals();
    });

    // ===== Делегирование кликов по data-action =====
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        switch (btn.dataset.action) {
            case 'open-product-dialog':
                openModal(document.getElementById('create-product-dialog'), 'input[name="name"]');
                break;
            case 'close-product-dialog':
                closeModal(document.getElementById('create-product-dialog'));
                break;
            case 'open-create-dialog':
                openModal(document.getElementById('create-dialog'), '#create-name');
                break;
            case 'close-create-dialog':
                closeModal(document.getElementById('create-dialog'));
                break;
            case 'open-info':
                openInfoDialog(btn);
                break;
            case 'open-edit-brand':
                openEditDialog(
                    '/admin/brands/' + btn.dataset.editId + '/edit',
                    btn.dataset.editName,
                    'Редактировать бренд'
                );
                break;
            case 'open-edit-category':
                openEditDialog(
                    '/admin/categories/' + btn.dataset.editId + '/edit',
                    btn.dataset.editName,
                    'Редактировать категорию'
                );
                break;
            case 'close-edit-dialog':
                closeModal(document.getElementById('edit-dialog'));
                break;
        }
    });

    // ===== Редактирование (общий диалог) =====
    function openEditDialog(actionUrl, name, title) {
        const dlg = document.getElementById('edit-dialog');
        if (!dlg) return;
        document.getElementById('edit-title').textContent = title;
        document.getElementById('edit-form').action = actionUrl;
        document.getElementById('edit-name').value = name;
        openModal(dlg, '#edit-name');
    }

    // ===== Info-модалка =====
    function openInfoDialog(btn) {
        const d = btn.dataset;
        const el = document.getElementById('info-dialog');
        if (!el) return;

        const imgEl = document.getElementById('info-image');
        if (d.infoImage) {
            imgEl.innerHTML = '<img src="' + d.infoImage + '" alt="" style="width:100%;height:100%;object-fit:cover;display:block;">';
        } else {
            imgEl.textContent = (d.infoName || '—').slice(0, 2).toUpperCase();
        }

        document.getElementById('info-name').textContent  = d.infoName || '—';
        document.getElementById('info-price').textContent = (d.infoPrice || '0') + ' ₽';

        const tagsEl = document.getElementById('info-tags');
        tagsEl.innerHTML = '';
        (d.infoCats || '').split(',').map(s => s.trim()).filter(Boolean).forEach(c => {
            const t = document.createElement('span');
            t.className = 'adm-tag';
            t.textContent = c;
            tagsEl.appendChild(t);
        });
        if (d.infoPopular === '1') {
            const t = document.createElement('span');
            t.className = 'adm-tag adm-tag-accent';
            t.textContent = 'популярное';
            tagsEl.appendChild(t);
        }

        const rows = document.getElementById('info-rows');
        rows.innerHTML = '';
        const addRow = (label, value) => {
            if (value === undefined || value === null || value === '') return;
            const dt = document.createElement('dt'); dt.textContent = label;
            const dd = document.createElement('dd'); dd.textContent = value;
            rows.appendChild(dt); rows.appendChild(dd);
        };
        addRow('ID', d.infoId);
        addRow('Бренд', d.infoBrand);
        addRow('Объём', d.infoVolume);
        addRow('Описание', d.infoDesc);

        document.getElementById('info-edit-link').href = '/admin/products/' + d.infoId + '/edit';

        openModal(el);
    }

    document.addEventListener('click', (e) => {
        if (e.target.closest('#info-close'))  { closeModal(document.getElementById('info-dialog')); return; }
        if (e.target.closest('#info-cancel')) { closeModal(document.getElementById('info-dialog')); return; }
    });

    // ============================================================
    // ДИАЛОГ ПОДТВЕРЖДЕНИЯ
    // ============================================================
    let pendingForm = null;

    function openConfirm(message, form) {
        pendingForm = form;

        document.getElementById('confirm-title').textContent = 'Подтвердите действие';
        document.getElementById('confirm-text').textContent  = message;

        const okBtn = document.getElementById('confirm-ok');
        const isDanger = /удал/i.test(message);
        okBtn.textContent = isDanger ? 'Удалить' : 'Подтвердить';
        okBtn.className = isDanger
            ? 'adm-btn adm-btn-danger-solid'
            : 'adm-btn adm-btn-primary';

        openModal(document.getElementById('confirm-dialog'));
    }

    function closeConfirm() {
        closeModal(document.getElementById('confirm-dialog'));
        pendingForm = null;
    }

    document.addEventListener('click', (e) => {
        if (e.target.closest('#confirm-cancel')) { closeConfirm(); return; }
        if (e.target.closest('#confirm-ok')) {
            const form = pendingForm;
            closeConfirm();
            if (form) {
                form.dataset.confirmed = '1';
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            }
        }
    });

    document.addEventListener('submit', (e) => {
        const form = e.target;
        const msg = form.dataset && form.dataset.confirm;
        if (!msg) return;
        if (form.dataset.confirmed === '1') {
            delete form.dataset.confirmed;
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        openConfirm(msg, form);
    }, true);

    // ============================================================
    // ЖИВОЙ ФИЛЬТР СТРОК
    // ------------------------------------------------------------
    // Работает одинаково для Товаров, Брендов и Категорий.
    //
    // Логика подбора для одной строки:
    //   1) если запрос — целое число, И у строки есть data-id,
    //      совпадающий с этим числом → строка подходит (поиск по ID);
    //   2) иначе проверяем, что data-name содержит запрос (подстрока).
    //
    // То есть ввод «1» найдёт:
    //   - товар с id=1 (точное совпадение),
    //   - все товары, у которых «1» встречается в названии.
    // Ввод «крем» найдёт все товары со словом «крем» в названии.
    //
    // На каждый ввод символа, без Enter. Показ кнопки очистки — CSS.
    // ============================================================
    function runRowFilter(input) {
        const q = input.value.trim().toLowerCase();
        const isNumeric = /^\d+$/.test(q);

        const rows = document.querySelectorAll('.row-item');
        let visible = 0;

        rows.forEach(r => {
            const name = r.dataset.name || '';
            const id   = r.dataset.id   || '';

            const match = !q
                || (isNumeric && id === q)   // «1» → id=1
                || name.includes(q);          // подстрока по имени

            r.style.display = match ? '' : 'none';
            if (match) visible++;
        });

        const no = document.getElementById('no-results');
        if (no) no.style.display = visible > 0 ? 'none' : 'block';
    }

    document.addEventListener('input', (e) => {
        const input = e.target.closest('input[data-action="filter-rows"]');
        if (!input) return;
        runRowFilter(input);
    });

    // ===== Кнопка очистки =====
    document.addEventListener('click', (e) => {
        const clearBtn = e.target.closest('[data-search-clear]');
        if (!clearBtn) return;
        const searchBox = clearBtn.closest('.adm-search');
        const input = searchBox && searchBox.querySelector('input');
        if (input) {
            input.value = '';
            runRowFilter(input);
            input.focus();
        }
    });
})();