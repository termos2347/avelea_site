(function () {
    'use strict';
    if (window.__avelea_catalog_init) return;
    window.__avelea_catalog_init = true;

    const body = document.body;
    const toggleBtn = () => document.getElementById('filters-toggle');
    const panel     = () => document.getElementById('filters-panel');
    const backdrop  = () => document.getElementById('filters-backdrop');

    // Ширина вертикального скроллбара. На мобиле / macOS-оверлейных
    // скроллбарах будет 0 — тогда компенсация не нужна.
    function getScrollbarWidth() {
        return window.innerWidth - document.documentElement.clientWidth;
    }

    function open()  {
        // Компенсация исчезающего скроллбара — иначе весь контент
        // прыгает вправо на его ширину. Считаем ДО того, как выставим
        // overflow: hidden (класс filters-open).
        const sbw = getScrollbarWidth();
        if (sbw > 0) {
            body.style.paddingRight = sbw + 'px';
        }

        body.classList.add('filters-open');

        const btn = toggleBtn();
        if (btn) btn.setAttribute('aria-expanded', 'true');

        setTimeout(() => {
            const first = panel() && panel().querySelector('input, select, button');
            if (first) first.focus({ preventScroll: true });
        }, 80);
    }

    function close() {
        body.classList.remove('filters-open');
        // Снимаем компенсацию — возвращаем layout как был.
        body.style.paddingRight = '';

        const btn = toggleBtn();
        if (btn) btn.setAttribute('aria-expanded', 'false');
    }

    function toggle() {
        if (body.classList.contains('filters-open')) close();
        else open();
    }

    // ===== Клики =====
    document.addEventListener('click', (e) => {
        if (e.target.closest('#filters-toggle')) { toggle(); return; }
        if (e.target.closest('#filters-close'))  { close();  return; }
        if (e.target.closest('#filters-cancel')) { close();  return; }
        // Клик по затемнению (вне окна) — закрыть
        if (e.target === backdrop()) { close(); return; }
    });

    // ===== Escape =====
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && body.classList.contains('filters-open')) {
            close();
        }
    });

    // ===== Автосабмит только для сортировки =====
    document.addEventListener('change', (e) => {
        const form = document.getElementById('filters-form');
        if (!form || !form.contains(e.target)) return;
        if (e.target.matches('select[name="sort"]')) {
            form.submit();
        }
    });

    // ===== Закрыть оверлей перед отправкой формы =====
    document.addEventListener('submit', (e) => {
        if (e.target && e.target.id === 'filters-form') close();
    }, true);

    document.body.addEventListener('htmx:beforeSwap', () => {
        if (body.classList.contains('filters-open')) close();
    });
})();