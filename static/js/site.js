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
        let current = 0;
        let timer   = null;

        // Полоски-индикаторы внизу: кликабельные, показывают активный слайд.
        // Без заливки — просто цветом.
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

        // Прогресс-бар в верхнем углу — просто заполняется за INTERVAL
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

        // Свайп на мобиле
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
})();