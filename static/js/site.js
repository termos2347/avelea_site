(function () {
    'use strict';
    if (window.__avelea_site_init) return;
    window.__avelea_site_init = true;

    let hideTimer = null;

    // ============================================================
    // СКЕЛЕТОН ПРИ HTMX-ПЕРЕХОДАХ
    // ============================================================
    const SKELETON_DELAY = 150;
    let skeletonTimer = null;
    let lastClickedHref = null;

    document.addEventListener('click', (e) => {
        const a = e.target.closest('a[href]');
        if (!a) return;
        if (a.getAttribute('hx-boost') === 'false') return;
        const href = a.getAttribute('href');
        if (!href || href.startsWith('http') || href.startsWith('#')) return;
        lastClickedHref = href;
    }, true);

    function pickSkeletonVariant(href) {
        if (!href) return 'catalog';
        const path = href.split('?')[0];
        if (path === '/' || path === '') return 'home';
        if (path.startsWith('/catalog')) return 'catalog';
        if (path.startsWith('/product/')) return 'product';
        if (path.startsWith('/about')) return 'about';
        return 'catalog';
    }

    function showSkeleton() {
        const overlay = document.getElementById('skeleton-overlay');
        if (!overlay) return;
        const variant = pickSkeletonVariant(lastClickedHref);
        overlay.querySelectorAll('.sk-variant').forEach(v => {
            v.classList.toggle('is-active', v.dataset.sk === variant);
        });
        overlay.classList.add('is-visible');
    }

    function hideSkeleton() {
        clearTimeout(skeletonTimer);
        const el = document.getElementById('skeleton-overlay');
        if (el) el.classList.remove('is-visible');
    }

    document.body.addEventListener('htmx:beforeRequest', (e) => {
        const target = e.detail.target;
        if (!target || target !== document.body) return;
        clearTimeout(skeletonTimer);
        skeletonTimer = setTimeout(showSkeleton, SKELETON_DELAY);
    });

    document.body.addEventListener('htmx:afterSettle', hideSkeleton);
    document.body.addEventListener('htmx:afterRequest', hideSkeleton);
    document.body.addEventListener('htmx:responseError', hideSkeleton);

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

    // ===== Скролл наверх после перехода (кроме каталога) =====
    document.body.addEventListener('htmx:afterSettle', () => {
        if (window.location.pathname.startsWith('/catalog')) return;
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

    // ===== Главная: hero-карусель =====
    function initCarousel(root) {
        if (root.hasAttribute('data-ready')) return;
        root.setAttribute('data-ready', '1');

        const track  = root.querySelector('[data-track]');
        const slides = Array.from(root.querySelectorAll('[data-slide]'));
        const dotsEl = root.querySelector('[data-dots]');
        const bar    = root.querySelector('[data-progress]');

        if (!track || slides.length < 2) return;

        const INTERVAL = 5500;
        const EDGE = 0.3;
        let current = 0;
        let timer   = null;

        const segments = slides.map((_, i) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.setAttribute('aria-label', 'Слайд ' + (i + 1));
            btn.className = 'flex-1 h-1 md:h-1.5 rounded-full transition-colors cursor-pointer bg-pink-300/40 hover:bg-pink-400/60';
            btn.addEventListener('click', () => goTo(i));
            dotsEl && dotsEl.appendChild(btn);
            return btn;
        });

        function render() {
            track.style.transform = 'translateX(-' + (current * 100) + '%)';
            segments.forEach((s, i) => {
                const active = i === current;
                s.classList.toggle('bg-pink-600', active);
                s.classList.toggle('bg-pink-300/40', !active);
                s.classList.toggle('hover:bg-pink-400/60', !active);
            });
        }

        function restartBar() {
            if (!bar) return;
            bar.style.transition = 'none';
            bar.style.width = '0%';
            void bar.offsetWidth;
            bar.style.transition = 'width ' + INTERVAL + 'ms linear';
            bar.style.width = '100%';
        }

        function startTimer() {
            if (timer) clearTimeout(timer);
            restartBar();
            timer = setTimeout(() => {
                goTo(current + 1);
            }, INTERVAL);
        }

        function goTo(i) {
            current = (i + slides.length) % slides.length;
            render();
            startTimer();
        }

        root.addEventListener('click', (e) => {
            if (e.target.closest('a, button, input, select, textarea')) return;

            const rect = root.getBoundingClientRect();
            const pct = (e.clientX - rect.left) / rect.width;

            if (pct < EDGE) {
                goTo(current - 1);
            } else if (pct > 1 - EDGE) {
                goTo(current + 1);
            }
        });

        root.addEventListener('mousemove', (e) => {
            const rect = root.getBoundingClientRect();
            const pct = (e.clientX - rect.left) / rect.width;
            const overEdge = pct < EDGE || pct > 1 - EDGE;
            const overInteractive = e.target.closest('a, button, input, select, textarea');
            root.style.cursor = (overEdge && !overInteractive) ? 'pointer' : '';
        });

        let x0 = null;
        root.addEventListener('touchstart', (e) => {
            x0 = e.touches[0].clientX;
        }, { passive: true });
        root.addEventListener('touchend', (e) => {
            if (x0 === null) return;
            const dx = e.changedTouches[0].clientX - x0;
            if (Math.abs(dx) > 40) (dx < 0 ? goTo(current + 1) : goTo(current - 1));
            x0 = null;
        });
        root.addEventListener('touchcancel', () => { x0 = null; });

        if (!root.hasAttribute('tabindex')) {
            root.setAttribute('tabindex', '0');
        }
        root.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                goTo(current - 1);
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                goTo(current + 1);
            }
        });

        render();
        startTimer();
    }

    function scanCarousels() {
        document.querySelectorAll('[data-carousel]').forEach(initCarousel);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scanCarousels);
    } else {
        scanCarousels();
    }

    document.body.addEventListener('htmx:afterSettle', scanCarousels);

    // ===== Горизонтальные рейлы карточек =====
    function initRails() {
        document.querySelectorAll('.product-rail-wrap').forEach((wrap) => {
            if (wrap.hasAttribute('data-ready')) return;
            wrap.setAttribute('data-ready', '1');

            const rail = wrap.querySelector('.product-rail');
            const prev = wrap.querySelector('[data-rail-prev]');
            const next = wrap.querySelector('[data-rail-next]');
            if (!rail || !prev || !next) return;

            function update() {
                const max = rail.scrollWidth - rail.clientWidth;
                prev.disabled = rail.scrollLeft <= 1;
                next.disabled = rail.scrollLeft >= max - 1;
            }

            function step(dir) {
                const card = rail.querySelector(':scope > a');
                const w = card ? card.getBoundingClientRect().width : rail.clientWidth;
                const gap = parseFloat(getComputedStyle(rail).gap) || 0;
                rail.scrollBy({ left: dir * (w + gap), behavior: 'smooth' });
            }

            prev.addEventListener('click', () => step(-1));
            next.addEventListener('click', () => step(1));
            rail.addEventListener('scroll', update, { passive: true });
            window.addEventListener('resize', update);
            update();
        });
    }

    initRails();
    document.body.addEventListener('htmx:afterSettle', initRails);

    // ============================================================
    // МЕНЮ И ПОИСК
    // ============================================================
    (function initHeaderInteractions() {
        function openMenu() {
            const menu = document.getElementById('mobile-menu');
            const backdrop = document.getElementById('menu-backdrop');
            if (menu) menu.classList.remove('-translate-x-full');
            if (backdrop) backdrop.classList.remove('opacity-0', 'pointer-events-none');
        }
        function closeMenu() {
            const menu = document.getElementById('mobile-menu');
            const backdrop = document.getElementById('menu-backdrop');
            if (menu) menu.classList.add('-translate-x-full');
            if (backdrop) backdrop.classList.add('opacity-0', 'pointer-events-none');
        }

        function openSearch() {
            const search = document.getElementById('search-overlay');
            if (!search) return;
            search.classList.add('is-open');
            search.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden';
            const input = search.querySelector('input[name="q"]');
            if (input) setTimeout(() => input.focus(), 180);
        }
        function closeSearch() {
            const search = document.getElementById('search-overlay');
            if (!search) return;
            search.classList.remove('is-open');
            search.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
        }

        document.addEventListener('click', function (e) {
            if (e.target.closest('#open-menu')) { openMenu(); return; }
            if (e.target.closest('#close-menu')) { closeMenu(); return; }
            if (e.target.closest('#menu-backdrop')) { closeMenu(); return; }

            if (e.target.closest('#open-search')) { openSearch(); return; }
            if (e.target.closest('#close-search')) { closeSearch(); return; }
            if (e.target.closest('[data-search-close]')) { closeSearch(); return; }

            if (e.target.closest('#mobile-menu a')) { closeMenu(); }
        });

        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            const search = document.getElementById('search-overlay');
            if (search && search.classList.contains('is-open')) closeSearch();
        });
    })();

    // ============================================================
    // АККОРДЕОН в карточке товара
    // ============================================================
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-acc-toggle]');
        if (!btn) return;
        var item = btn.closest('[data-acc]');
        if (!item) return;
        item.classList.toggle('is-open');
    });

    // ============================================================
    // ВЫБОР ВАРИАНТА ТОВАРА
    // ============================================================
    (function initVariantPicker() {
        function closeAll(except) {
            document.querySelectorAll('[data-variant-picker].is-open')
                .forEach(function (p) {
                    if (p === except) return;
                    p.classList.remove('is-open');
                    var t = p.querySelector('[data-variant-trigger]');
                    if (t) t.setAttribute('aria-expanded', 'false');
                });
        }

        document.addEventListener('click', function (e) {
            var trigger = e.target.closest('[data-variant-trigger]');
            if (trigger) {
                var picker = trigger.closest('[data-variant-picker]');
                if (!picker) return;
                var isOpen = picker.classList.toggle('is-open');
                trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
                if (isOpen) closeAll(picker);
                return;
            }

            var option = e.target.closest('[data-variant-option]');
            if (option) {
                var picker = option.closest('[data-variant-picker]');
                if (!picker) return;

                var price  = option.dataset.price  || '';
                var volume = option.dataset.volume || '';

                picker.querySelectorAll('[data-variant-option]').forEach(function (o) {
                    o.classList.toggle('is-active', o === option);
                });

                var tVol   = picker.querySelector('[data-variant-trigger-volume]');
                var tPrice = picker.querySelector('[data-variant-trigger-price]');
                if (tVol)   tVol.textContent   = volume;
                if (tPrice) tPrice.textContent = price + ' ₽';

                var mPrice  = document.querySelector('[data-variant-price]');
                var mVolume = document.querySelector('[data-variant-volume]');
                if (mPrice)  mPrice.textContent  = price;
                if (mVolume) mVolume.textContent = volume;

                picker.classList.remove('is-open');
                var trg = picker.querySelector('[data-variant-trigger]');
                if (trg) trg.setAttribute('aria-expanded', 'false');
                return;
            }

            if (!e.target.closest('[data-variant-picker]')) {
                closeAll(null);
            }
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeAll(null);
        });
    })();

    // ============================================================
    // SCROLL-REVEAL: анимация карточек при скролле
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
            rootMargin: '-5% 0px -5% 0px',
            threshold: 0,
        });

        const deadTop    = window.innerHeight * 0.05;
        const deadBottom = window.innerHeight * 0.95;

        document.querySelectorAll('.reveal-item').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.bottom > deadTop && r.top < deadBottom) {
                el.classList.add('is-visible');
            }
            scrollObserver.observe(el);
        });
    }

    // Экспортируем для catalog.js
    window.refreshScrollObserver = function() {
        if (!scrollObserver) return;
        document.querySelectorAll('.reveal-item').forEach(el => {
            scrollObserver.observe(el);
        });
    };

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

})();