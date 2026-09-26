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

    // ============================================================
    // htMX: beforeSwap — закрываем модалы на успех,
    // пропускаем 401/403 для показа ошибок.
    // ============================================================
    document.body.addEventListener('htmx:beforeSwap', (e) => {
        const s = e.detail.xhr.status;

        // Ошибки авторизации пропускаем как обычный ответ,
        // чтобы показать их пользователю.
        if (s === 401 || s === 403) {
            e.detail.shouldSwap = true;
            e.detail.isError = false;
            return;
        }

        // Успешный ответ (200 или 2xx после редиректа) — свап
        // страницы, все открытые модалы закрываем.
        if (s >= 200 && s < 400) {
            closeAllModals();
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
    // ПЕРЕКЛЮЧАТЕЛЬ ВИДОВ ТОВАРОВ
    // ============================================================
    const VIEW_KEY = 'adm_products_view';

    function getSavedView() {
        try {
            const v = localStorage.getItem(VIEW_KEY);
            return (v === 'cards' || v === 'table') ? v : 'table';
        } catch (e) {
            return 'table';
        }
    }

    function applyView(view) {
        document.body.dataset.productsView = view;
        document.querySelectorAll('[data-products-view]').forEach(btn => {
            btn.classList.toggle('is-active', btn.dataset.productsView === view);
        });
    }

    applyView(getSavedView());

    document.body.addEventListener('htmx:afterSettle', () => {
        applyView(document.body.dataset.productsView || getSavedView());
    });

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-products-view]');
        if (!btn) return;
        const view = btn.dataset.productsView;
        try { localStorage.setItem(VIEW_KEY, view); } catch (err) {}
        applyView(view);
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
            case 'close-edit-product-dialog':
                closeModal(document.getElementById('edit-product-dialog'));
                break;
            case 'close-current-modal': {
                const modal = btn.closest('.adm-modal');
                if (modal) closeModal(modal);
                break;
            }
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

    // ============================================================
    // ПОДГРУЗКА ФОРМЫ РЕДАКТИРОВАНИЯ ТОВАРА В МОДАЛКУ
    // ------------------------------------------------------------
    // Кнопка «Редактировать» — это <a href=".../edit" hx-get=".../edit">.
    // HTMX подгружает партиал _product_form.html в
    // #edit-product-dialog-content. После подмены контента —
    // открываем модалку.
    // ============================================================
    document.body.addEventListener('htmx:afterSwap', (e) => {
        if (e.detail.target && e.detail.target.id === 'edit-product-dialog-content') {
            openModal(document.getElementById('edit-product-dialog'), 'input[name="name"]');
        }
    });

    // ===== Редактирование бренда/категории (общий диалог) =====
    function openEditDialog(actionUrl, name, title) {
        const dlg = document.getElementById('edit-dialog');
        if (!dlg) return;
        document.getElementById('edit-title').textContent = title;
        document.getElementById('edit-form').action = actionUrl;
        document.getElementById('edit-name').value = name;
        openModal(dlg, '#edit-name');
    }

    // ===== Info-модалка =====
        // ============================================================
    // INFO-модалка с предпросмотром карточки
    // ------------------------------------------------------------
    // Левая колонка — метаданные (заполняется из data-info-*).
    // Правая колонка — карточка в стиле сайта, тоже из data-атрибутов.
    // ============================================================
    function openInfoDialog(btn) {
        const d = btn.dataset;
        const el = document.getElementById('info-dialog');
        if (!el) return;

        // ---------- Левая колонка: метаданные ----------
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

        // ---------- Правая колонка: превью карточки ----------
        const previewImg = document.getElementById('info-preview-img');
        const previewInitials = document.getElementById('info-preview-initials');

        if (d.infoImage) {
            previewImg.src = d.infoImage;
            previewImg.style.display = 'block';
            previewInitials.style.display = 'none';
        } else {
            previewImg.src = '';
            previewImg.style.display = 'none';
            previewInitials.style.display = '';
            previewInitials.textContent = (d.infoName || '—').slice(0, 2).toUpperCase();
        }

        document.getElementById('info-preview-name').textContent  = d.infoName || '—';
        document.getElementById('info-preview-cats').textContent  = d.infoCats || '—';
        document.getElementById('info-preview-price').textContent = (d.infoPrice || '0') + ' ₽';

        // Превью-карточка теперь не ссылка — открытие сайта только кнопкой в футере.
        document.getElementById('info-site-link').href = '/product/' + d.infoId;

        // ---------- Кнопка «Редактировать» ----------
        // hx-get на форму редактирования — она подгрузится в edit-модалку.
        const editBtn = document.getElementById('info-edit-btn');
        editBtn.href = '/admin/products/' + d.infoId + '/edit';
        editBtn.setAttribute('hx-get', '/admin/products/' + d.infoId + '/edit');
        // Пересобираем htmx-атрибут, чтобы htmx «увидел» новый URL.
        if (window.htmx) htmx.process(editBtn);

        openModal(el);
    }

    document.addEventListener('click', (e) => {
        if (e.target.closest('#info-close'))  { closeModal(document.getElementById('info-dialog')); return; }
        if (e.target.closest('#info-cancel')) { closeModal(document.getElementById('info-dialog')); return; }

        if (e.target.closest('#info-edit-btn')) {
            closeModal(document.getElementById('info-dialog'));
            // Не preventDefault — пусть htmx сделает hx-get
        }
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
    // ЖИВОЙ ФИЛЬТР
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
                || (isNumeric && id === q)
                || name.includes(q);
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