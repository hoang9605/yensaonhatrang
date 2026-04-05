(function () {
  "use strict";

  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function initReveal() {
    var nodes = document.querySelectorAll("[data-reveal]");
    if (!nodes.length) return;

    if (reducedMotion) {
      nodes.forEach(function (el) {
        el.classList.add("is-revealed");
      });
      return;
    }

    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-revealed");
            io.unobserve(entry.target);
          }
        });
      },
      {
        root: null,
        rootMargin: "0px 0px -6% 0px",
        threshold: 0.08,
      }
    );

    nodes.forEach(function (el) {
      io.observe(el);
    });
  }

  function initParallax() {
    var layer = document.querySelector("[data-lux-parallax]");
    if (!layer || reducedMotion) return;

    var ticking = false;

    function update() {
      var y = window.scrollY || window.pageYOffset;
      var factor = 0.38;
      layer.style.transform = "translate3d(0," + Math.round(y * factor) + "px,0)";
      ticking = false;
    }

    function onScroll() {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(update);
      }
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    update();
  }

  initParallax();
  initReveal();
})();
