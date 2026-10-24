(function () {
    'use strict';
    if (window.__avelea_admin_init) return;
    window.__avelea_admin_init = true;

    let hideTimer = null;

    // ============================================================
    // SCROLL-REVEAL: товары плавно появляются/затухают при скролле
    // ============================================================
    let scrollObserver = null;

    function initScrollAnimations() {
        document.body.classList.add('scroll-anim-ready');

        if (scrollObserver) {
            scrollObserver.disconnect();
        }

        scrollObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-visible');
                } else {
                    entry.target.classList.remove('is-visible');
                }
            });
        }, {
            rootMargin: '-10% 0px -10% 0px',
            threshold: 0,
        });

        const deadTop    = window.innerHeight * 0.1;
        const deadBottom = window.innerHeight * 0.9;

        document.querySelectorAll('.row-item, .adm-product-card').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.bottom > deadTop && r.top < deadBottom) {
                el.classList.add('is-visible');
            }
            scrollObserver.observe(el);
        });
    }

    function refreshScrollObserver() {
        if (!scrollObserver) return;
        document.querySelectorAll('.row-item, .adm-product-card').forEach(el => {
            scrollObserver.observe(el);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initScrollAnimations);
    } else {
        initScrollAnimations();
    }

    let _lastUrl = window.location.href;
    document.body.addEventListener('htmx:afterSettle', () => {
        if (window.location.href !== _lastUrl) {
            _lastUrl = window.location.href;
            initScrollAnimations();
        }
    });

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
            case 'open-create-dialog': {
                // Сбрасываем прошлое состояние (бренд или категория).
                const createName = document.getElementById('create-name');
                if (createName) {
                    createName.value = '';
                    createName.setCustomValidity('');
                    createName.dispatchEvent(new Event('input', { bubbles: true }));
                }
                openModal(document.getElementById('create-dialog'), '#create-name');
                break;
            }
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
                    btn.dataset.editDescription || '',
                    'Редактировать бренд'
                );
                break;
            case 'open-edit-category':
                openEditDialog(
                    '/admin/categories/' + btn.dataset.editId + '/edit',
                    btn.dataset.editName,
                    '',
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

    function openEditDialog(actionUrl, name, description, title) {
        const dlg = document.getElementById('edit-dialog');
        if (!dlg) return;
        document.getElementById('edit-title').textContent = title;

        const form = document.getElementById('edit-form');
        form.action = actionUrl;
        form.setAttribute('action', actionUrl);

        const nameInput = document.getElementById('edit-name');
        nameInput.value = name;
        nameInput.setCustomValidity('');

        const isBrand = title.toLowerCase().indexOf('бренд') !== -1;
        const nameErr = form.querySelector('[data-brand-name-error]');
        const submit = form.querySelector('button[type="submit"]');

        if (isBrand) {
            // Включаем live-валидацию только для брендов.
            nameInput.setAttribute('data-brand-name', '');
        } else {
            nameInput.removeAttribute('data-brand-name');
            if (nameErr) nameErr.classList.remove('is-visible');
            if (submit) submit.disabled = false;
        }

        const descField = document.getElementById('edit-description');
        const descWrap = document.getElementById('edit-description-wrap');
        if (descField && descWrap) {
            if (isBrand) {
                descWrap.style.display = '';
                descField.value = description || '';
            } else {
                descWrap.style.display = 'none';
                descField.value = '';
            }
        }

        openModal(dlg, '#edit-name');

        if (isBrand) {
            // Проверить текущее значение (вдруг name уже с кириллицей).
            nameInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
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
    let pendingConfirmForm = null;

    function openConfirm(message, form) {
        pendingConfirmForm = form;

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
        pendingConfirmForm = null;
    }

    document.addEventListener('click', (e) => {
        if (e.target.closest('#confirm-cancel')) { closeConfirm(); return; }
        if (e.target.closest('#confirm-ok')) {
            const form = pendingConfirmForm;
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
    // ЖИВОЙ ФИЛЬТР СПИСКОВ
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

    let rowFilterTimer = null;
    document.addEventListener('input', (e) => {
        const input = e.target.closest('input[data-action="filter-rows"]');
        if (!input) return;
        clearTimeout(rowFilterTimer);
        rowFilterTimer = setTimeout(() => runRowFilter(input), 150);
    });

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
    // СЛОТЫ МЕДИА: превью (картинка или видео) + удаление
    // ============================================================
    (function initImageSlots() {

        function isVideoFile(name) {
            return /\.(mp4|webm|mov|m4v)$/i.test(name || '');
        }

        function makePreview(fileName, url) {
            if (isVideoFile(fileName)) {
                var v = document.createElement('video');
                v.className = 'adm-image-preview';
                v.src = url;
                v.muted = true;
                v.playsInline = true;
                v.autoplay = true;
                v.loop = true;
                return v;
            }
            var img = document.createElement('img');
            img.className = 'adm-image-preview';
            img.src = url;
            img.alt = '';
            return img;
        }

        function updateRemoveButton(slot) {
            var btn = slot.querySelector('[data-remove-image]');
            var label = slot.querySelector('.adm-image-uploader');
            var input = slot.querySelector('.adm-file-input');
            var cb = slot.querySelector('.adm-remove-checkbox');

            if (!btn || !label || !input) return;

            var hasFile = input.files && input.files.length > 0;
            var hasSaved = label.classList.contains('has-image');
            var marked = cb && cb.checked;

            btn.style.display = ((hasFile || hasSaved) && !marked) ? '' : 'none';
        }

        function resetSlotToEmpty(slot) {
            var label = slot.querySelector('.adm-image-uploader');
            var input = slot.querySelector('.adm-file-input');
            var preview = slot.querySelector('.adm-image-preview');
            var overlay = slot.querySelector('.adm-image-overlay');
            var empty = slot.querySelector('.adm-image-empty');

            if (input) input.value = '';
            if (preview) preview.remove();
            if (overlay) overlay.remove();

            if (!empty) {
                empty = document.createElement('div');
                empty.className = 'adm-image-empty';
                empty.innerHTML =
                    '<i class="fas fa-photo-film"></i>' +
                    '<span class="adm-file-text">Загрузить</span>';
                label.insertBefore(empty, input);
            } else {
                var t = empty.querySelector('.adm-file-text');
                if (t) t.textContent = 'Загрузить';
            }

            label.classList.remove('has-image');
        }

        document.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-remove-image]');
            if (!btn) return;

            e.preventDefault();
            e.stopPropagation();

            var slot = btn.closest('.adm-image-slot');
            if (!slot) return;

            var cb = slot.querySelector('.adm-remove-checkbox');
            if (cb && !cb.checked) cb.checked = true;

            resetSlotToEmpty(slot);
            updateRemoveButton(slot);
        });

        document.addEventListener('change', function (e) {
            if (!e.target.matches('.adm-file-input')) return;

            var label = e.target.closest('.adm-image-uploader');
            if (!label) return;
            var slot = label.closest('.adm-image-slot');
            if (!slot) return;

            var file = e.target.files && e.target.files[0];
            if (!file) return;

            var url = URL.createObjectURL(file);

            var cb = slot.querySelector('.adm-remove-checkbox');
            if (cb) cb.checked = false;

            var old = label.querySelector('.adm-image-preview');
            if (old) old.remove();

            var preview = makePreview(file.name, url);
            var input = label.querySelector('.adm-file-input');
            label.insertBefore(preview, input);

            var empty = label.querySelector('.adm-image-empty');
            if (empty) empty.remove();

            if (!label.querySelector('.adm-image-overlay')) {
                var overlay = document.createElement('div');
                overlay.className = 'adm-image-overlay';
                overlay.innerHTML =
                    '<i class="fas fa-cloud-arrow-up"></i>' +
                    '<span class="adm-file-text">Заменить</span>';
                label.insertBefore(overlay, input);
            }

            label.classList.add('has-image');
            updateRemoveButton(slot);
        });

        document.querySelectorAll('.adm-image-slot').forEach(updateRemoveButton);

        document.body.addEventListener('htmx:afterSwap', function () {
            document.querySelectorAll('.adm-image-slot').forEach(updateRemoveButton);
        });

    })();

    // ============================================================
    // ВАРИАНТЫ ТОВАРА: добавить/удалить строку
    // ============================================================
    (function initVariants() {

        function makeRow() {
            var row = document.createElement('div');
            row.className = 'adm-variant-row';
            row.innerHTML =
                '<input type="number" name="variant_volume_amount" step="0.1" min="0" ' +
                    'class="adm-input" placeholder="10">' +
                '<select name="variant_volume_unit" class="adm-select">' +
                    '<option value="мл">мл</option>' +
                    '<option value="г">г</option>' +
                '</select>' +
                '<input type="number" name="variant_price" min="0" ' +
                    'class="adm-input" placeholder="500">' +
                '<button type="button" class="adm-variant-remove" ' +
                    'data-remove-variant aria-label="Удалить вариант">' +
                    '<i class="fas fa-times"></i>' +
                '</button>';
            return row;
        }

        document.addEventListener('click', function (e) {
            if (e.target.closest('[data-add-variant]')) {
                var wrap = e.target.closest('[data-variants]');
                if (!wrap) return;
                var list = wrap.querySelector('[data-variant-rows]');
                if (!list) return;
                if (list.children.length >= 10) return;
                list.appendChild(makeRow());
                return;
            }

            if (e.target.closest('[data-remove-variant]')) {
                var row = e.target.closest('.adm-variant-row');
                if (row) row.remove();
            }
        });

    })();

    // ============================================================
    // ИНДИКАТОР СОХРАНЕНИЯ ТОВАРА
    // ============================================================
    (function () {
        const overlay = document.getElementById('adm-saving-overlay');
        const textEl  = document.getElementById('adm-saving-text');
        if (!overlay) return;

        const SHOW_BEFORE_SUBMIT = 220;

        let hideTimer = null;
        let pendingForm = null;

        function isProductForm(form) {
            if (!form || form.tagName !== 'FORM') return false;
            return !!(form.querySelector('input[name="name"]')
                   && form.querySelector('input[name="price"]'));
        }

        function pickMsg(form) {
            const action = form.getAttribute('action') || '';
            if (/\/new\b/.test(action) || action.endsWith('/new')) {
                return 'Товар создаётся…';
            }
            if (/\/edit\b/.test(action) || action.endsWith('/edit')) {
                return 'Изменения сохраняются…';
            }
            return 'Сохраняем…';
        }

        function show(message) {
            if (textEl) textEl.textContent = message || 'Сохраняем…';

            overlay.classList.remove('is-visible');
            void overlay.offsetHeight;
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

        document.addEventListener('submit', (e) => {
            const form = e.target;
            if (!isProductForm(form)) return;
            if (e.defaultPrevented) return;

            if (typeof form.checkValidity === 'function' && !form.checkValidity()) {
                return;
            }

            if (pendingForm === form) {
                e.preventDefault();
                return;
            }

            e.preventDefault();
            pendingForm = form;

            show(pickMsg(form));

            setTimeout(() => {
                if (pendingForm !== form) return;
                pendingForm = null;
                HTMLFormElement.prototype.submit.call(form);
            }, SHOW_BEFORE_SUBMIT);
        }, true);

        document.body.addEventListener('htmx:afterRequest', hide);
        document.body.addEventListener('htmx:responseError', hide);

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') hide();
        });
    })();

    // ============================================================
    // SITE CONTENT (перенос из site_content.html <script>)
    // ============================================================
    (function initSiteContent() {
        function init() {
            var pages = document.querySelectorAll('.site-page');
            if (!pages.length) return;
            if (pages[0].hasAttribute('data-ready')) return;

            pages.forEach(function (el) {
                el.setAttribute('data-ready', '1');
            });

            var toast = document.getElementById('site-toast');
            var toastTimer = null;

            function showToast(msg, isError) {
                if (!toast) return;
                toast.textContent = msg;
                toast.classList.toggle('is-error', !!isError);
                toast.classList.add('is-visible');
                clearTimeout(toastTimer);
                toastTimer = setTimeout(function () {
                    toast.classList.remove('is-visible');
                }, 3000);
            }

            function getCsrf() {
                var el = document.querySelector('input[name="csrf_token"]');
                return el ? el.value : '';
            }

            function isDirty(root) {
                var input = root.querySelector('[data-text-input]');
                if (!input) return false;
                var original = root.dataset.original || '';
                return input.value !== original;
            }

            function getDirtyCount() {
                return Array.from(document.querySelectorAll('[data-site-text]'))
                    .filter(isDirty).length;
            }

            function updateGlobal() {
                var float = document.querySelector('[data-unsaved-float]');
                if (!float) return;
                var n = getDirtyCount();
                if (n > 0) {
                    float.style.display = '';
                    var c = float.querySelector('[data-count]');
                    if (c) c.textContent = n;
                } else {
                    float.style.display = 'none';
                }
            }

            function updateDirtyState(root) {
                var item = root.closest('.site-item');
                if (!item) return;
                var dirty = isDirty(root);
                item.classList.toggle('is-dirty', dirty);
                var badge = item.querySelector('[data-unsaved-badge]');
                if (badge) badge.style.display = dirty ? '' : 'none';
                updateGlobal();
            }

            document.querySelectorAll('[data-site-text]').forEach(function (root) {
                var input = root.querySelector('[data-text-input]');
                if (!input) return;
                input.addEventListener('input', function () { updateDirtyState(root); });
                updateDirtyState(root);
            });

            function warnIfDirty() {
                var n = getDirtyCount();
                if (n === 0) return true;
                var word = n === 1 ? 'изменение' : (n < 5 ? 'изменения' : 'изменений');
                return confirm('У вас есть несохранённые ' + word + ' (' + n + ').\nПерейти и потерять их?');
            }

            window.addEventListener('beforeunload', function (e) {
                if (getDirtyCount() > 0) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            });

            document.body.addEventListener('htmx:confirm', function (e) {
                if (getDirtyCount() === 0) return;
                if (!warnIfDirty()) {
                    e.preventDefault();
                }
            });

            var STORAGE_PREFIX = 'site_page_open_';

            document.querySelectorAll('.site-page').forEach(function (details) {
                var slug = details.dataset.pageSlug;
                if (!slug) return;

                try {
                    var stored = localStorage.getItem(STORAGE_PREFIX + slug);
                    if (stored === '0') details.open = false;
                    else if (stored === '1') details.open = true;
                } catch (e) {}

                details.addEventListener('toggle', function () {
                    try {
                        localStorage.setItem(STORAGE_PREFIX + slug, details.open ? '1' : '0');
                    } catch (e) {}
                });
            });

            var expandBtn = document.querySelector('[data-expand-all]');
            var collapseBtn = document.querySelector('[data-collapse-all]');

            function setAll(open) {
                document.querySelectorAll('.site-page').forEach(function (d) {
                    d.open = open;
                    try {
                        localStorage.setItem(STORAGE_PREFIX + d.dataset.pageSlug, open ? '1' : '0');
                    } catch (e) {}
                });
            }

            if (expandBtn) expandBtn.addEventListener('click', function () { setAll(true); });
            if (collapseBtn) collapseBtn.addEventListener('click', function () { setAll(false); });

            function renderMeta(root, info) {
                var meta = root.querySelector('[data-meta]');
                if (!meta) return;

                meta.textContent = '';

                if (!info) {
                    meta.textContent = 'jpg, png, gif, webp — до 5 МБ. Автоконвертация в WebP.';
                    return;
                }

                if (info.missing) {
                    var warn = document.createElement('span');
                    warn.style.color = 'var(--adm-danger)';

                    var icon = document.createElement('i');
                    icon.className = 'fas fa-exclamation-triangle';
                    warn.appendChild(icon);

                    warn.appendChild(
                        document.createTextNode(' Файл ' + info.filename + ' отсутствует на диске')
                    );
                    meta.appendChild(warn);
                    return;
                }

                var type = document.createElement('span');
                type.className = 'site-img-meta-type';
                type.textContent = 'WebP';
                meta.appendChild(type);

                meta.appendChild(document.createTextNode(' · ' + info.size_kb + ' KB · '));

                var code = document.createElement('code');
                code.textContent = info.filename;
                meta.appendChild(code);
            }

            function setPreview(root, url, info) {
                var preview = root.querySelector('[data-preview]');
                var overlayText = root.querySelector('[data-overlay-text]');
                var removeBtn = root.querySelector('[data-remove-btn]');

                if (url) {
                    preview.innerHTML = '<img src="' + url + '" alt="">';
                    if (overlayText) overlayText.textContent = 'Заменить';
                    if (removeBtn) removeBtn.style.display = '';
                    root.dataset.hasImage = '1';
                } else {
                    preview.innerHTML = '<div class="site-img-empty"><i class="fas fa-image"></i></div>';
                    if (overlayText) overlayText.textContent = 'Загрузить';
                    if (removeBtn) removeBtn.style.display = 'none';
                    root.dataset.hasImage = '0';
                }
                renderMeta(root, info);
            }

            function uploadImage(root, file) {
                var key = root.dataset.key;
                var progress = root.querySelector('[data-progress]');
                var progressBar = root.querySelector('[data-progress-bar]');
                var progressText = root.querySelector('[data-progress-text]');
                var success = root.querySelector('[data-success]');
                var preview = root.querySelector('[data-preview]');

                preview.innerHTML = '<img src="' + URL.createObjectURL(file) + '" alt="">';

                var form = new FormData();
                form.append('image', file);
                form.append('csrf_token', getCsrf());

                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/admin/site/' + key + '/image', true);
                xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

                xhr.upload.addEventListener('progress', function (e) {
                    if (!e.lengthComputable) return;
                    var pct = Math.round((e.loaded / e.total) * 100);
                    progressBar.style.width = pct + '%';
                    progressText.textContent = pct + '%';
                });

                progress.classList.add('is-visible');

                xhr.addEventListener('load', function () {
                    progress.classList.remove('is-visible');
                    progressBar.style.width = '0%';
                    var data = null;
                    try { data = JSON.parse(xhr.responseText); } catch (e) {}
                    if (xhr.status >= 200 && xhr.status < 300 && data && data.ok) {
                        setPreview(root, data.url, data.info);
                        success.classList.add('is-visible');
                        setTimeout(function () { success.classList.remove('is-visible'); }, 700);
                        showToast('Картинка обновлена', false);
                    } else {
                        showToast((data && data.error) || 'Не удалось загрузить', true);
                        setPreview(root, null, null);
                    }
                });
                xhr.send(form);
            }

            function removeImage(root) {
                if (!confirm('Удалить картинку «' + root.dataset.label + '»?')) return;
                var form = new FormData();
                form.append('remove', '1');
                form.append('csrf_token', getCsrf());

                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/admin/site/' + root.dataset.key + '/image', true);
                xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                xhr.addEventListener('load', function () {
                    var data = null;
                    try { data = JSON.parse(xhr.responseText); } catch (e) {}
                    if (xhr.status >= 200 && xhr.status < 300 && data && data.ok) {
                        setPreview(root, null, null);
                        showToast('Картинка удалена', false);
                    } else {
                        showToast('Не удалось удалить', true);
                    }
                });
                xhr.send(form);
            }

            document.querySelectorAll('[data-site-img]').forEach(function (root) {
                var drop = root.querySelector('[data-drop]');
                var input = root.querySelector('[data-input]');
                var trigger = root.querySelector('[data-trigger-input]');
                var removeBtn = root.querySelector('[data-remove-btn]');

                if (trigger && input) {
                    trigger.addEventListener('click', function () { input.click(); });
                }
                if (input) {
                    input.addEventListener('change', function () {
                        var f = input.files && input.files[0];
                        if (!f) return;
                        uploadImage(root, f);
                        input.value = '';
                    });
                }
                if (drop) {
                    ['dragenter', 'dragover'].forEach(function (ev) {
                        drop.addEventListener(ev, function (e) {
                            e.preventDefault(); e.stopPropagation();
                            drop.classList.add('is-dragover');
                        });
                    });
                    ['dragleave', 'drop'].forEach(function (ev) {
                        drop.addEventListener(ev, function (e) {
                            e.preventDefault(); e.stopPropagation();
                            drop.classList.remove('is-dragover');
                        });
                    });
                    drop.addEventListener('drop', function (e) {
                        var files = e.dataTransfer && e.dataTransfer.files;
                        if (!files || !files.length) return;
                        var f = files[0];
                        if (!f.type.startsWith('image/')) {
                            showToast('Это не изображение', true);
                            return;
                        }
                        uploadImage(root, f);
                    });
                }
                if (removeBtn) {
                    removeBtn.addEventListener('click', function () { removeImage(root); });
                }
            });

            document.querySelectorAll('[data-site-text]').forEach(function (root) {
                var input = root.querySelector('[data-text-input]');
                var saveBtn = root.querySelector('[data-save-text]');
                if (!input || !saveBtn) return;

                saveBtn.addEventListener('click', function () {
                    var form = new FormData();
                    form.append('value', input.value);
                    form.append('csrf_token', getCsrf());

                    var xhr = new XMLHttpRequest();
                    xhr.open('POST', '/admin/site/' + root.dataset.key + '/text', true);
                    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

                    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>…</span>';
                    saveBtn.disabled = true;

                    xhr.addEventListener('load', function () {
                        saveBtn.innerHTML = '<i class="fas fa-check"></i><span>Сохранить</span>';
                        saveBtn.disabled = false;
                        var data = null;
                        try { data = JSON.parse(xhr.responseText); } catch (e) {}
                        if (xhr.status >= 200 && xhr.status < 300 && data && data.ok) {
                            var newVal = data.value || '';
                            input.value = newVal;
                            root.dataset.original = newVal;
                            updateDirtyState(root);
                            showToast('Текст сохранён', false);
                        } else {
                            showToast((data && data.error) || 'Не удалось сохранить', true);
                        }
                    });
                    xhr.addEventListener('error', function () {
                        saveBtn.innerHTML = '<i class="fas fa-check"></i><span>Сохранить</span>';
                        saveBtn.disabled = false;
                        showToast('Ошибка сети', true);
                    });

                    xhr.send(form);
                });
            });

            document.addEventListener('keydown', function (e) {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    var active = document.activeElement;
                    if (!active || !active.closest('[data-site-text]')) return;
                    e.preventDefault();
                    var btn = active.closest('[data-site-text]').querySelector('[data-save-text]');
                    if (btn) btn.click();
                }
            });
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
        } else {
            init();
        }

        document.body.addEventListener('htmx:afterSettle', init);
    })();

    // ============================================================
    // КНОПКА «ПОКАЗАТЬ ЕЩЁ»
    // ============================================================
    (function initLoadMore() {
        const btn = document.getElementById('adm-load-more-btn');
        if (!btn) return;

        btn.addEventListener('click', async function () {
            const tbody = document.getElementById('adm-products-tbody');
            const grid  = document.getElementById('adm-products-grid');
            const container = document.getElementById('adm-load-more-container');

            const textSpan = btn.querySelector('.adm-load-more-text');
            const spinner  = btn.querySelector('.adm-load-more-spinner');

            let page = parseInt(btn.dataset.page, 10);
            const totalPages = parseInt(btn.dataset.totalPages, 10);
            const q = btn.dataset.q || '';

            if (page >= totalPages) return;

            btn.disabled = true;
            textSpan.style.display = 'none';
            spinner.style.display = 'inline-block';

            try {
                const params = new URLSearchParams();
                params.set('page', String(page + 1));
                if (q) params.set('q', q);

                const resp = await fetch('/admin/products/more?' + params.toString(), {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                if (!resp.ok) throw new Error('HTTP ' + resp.status);

                const html = await resp.text();
                const doc = new DOMParser().parseFromString(html, 'text/html');

                const tableTpl = doc.querySelector('template[data-table-rows]');
                if (tableTpl && tbody) {
                    tbody.appendChild(tableTpl.content.cloneNode(true));
                }

                const cardTpl = doc.querySelector('template[data-card-items]');
                if (cardTpl && grid) {
                    grid.appendChild(cardTpl.content.cloneNode(true));
                }

                refreshScrollObserver();

                const meta = doc.querySelector('[data-infinite-meta]');
                if (meta) {
                    page = parseInt(meta.dataset.page, 10);
                    const hasNext = meta.dataset.hasNext === '1';
                    btn.dataset.page = page;

                    if (!hasNext && container) {
                        container.style.transition = 'opacity 200ms ease';
                        container.style.opacity = '0';
                        setTimeout(() => { container.style.display = 'none'; }, 200);
                    }
                }
            } catch (e) {
                console.error('Load more error:', e);
                alert('Не удалось загрузить ещё товары.');
            } finally {
                btn.disabled = false;
                textSpan.style.display = 'inline-block';
                spinner.style.display = 'none';
            }
        });
    })();

    // ============================================================
    // LIVE-ВАЛИДАЦИЯ ИМЕНИ БРЕНДА (только латиница)
    // ============================================================
    (function initBrandNameLiveValidation() {
        // True, если в строке есть буква не из латинского скрипта.
        // Работает так же, как серверный _validate_brand_name в
        // app/routers/admin/catalog.py: цифры/пунктуация пропускаются,
        // любая нелатинская буква (кириллица, CJK, греческий) — блочит.
        function hasNonLatinLetter(str) {
            for (const ch of str) {
                if (/\p{L}/u.test(ch) && !/\p{Script=Latin}/u.test(ch)) {
                    return true;
                }
            }
            return false;
        }

        function validate(input) {
            if (!input.hasAttribute('data-brand-name')) return;
            const form = input.closest('form');
            if (!form) return;

            const err = form.querySelector('[data-brand-name-error]');
            const submit = form.querySelector('button[type="submit"]');

            const bad = hasNonLatinLetter(input.value);

            if (err) err.classList.toggle('is-visible', bad);

            // Нативный tooltip браузера при попытке сабмита
            input.setCustomValidity(bad
                ? 'Бренды пишутся только латиницей. Примеры: Avelea, Chanel, Lush.'
                : '');

            // Блокируем кнопку — пользователь сразу видит, что нельзя
            if (submit) submit.disabled = bad;
        }

        document.addEventListener('input', (e) => {
            const input = e.target.closest('input[data-brand-name]');
            if (input) validate(input);
        });

        // Инициализация при загрузке: проверяем все помеченные
        // поля (для create-name в /admin/brands).
        document.querySelectorAll('input[data-brand-name]').forEach(validate);
    })();

})();