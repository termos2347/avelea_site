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
            return;
        }
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
    // ПЕРЕКЛЮЧАТЕЛЬ ВИДОВ ТОВАРОВ (таблица / карточки)
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
    // ============================================================
    document.body.addEventListener('htmx:afterSwap', (e) => {
        if (e.detail.target && e.detail.target.id === 'edit-product-dialog-content') {
            openModal(document.getElementById('edit-product-dialog'), 'input[name="name"]');
            initFormSections();
            updateCategoriesCount(document.getElementById('edit-product-dialog'));
        }
    });

    function openEditDialog(actionUrl, name, title) {
        const dlg = document.getElementById('edit-dialog');
        if (!dlg) return;
        document.getElementById('edit-title').textContent = title;

        const form = document.getElementById('edit-form');
        form.action = actionUrl;
        form.setAttribute('action', actionUrl);

        document.getElementById('edit-name').value = name;
        openModal(dlg, '#edit-name');
    }

    // ============================================================
    // INFO-модалка с предпросмотром
    // ============================================================
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

        document.getElementById('info-site-link').href = '/product/' + d.infoId;

        const editBtn = document.getElementById('info-edit-btn');
        editBtn.href = '/admin/products/' + d.infoId + '/edit';
        editBtn.setAttribute('hx-get', '/admin/products/' + d.infoId + '/edit');
        if (window.htmx) htmx.process(editBtn);

        openModal(el);
    }

    document.addEventListener('click', (e) => {
        if (e.target.closest('#info-close'))  { closeModal(document.getElementById('info-dialog')); return; }
        if (e.target.closest('#info-cancel')) { closeModal(document.getElementById('info-dialog')); return; }
        if (e.target.closest('#info-edit-btn')) {
            closeModal(document.getElementById('info-dialog'));
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
    // ОБЯЗАТЕЛЬНЫЕ ПОЛЯ ФОРМЫ ТОВАРА
    // ============================================================
    document.addEventListener('submit', (e) => {
        const form = e.target;
        if (!form.querySelector('input[name="categories"]')) return;

        const anyCat = form.querySelectorAll('input[name="categories"]:checked').length > 0;
        if (!anyCat) {
            e.preventDefault();
            e.stopPropagation();
            const group = form.querySelector('[data-categories-group]');
            const error = form.querySelector('[data-categories-error]');
            if (group) group.classList.add('is-error');
            if (error) error.classList.add('is-visible');
            if (group) group.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }

        const brandRadios = form.querySelectorAll('input[name="brand_id"]');
        if (brandRadios.length > 0) {
            const anyBrand = form.querySelectorAll('input[name="brand_id"]:checked').length > 0;
            if (!anyBrand) {
                e.preventDefault();
                e.stopPropagation();
                const group = form.querySelector('[data-brands-group]');
                const error = form.querySelector('[data-brands-error]');
                if (group) group.classList.add('is-error');
                if (error) error.classList.add('is-visible');
                if (group) group.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return;
            }
        }
    }, true);

    // ============================================================
    // ЖИВОЙ ФИЛЬТР СПИСКОВ (Товары / Бренды / Категории)
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

    // Debounce: при быстром наборе не гоняем фильтр на каждую букву.
    // 150 мс — практически незаметно, но заметно экономит работу
    // браузера на длинных списках (сотни строк).
    let rowFilterTimer = null;
    document.addEventListener('input', (e) => {
        const input = e.target.closest('input[data-action="filter-rows"]');
        if (!input) return;
        clearTimeout(rowFilterTimer);
        rowFilterTimer = setTimeout(() => runRowFilter(input), 150);
    });

    // Кнопка «очистить» работает мгновенно — ждать там нечего.
    document.addEventListener('click', (e) => {
        const clearBtn = e.target.closest('[data-search-clear]');
        if (!clearBtn) return;
        const searchBox = clearBtn.closest('.adm-search');
        const input = searchBox && searchBox.querySelector('input');
        if (input) {
            input.value = '';
            clearTimeout(rowFilterTimer);
            runRowFilter(input);
            input.focus();
        }
    });

    // ============================================================
    // ФОРМА ТОВАРА: единицы объёма, сворачивание, поиск, счётчик
    // ============================================================

    // ---- Переключатель мл / г ----
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.adm-unit-switch button');
        if (!btn) return;
        const wrap = btn.closest('.adm-unit-switch');
        const row = wrap.closest('.adm-volume-row');
        const input = row && row.querySelector('[data-unit-input]');
        if (!input) return;
        input.value = btn.dataset.unit;
        wrap.querySelectorAll('button').forEach(b =>
            b.classList.toggle('is-active', b === btn));
    });

    // ---- Сворачивание секций (Категории / Бренд) ----
    function findCollapseTarget(btn) {
        const id = btn.dataset.collapseTarget;
        if (!id) return null;

        const form = btn.closest('form');
        if (form) {
            const inForm = form.querySelector('[id="' + id + '"]');
            if (inForm) return inForm;
        }
        return document.getElementById(id);
    }

    function setCollapsed(target, btn, collapsed, instant) {
        if (!target) return;

        target.classList.toggle('is-collapsed', collapsed);
        if (btn) btn.setAttribute('aria-expanded', String(!collapsed));

        if (instant) {
            target.style.transition = 'none';
            target.style.maxHeight = collapsed ? '0px' : '';
            void target.offsetHeight;
            target.style.transition = '';
            return;
        }

        if (collapsed) {
            target.style.maxHeight = target.scrollHeight + 'px';
            void target.offsetHeight;
            target.style.maxHeight = '0px';
        } else {
            target.style.maxHeight = target.scrollHeight + 'px';

            const done = (ev) => {
                if (ev.propertyName !== 'max-height') return;
                target.removeEventListener('transitionend', done);
                if (!target.classList.contains('is-collapsed')) {
                    target.style.maxHeight = '';
                }
            };
            target.addEventListener('transitionend', done);
        }
    }

    function applyCollapseState(btn) {
        const target = findCollapseTarget(btn);
        if (!target) return;

        const key = btn.dataset.collapseKey;
        let collapsed = false;
        try { collapsed = localStorage.getItem(key) === '1'; } catch (err) {}

        setCollapsed(target, btn, collapsed, true);
    }

    function initFormSections() {
        document.querySelectorAll('.adm-collapse-btn[data-collapse-target]').forEach(applyCollapseState);
    }
    initFormSections();

    document.body.addEventListener('htmx:afterSwap', initFormSections);

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.adm-collapse-btn');
        if (!btn) return;
        e.preventDefault();

        const target = findCollapseTarget(btn);
        if (!target) return;

        const nowCollapsed = !target.classList.contains('is-collapsed');
        setCollapsed(target, btn, nowCollapsed);

        try { localStorage.setItem(btn.dataset.collapseKey, nowCollapsed ? '1' : '0'); } catch (err) {}
    });

    // ---- Поиск внутри чип-групп ----
    document.addEventListener('input', (e) => {
        const input = e.target.closest('[data-filter-target]');
        if (!input) return;
        const container = input.closest('.adm-section');
        if (!container) return;
        const q = input.value.trim().toLowerCase();
        container.querySelectorAll('[data-filter-item]').forEach(it => {
            const name = it.dataset.name || '';
            it.style.display = (!q || name.includes(q)) ? '' : 'none';
        });
    });

    // ---- Счётчик выбранных категорий ----
    function updateCategoriesCount(scope) {
        const root = scope || document;
        root.querySelectorAll('form').forEach(form => {
            const el = form.querySelector('[data-count-for="categories"]');
            if (!el) return;
            const n = form.querySelectorAll('input[name="categories"]:checked').length;
            el.textContent = n > 0 ? n : '';
        });
    }
    updateCategoriesCount();

    document.addEventListener('change', (e) => {
        const form = e.target.closest('form');
        if (!form) return;

        if (e.target.matches('input[name="categories"]')) {
            const group = form.querySelector('[data-categories-group]');
            const error = form.querySelector('[data-categories-error]');
            if (group) group.classList.remove('is-error');
            if (error) error.classList.remove('is-visible');
            updateCategoriesCount(form);
        }
        if (e.target.matches('input[name="brand_id"]')) {
            const group = form.querySelector('[data-brands-group]');
            const error = form.querySelector('[data-brands-error]');
            if (group) group.classList.remove('is-error');
            if (error) error.classList.remove('is-visible');
        }
    });

    // ============================================================
    // ПОЛНОЭКРАННЫЙ ИНДИКАТОР СОХРАНЕНИЯ ТОВАРА
    // ============================================================
    (function () {
        const overlay = document.getElementById('adm-saving-overlay');
        const textEl  = document.getElementById('adm-saving-text');
        if (!overlay) return;

        let hideTimer = null;

        function isProductForm(form) {
            if (!form || form.tagName !== 'FORM') return false;
            return !!(form.querySelector('input[name="name"]')
                   && form.querySelector('input[name="price"]'));
        }

        function show(message) {
            if (textEl) textEl.textContent = message || 'Сохраняем…';
            overlay.classList.add('is-visible');
            overlay.setAttribute('aria-hidden', 'false');

            clearTimeout(hideTimer);
            hideTimer = setTimeout(hide, 15000);
        }

        function hide() {
            clearTimeout(hideTimer);
            overlay.classList.remove('is-visible');
            overlay.setAttribute('aria-hidden', 'true');
        }

        document.addEventListener('click', (e) => {
            const btn = e.target.closest('button[type="submit"], input[type="submit"]');
            if (!btn) return;
            const form = btn.closest('form');
            if (!isProductForm(form)) return;

            if (typeof form.checkValidity === 'function' && !form.checkValidity()) {
                return;
            }

            const action = form.getAttribute('action') || '';
            let msg = 'Сохраняем…';
            if (/\/new\b/.test(action) || action.endsWith('/new')) {
                msg = 'Товар создаётся…';
            } else if (/\/edit\b/.test(action) || action.endsWith('/edit')) {
                msg = 'Изменения сохраняются…';
            }

            show(msg);
        }, true);

        document.body.addEventListener('htmx:afterRequest', (e) => {
            const elt = e.detail && e.detail.elt;
            let form = null;
            if (elt) {
                form = elt.tagName === 'FORM' ? elt : (elt.closest && elt.closest('form'));
            }
            if (isProductForm(form)) hide();
        });

        document.body.addEventListener('htmx:responseError', (e) => {
            const elt = e.detail && e.detail.elt;
            let form = null;
            if (elt) {
                form = elt.tagName === 'FORM' ? elt : (elt.closest && elt.closest('form'));
            }
            if (isProductForm(form)) hide();
        });

        window.addEventListener('beforeunload', hide);

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') hide();
        });
    })();

})();