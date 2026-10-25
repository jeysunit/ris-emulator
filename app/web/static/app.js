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
  // 漢字の氏名は、文字コードが JIS のときだけ JIS X 0208 の字かどうかを近似で確かめる（半角カナ・
  // 拡張の字を断る）。最後の判定はサーバーが行う。誤りがあるうちは setCustomValidity で送信を止める
  var PATIENT_ID_CHARS = /^[\x20-\x7E]*$/;
  var PATIENT_ID_DELIMITERS = /[\\^~&|]/;
  var ALPHABETIC_CHARS = /^[A-Za-z' -]*$/;
  // JIS X 0208 の字を全部含む範囲（含みすぎてよい。サーバーが正確に判定する。正しい氏名を
  // 画面で止めないため、範囲を狭めない）
  var IDEOGRAPHIC_RANGES = [
    [0x20, 0x7e], [0xa0, 0xf7], [0x391, 0x3c9], [0x401, 0x451], [0x2010, 0x23ff],
    [0x2500, 0x266f], [0x3000, 0x303f], [0x3041, 0x3096], [0x309b, 0x309e],
    [0x30a1, 0x30fe], [0x4e00, 0x9fff], [0xff01, 0xff5e], [0xffe0, 0xffe5],
  ];
  function isIdeographic(value) {
    return Array.from(value).every(function (char) {
      var code = char.codePointAt(0);
      return IDEOGRAPHIC_RANGES.some(function (range) {
        return code >= range[0] && code <= range[1];
      });
    });
  }
  function today() {
    var now = new Date();
    var month = ("0" + (now.getMonth() + 1)).slice(-2);
    var day = ("0" + now.getDate()).slice(-2);
    return now.getFullYear() + "-" + month + "-" + day;
  }
  // かな：全角カタカナ（ァ〜ヾ）と空白だけ。半角カナは断る
  var PHONETIC_RANGES = [[0x20, 0x20], [0x3000, 0x3000], [0x30a1, 0x30fe]];
  function isPhonetic(value) {
    return Array.from(value).every(function (char) {
      var code = char.codePointAt(0);
      return PHONETIC_RANGES.some(function (range) {
        return code >= range[0] && code <= range[1];
      });
    });
  }
  function isAcceptable(input, kind, value) {
    if (kind === "patient-id") {
      return PATIENT_ID_CHARS.test(value) && !PATIENT_ID_DELIMITERS.test(value);
    }
    if (kind === "alphabetic") {
      return ALPHABETIC_CHARS.test(value);
    }
    if (kind === "ideographic") {
      // 文字コードが UTF-8 なら制限しない。JIS のときだけ JIS X 0208 の範囲で確かめる
      return !input.hasAttribute("data-charset-jis") || isIdeographic(value);
    }
    if (kind === "phonetic") {
      return input.hasAttribute("data-test-mode") || isPhonetic(value);
    }
    if (kind === "birth-date") {
      return !value || value <= today();
    }
    return true;
  }
  // かな：ひらがなをカタカナに直し、直したことを欄の下に知らせる（試験の形では直さない）
  var HIRAGANA = /[ぁ-ゖゝゞ]/g;
  var HIRAGANA_TO_KATAKANA = 0x60;
  function convertPhonetic(input) {
    if (input.getAttribute("data-check") !== "phonetic" || input.hasAttribute("data-test-mode")) {
      return;
    }
    var note = document.getElementById("note-phonetic");
    var converted = input.value.replace(HIRAGANA, function (char) {
      return String.fromCharCode(char.charCodeAt(0) + HIRAGANA_TO_KATAKANA);
    });
    var changed = converted !== input.value;
    input.value = converted;
    if (note) {
      note.textContent = changed ? input.getAttribute("data-note") || "" : "";
      note.hidden = !changed;
    }
  }
  document.addEventListener("focusout", function (event) {
    if (event.target instanceof HTMLInputElement) {
      convertPhonetic(event.target);
      checkField(event.target);
    }
  });
  function checkField(input) {
    var kind = input.getAttribute("data-check");
    var note = document.getElementById(input.getAttribute("aria-describedby"));
    if (!kind || !note) {
      return;
    }
    var ok = isAcceptable(input, kind, input.value);
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
