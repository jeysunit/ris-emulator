// 画面の小さな動き。インラインのスクリプトは CSP で止めるので、ここに置く
(function () {
  // htmx の要求が失敗したとき、画面の上にエラーを出す。一覧の状態の変更なら、選択を保存済みの
  // 状態に戻す（失敗した応答は行を置き換えない（base.html の responseHandling）ので、戻さないと
  // 未保存の値が残る）。エラーは画面を読み直すまで残す（別の行の変更が成功しても消さない）
  function fail(event, detail) {
    var element = event.detail.elt;
    var isStatus = element && element.matches && element.matches("select[data-current]");
    if (isStatus) {
      element.value = element.dataset.current;
    }
    var box = document.getElementById("request-error");
    if (box) {
      box.textContent =
        (isStatus ? "状態を変更できませんでした" : "選択肢を読み込めませんでした") + detail;
      box.hidden = false;
    }
  }
  document.addEventListener("htmx:responseError", function (event) {
    var status = event.detail.xhr ? event.detail.xhr.status : 0;
    fail(event, "（" + status + "）。画面を読み直してください");
  });
  document.addEventListener("htmx:sendError", function (event) {
    fail(event, "。接続を確かめて、画面を読み直してください");
  });

  // 登録・作成のボタンは、押したら送信が終わるまで押せなくする（二重送信を防ぐ）
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.method && form.method.toLowerCase() === "post") {
      var buttons = form.querySelectorAll("button[type=submit]");
      for (var i = 0; i < buttons.length; i++) {
        buttons[i].disabled = true;
      }
    }
  });
  // 戻るボタンで戻った画面では、押せる状態に戻す
  window.addEventListener("pageshow", function () {
    var buttons = document.querySelectorAll("form button[type=submit][disabled]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].disabled = false;
    }
  });
})();
