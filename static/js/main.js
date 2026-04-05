/**
 * Menu điều hướng mobile: bật/tắt class nav-open trên body
 */
(function () {
  var toggle = document.getElementById("navToggle");
  var nav = document.getElementById("mainNav");
  if (!toggle || !nav) return;

  toggle.addEventListener("click", function () {
    document.body.classList.toggle("nav-open");
  });

  // Đóng menu khi click link (mobile)
  nav.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function () {
      document.body.classList.remove("nav-open");
    });
  });
})();
