// 画面の小さな動き。インラインのスクリプトは CSP で止めるので、ここに置く
(function () {
  // htmx の要求が失敗したとき、画面の上にエラーを出す。選んだ予約の状態の変更なら、選択を保存済みの
  // 状態に戻す（失敗した応答は区画を置き換えない（base.html の responseHandling）ので、戻さないと
  // 未保存の値が残る）。エラーは画面を読み直すまで残す（別の予約の変更が成功しても消さない）
  function fail(event, detail) {
    var element = event.detail.elt;
    var select = element && element.querySelector && element.querySelector("select[data-current]");
    var isStatus = !!select;
    if (isStatus) {
      select.value = select.dataset.current;
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
    if (status === 401) {
      // Basic 認証が通らなくなった。読み直してブラウザに認証を求めさせる
      window.location.reload();
      return;
    }
    fail(event, "（" + status + "）。画面を読み直してください");
  });
  document.addEventListener("htmx:sendError", function (event) {
    fail(event, "。接続を確かめて、画面を読み直してください");
  });

  // 予約作成：「新規（架空）」を選んでいる間は、名簿の患者の選択肢を選べなくする。
  // 見た目だけの補助で、サーバーは患者が新規なら名簿の患者ID を使わない
  function syncRosterSelect() {
    var select = document.querySelector("select[data-roster-select]");
    var fresh = document.querySelector("input[name=patient][value=new]");
    if (select && fresh) {
      select.disabled = fresh.checked || select.hasAttribute("data-no-roster");
    }
  }
  document.addEventListener("change", function (event) {
    if (event.target.name === "patient") {
      syncRosterSelect();
    }
  });
  // 戻るボタンで戻った画面は、ブラウザが戻した選択に合わせる
  window.addEventListener("pageshow", syncRosterSelect);
  syncRosterSelect();

  // 登録・作成のボタンは、押したら送信が終わるまで押せなくする（二重送信を防ぐ）
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("hx-post") && form.method && form.method.toLowerCase() === "post") {
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

  // 患者の入力欄：入力のたびに確かめ、誤りの文を欄の下に出す（読み上げない。画面の上の知らせ
  // だけが読み上げる）。文は data-message（サーバーと同じ文。app/core/patient_input.py）。
  // 漢字の氏名は JIS X 0208 の字かどうかの近似（半角カナ・拡張の字を断る）で、最後の判定は
  // サーバーが行う。誤りがあるうちは setCustomValidity で送信を止める
  var PATIENT_ID_CHARS = /^[\x20-\x7E]*$/;
  var PATIENT_ID_DELIMITERS = /[\\^~&|]/;
  var ALPHABETIC_CHARS = /^[A-Za-z' -]*$/;
  var IDEOGRAPHIC_CHARS =
    /^[\x20-\x7E　-〿ぁ-ゖァ-ー一-鿿！-～]*$/;
  function today() {
    var now = new Date();
    var month = ("0" + (now.getMonth() + 1)).slice(-2);
    var day = ("0" + now.getDate()).slice(-2);
    return now.getFullYear() + "-" + month + "-" + day;
  }
  function isAcceptable(kind, value) {
    if (kind === "patient-id") {
      return PATIENT_ID_CHARS.test(value) && !PATIENT_ID_DELIMITERS.test(value);
    }
    if (kind === "alphabetic") {
      return ALPHABETIC_CHARS.test(value);
    }
    if (kind === "ideographic") {
      return IDEOGRAPHIC_CHARS.test(value);
    }
    if (kind === "birth-date") {
      return !value || value <= today();
    }
    return true;
  }
  function checkField(input) {
    var kind = input.getAttribute("data-check");
    var note = document.getElementById(input.getAttribute("aria-describedby"));
    if (!kind || !note) {
      return;
    }
    var ok = isAcceptable(kind, input.value);
    var message = ok ? "" : input.getAttribute("data-message");
    input.setCustomValidity(message);
    if (ok) {
      input.removeAttribute("aria-invalid");
    } else {
      input.setAttribute("aria-invalid", "true");
    }
    note.textContent = message;
    note.hidden = ok;
  }
  document.addEventListener("input", function (event) {
    if (event.target instanceof HTMLInputElement) {
      checkField(event.target);
    }
  });
  document.addEventListener("change", function (event) {
    if (event.target instanceof HTMLInputElement) {
      checkField(event.target);
    }
  });
})();
