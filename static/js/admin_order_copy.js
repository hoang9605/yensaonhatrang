/**
 * Nút Copy mã đơn (admin) — navigator.clipboard
 */
(function () {
  document.querySelectorAll(".js-copy-order-code").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var code = btn.getAttribute("data-code");
      if (!code) return;
      if (!navigator.clipboard || !navigator.clipboard.writeText) {
        alert("Trình duyệt không hỗ trợ copy.");
        return;
      }
      navigator.clipboard.writeText(code).then(
        function () {
          alert("Đã copy");
        },
        function () {
          alert("Không copy được.");
        }
      );
    });
  });
})();
