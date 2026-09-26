(function () {
    'use strict';
    if (window.__avelea_site_init) return;
    window.__avelea_site_init = true;

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

    // ===== Горизонтальные рейлы карточек (Популярное и т.д.) =====
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
})();