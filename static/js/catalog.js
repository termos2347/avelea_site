(function () {
    'use strict';
    if (window.__avelea_catalog_init) return;
    window.__avelea_catalog_init = true;

    const KEY = 'catalog_filters_collapsed';
    const isMobile = () => window.matchMedia('(max-width: 767px)').matches;

    // ===== Ранняя синхронизация свёрнутого состояния (desktop) =====
    // Выполняется один раз при первой загрузке. При HTMX-переходах класс
    // на <body> сохраняется (htmx не пересоздаёт body целиком).
    try {
        if (localStorage.getItem(KEY) === '1') {
            document.body.classList.add('catalog-filters-collapsed');
        }
    } catch (e) {}

    function syncToggle() {
        const collapsed = document.body.classList.contains('catalog-filters-collapsed');
        const btn  = document.getElementById('filters-toggle-desktop');
        const icon = document.getElementById('filters-toggle-icon');
        if (btn)  btn.setAttribute('aria-expanded', String(!collapsed));
        if (icon) {
            icon.classList.toggle('fa-chevron-left', !collapsed);
            icon.classList.toggle('fa-chevron-right', collapsed);
        }
    }

    function setCollapsed(collapsed) {
        document.body.classList.toggle('catalog-filters-collapsed', collapsed);
        syncToggle();
        try { localStorage.setItem(KEY, collapsed ? '1' : '0'); } catch (e) {}
    }

    // ===== Делегирование кликов =====
    document.addEventListener('click', (e) => {
        if (e.target.closest('#filters-toggle-desktop')) {
            setCollapsed(!document.body.classList.contains('catalog-filters-collapsed'));
            return;
        }
        if (e.target.closest('#open-filters-mobile')) {
            document.body.classList.add('mobile-filters-open');
            return;
        }
        if (e.target.closest('#close-filters-mobile')) {
            document.body.classList.remove('mobile-filters-open');
            return;
        }
        if (e.target.closest('#apply-filters-mobile')) {
            document.body.classList.remove('mobile-filters-open');
            const form = document.getElementById('filters-form');
            if (form) form.submit();
            return;
        }
    });

    // ===== Делегирование change на форме фильтров =====
    document.addEventListener('change', (e) => {
        const form = document.getElementById('filters-form');
        if (!form || !form.contains(e.target)) return;

        const t = e.target;
        if (t.matches('select[name="sort"]')) {
            form.submit();
            return;
        }
        if (t.matches('input[name="category"], input[name="brand"], input[name="price_min"], input[name="price_max"]')) {
            if (isMobile()) return;
            form.submit();
        }
    });

    // ===== Escape закрывает мобильные фильтры =====
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') document.body.classList.remove('mobile-filters-open');
    });

    // ===== Синхронизация иконок после HTMX-свапа =====
    // Единственный afterSettle-хук. Он идемпотентен — можно вызывать сколько угодно раз.
    document.body.addEventListener('htmx:afterSettle', syncToggle);

    // И один раз при первой загрузке — если перешли прямой ссылкой.
    syncToggle();
})();