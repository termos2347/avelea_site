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

    document.body.addEventListener('htmx:afterSettle', () => {
        if (window.location.pathname.startsWith('/catalog')) return;
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
            if (pct < EDGE) goTo(current - 1);
            else if (pct > 1 - EDGE) goTo(current + 1);
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

        if (!root.hasAttribute('tabindex')) root.setAttribute('tabindex', '0');
        root.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') { e.preventDefault(); goTo(current - 1); }
            else if (e.key === 'ArrowRight') { e.preventDefault(); goTo(current + 1); }
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
    // SCROLL REVEAL
    // ============================================================
    (function initScrollReveal() {
        if (!document.documentElement.classList.contains('rv')) return;

        const io = ('IntersectionObserver' in window)
            ? new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting) return;
                    entry.target.classList.add('rv-in');
                    io.unobserve(entry.target);
                });
            }, { rootMargin: '0px 0px -8% 0px', threshold: 0.01 })
            : null;

        function inCarousel(el) {
            return !!el.closest('[data-carousel]');
        }

        function tagTargets() {
            const nodes = document.querySelectorAll(
                'section, .product-grid > a, .product-rail > a'
            );
            nodes.forEach((el) => {
                if (inCarousel(el)) return;
                if (el.hasAttribute('data-rv')) return;
                el.setAttribute('data-rv', '');

                const parent = el.parentElement;
                if (!parent) return;

                const siblings = Array.from(parent.children)
                    .filter((c) => c.hasAttribute('data-rv'));
                const i = siblings.indexOf(el);
                if (i > 0) {
                    el.style.transitionDelay = Math.min(i * 45, 360) + 'ms';
                }
            });
        }

        function scan() {
            tagTargets();
            const targets = document.querySelectorAll('[data-rv]:not(.rv-in)');
            if (!io) {
                targets.forEach((el) => el.classList.add('rv-in'));
                return;
            }
            targets.forEach((el) => io.observe(el));
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', scan);
        } else {
            scan();
        }
        document.body.addEventListener('htmx:afterSettle', scan);
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
    // ВЫБОР ВАРИАНТА ТОВАРА (объём / цена)
    // ============================================================
    document.addEventListener('change', function (e) {
        var sel = e.target.closest('[data-variant-select]');
        if (!sel) return;

        var opt = sel.options[sel.selectedIndex];
        if (!opt) return;

        var price  = opt.dataset.price  || '';
        var volume = opt.dataset.volume || '';

        var priceEl  = document.querySelector('[data-variant-price]');
        var volumeEl = document.querySelector('[data-variant-volume]');

        if (priceEl)  priceEl.textContent  = price;
        if (volumeEl) volumeEl.textContent = volume;
    });

})();