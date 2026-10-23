document.body.classList.add('scroll-anim-enabled');
setTimeout(function () {
    if (!document.body.classList.contains('scroll-anim-ready')) {
        document.body.classList.remove('scroll-anim-enabled');
    }
}, 1500);