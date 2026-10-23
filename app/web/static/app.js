// 一覧の状態の変更（htmx）が失敗したとき、選択を保存済みの状態に戻し、画面の上にエラーを出す。
// 失敗した応答は行を置き換えない（base.html の responseHandling）ので、戻さないと未保存の値が残る
(function () {
  function fail(event, message) {
    var element = event.detail.elt;
    if (element && element.matches && element.matches("select[data-current]")) {
      element.value = element.dataset.current;
    }
    var box = document.getElementById("request-error");
    if (box) {
      box.textContent = message;
      box.hidden = false;
    }
  }
  document.addEventListener("htmx:responseError", function (event) {
    var status = event.detail.xhr ? event.detail.xhr.status : 0;
    fail(event, "状態を変更できませんでした（" + status + "）。画面を読み直してください");
  });
  // エラーは画面を読み直すまで残す（別の行の変更が成功しても、失敗した行の案内を消さない）
  document.addEventListener("htmx:sendError", function (event) {
    fail(event, "状態を変更できませんでした。接続を確かめて、画面を読み直してください");
  });
})();
