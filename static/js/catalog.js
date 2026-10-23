(function () {
    'use strict';
    if (window.__avelea_catalog_init) return;
    window.__avelea_catalog_init = true;

    const body = document.body;
    const toggleBtn = () => document.getElementById('filters-toggle');
    const panel     = () => document.getElementById('filters-panel');
    const backdrop  = () => document.getElementById('filters-backdrop');

    function getScrollbarWidth() {
        return window.innerWidth - document.documentElement.clientWidth;
    }

    function open()  {
        const sbw = getScrollbarWidth();
        if (sbw > 0) body.style.paddingRight = sbw + 'px';
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
        body.style.paddingRight = '';
        const btn = toggleBtn();
        if (btn) btn.setAttribute('aria-expanded', 'false');
    }

    function toggle() {
        if (body.classList.contains('filters-open')) close();
        else open();
    }

    // ===== Клики по фильтрам =====
    document.addEventListener('click', (e) => {
        if (e.target.closest('#filters-toggle')) { toggle(); return; }
        if (e.target.closest('#filters-close'))  { close();  return; }
        if (e.target.closest('#filters-cancel')) { close();  return; }
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

    // ============================================================
    // INFINITE SCROLL
    // ============================================================
    let infiniteScroll = null;

    function initInfiniteScroll() {
        const grid = document.getElementById('catalog-grid');
        if (!grid) return;
        if (grid.hasAttribute('data-inf-ready')) return;
        grid.setAttribute('data-inf-ready', '1');

        document.querySelectorAll('[data-pagination]').forEach(el => {
            el.style.display = 'none';
        });

        const loader   = document.getElementById('catalog-loader');
        const endMsg   = document.getElementById('catalog-end');
        const sentinel = document.getElementById('catalog-sentinel');

        if (!loader || !sentinel) {
            console.warn('catalog: нет #catalog-loader или #catalog-sentinel');
            return;
        }

        let loading = false;

        const initialPage  = parseInt(grid.dataset.page, 10) || 1;
        const initialTotal = parseInt(grid.dataset.totalPages, 10) || 1;
        if (initialPage >= initialTotal && endMsg) {
            endMsg.hidden = false;
        }

        async function loadNext() {
            if (loading) return;

            const page       = parseInt(grid.dataset.page, 10) || 1;
            const totalPages = parseInt(grid.dataset.totalPages, 10) || 1;

            if (page >= totalPages) {
                if (endMsg) endMsg.hidden = false;
                return;
            }

            loading = true;
            loader.classList.add('is-loading');

            try {
                const params = new URLSearchParams(window.location.search);
                params.set('page', String(page + 1));

                const resp = await fetch('/catalog/more?' + params.toString(), {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (!resp.ok) throw new Error('HTTP ' + resp.status);

                const html = await resp.text();

                const tmp = document.createElement('div');
                tmp.innerHTML = html;

                const cards = Array.from(tmp.querySelectorAll('a.group'));
                const meta = tmp.querySelector('[data-catalog-meta]');

                cards.forEach(el => {
                    el.classList.add('catalog-item-new');
                    grid.appendChild(el);
                    setTimeout(() => el.classList.remove('catalog-item-new'), 400);
                });

                // ВАЖНО: подключаем новые карточки к анимации появления
                if (window.refreshScrollObserver) window.refreshScrollObserver();

                if (meta) {
                    const nextPage = meta.dataset.loadedPage;
                    const hasNext  = meta.dataset.hasNext === '1';
                    grid.dataset.page = nextPage;
                    if (!hasNext && endMsg) endMsg.hidden = false;
                }
            } catch (e) {
                console.error('Infinite scroll error:', e);
            } finally {
                loading = false;
                loader.classList.remove('is-loading');
            }
        }

        infiniteScroll = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) loadNext();
                });
            },
            { rootMargin: '400px 0px' }
        );

        infiniteScroll.observe(sentinel);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initInfiniteScroll);
    } else {
        initInfiniteScroll();
    }

    document.body.addEventListener('htmx:afterSettle', () => {
        if (infiniteScroll) {
            infiniteScroll.disconnect();
            infiniteScroll = null;
        }
        initInfiniteScroll();
    });

})();