/**
 * Kéo thả / chọn ảnh sản phẩm (admin). Không dùng thư viện ngoài.
 * Form cần: data-product-upload, [data-drop-zone], input[name=image_file], [data-preview]
 */
(function () {
  var form = document.querySelector("form[data-product-upload]");
  if (!form) return;

  var input = form.querySelector('input[type="file"][name="image_file"]');
  var drop = form.querySelector("[data-drop-zone]");
  var preview = form.querySelector("[data-preview]");
  var hiddenImage = form.querySelector('input[name="image"]');

  if (!input || !drop || !preview) return;

  function setDragHighlight(on) {
    drop.classList.toggle("is-dragover", on);
  }

  drop.addEventListener("click", function () {
    input.click();
  });

  drop.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });

  ["dragenter", "dragover"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault();
      e.stopPropagation();
      setDragHighlight(true);
    });
  });

  ["dragleave", "drop"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault();
      e.stopPropagation();
      setDragHighlight(false);
    });
  });

  drop.addEventListener("drop", function (e) {
    var dt = e.dataTransfer;
    if (!dt || !dt.files || !dt.files.length) return;
    var file = dt.files[0];
    if (!file.type.match(/^image\//)) return;
    try {
      var buf = new DataTransfer();
      buf.items.add(file);
      input.files = buf.files;
    } catch (err) {
      console.error(err);
    }
    showPreview(file);
    if (hiddenImage) hiddenImage.value = "";
  });

  input.addEventListener("change", function () {
    if (input.files && input.files[0]) {
      showPreview(input.files[0]);
      if (hiddenImage) hiddenImage.value = "";
    }
  });

  function showPreview(file) {
    var reader = new FileReader();
    reader.onload = function (ev) {
      preview.innerHTML =
        '<img src="' + ev.target.result + '" alt="Xem trước" class="upload-preview-img">';
      preview.classList.add("has-image");
    };
    reader.readAsDataURL(file);
  }
})();
