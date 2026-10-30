// 画面の小さな動き。インラインのスクリプトは CSP で止めるので、ここに置く
(function () {
  var root = document.documentElement;
  function remember(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      // 覚えられなくても、いまのページの表示は変わる
    }
  }

  // ナビの開閉：theme.js が読んだ覚え（html の data-nav）を外枠に写す
  var shell = document.querySelector(".shell");
  var navButton = document.querySelector("[data-act=nav]");
  function setNav(closed) {
    if (!shell || !navButton) {
      return;
    }
    shell.classList.toggle("collapsed", closed);
    navButton.setAttribute("aria-expanded", closed ? "false" : "true");
    // 読み上げの名前（aria-label）と絵は替えず、ホバーの title だけ替える
    navButton.setAttribute("title", closed ? "ナビを開く" : "ナビを閉じる");
  }
  setNav(root.getAttribute("data-nav") === "closed");

  // 上の帯の押しボタン：表示（明るい地と暗い地）とナビの開閉。押すたびに替えて覚える
  document.addEventListener("click", function (event) {
    var theme = event.target.closest("[data-act=theme]");
    if (theme) {
      var dark = root.getAttribute("data-theme")
        ? root.getAttribute("data-theme") === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      var next = dark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      remember("ris-theme", next);
      return;
    }
    if (event.target.closest("[data-act=nav]")) {
      var closed = !shell.classList.contains("collapsed");
      setNav(closed);
      root.setAttribute("data-nav", closed ? "closed" : "open");
      remember("ris-nav", closed ? "closed" : "open");
    }
  });

  // htmx の要求が失敗したとき、画面の上にエラーを出す。選んだ予約の状態の変更なら、選択を保存済みの
  // 状態に戻す（失敗した応答は区画を置き換えない（base.html の responseHandling）ので、戻さないと
  // 未保存の値が残る）。エラーは画面を読み直すまで残す（別の予約の変更が成功しても消さない）
  function fail(event, detail) {
    var element = event.detail.elt;
    var select = element && element.querySelector && element.querySelector("select[data-current]");
    // 確認の窓（dlg-status-…）から送った変更も、状態の変更として扱う
    if (!select && element && element.closest && element.closest("dialog[id^='dlg-status-']")) {
      select = document.querySelector("select[data-current]");
    }
    var isStatus = !!select;
    if (isStatus) {
      select.value = select.dataset.current;
    }
    var box = document.getElementById("request-error");
    var text = box && box.querySelector("div");
    if (text) {
      text.textContent =
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
    if (isConnCheck(event)) {
      announceUnreadable();
      return;
    }
    fail(event, "（" + status + "）。画面を読み直してください");
  });
  document.addEventListener("htmx:sendError", function (event) {
    if (isConnCheck(event)) {
      announceUnreadable();
      return;
    }
    fail(event, "。接続を確かめて、画面を読み直してください");
  });

  // 上の帯の「接続確認」の結果の読み上げ（部品集の 3 つの型）。結果の 1 文は読み上げの欄
  // （#conn-result。popover の中）の data-result で届く。欄は中身ごと差し替わるので、差し替えた後に、
  // 先に空にしてから入れる（同じ文が続いても読み直される）。ボタンも差し替わるので、焦点を戻す
  function announceConn(text) {
    var result = document.getElementById("conn-result");
    if (!result || !text) {
      return;
    }
    result.textContent = "";
    window.setTimeout(function () {
      result.textContent = text;
    }, 50);
  }
  function isConnCheck(event) {
    var config = event.detail && event.detail.requestConfig;
    return !!config && config.path === "/connection/check";
  }
  // 要求が届かない・断られたときは、差し替わらない欄に「確かめられなかった」の型を入れる
  function announceUnreadable() {
    var result = document.getElementById("conn-result");
    announceConn(result ? result.getAttribute("data-unreadable") : null);
  }
  document.addEventListener("htmx:afterSwap", function (event) {
    var result = document.getElementById("conn-result");
    if (!isConnCheck(event) || !result) {
      return;
    }
    announceConn(result.getAttribute("data-result"));
    var button = document.getElementById("conn-check");
    if (button) {
      button.focus();
    }
  });

  // 予約作成：「新規（架空）」を選んでいる間は、名簿の患者の選択肢を選べなくする。
  // 見た目だけの補助で、サーバーは患者が新規なら名簿の患者ID を使わない
  function syncRosterSelect() {
    var select = document.querySelector("select[data-roster-select]");
    var fresh = document.querySelector("input[name=patient][value=new]");
    if (select && fresh) {
      select.disabled = fresh.checked || select.hasAttribute("data-no-roster");
    }
    syncPatientSource();
  }
  // 照合：「名簿から選ぶ」「入力する」のうち、選んでいない側の欄を押せなくする（どちらの値で
  // 照合するかを見て分かるようにする）。サーバーも選んだ側の値だけを使う
  function syncPatientSource() {
    var form = document.querySelector("form[data-patient-source]");
    if (!form) {
      return;
    }
    var roster = form.querySelector("input[name=patient][value=roster]");
    var manual = form.querySelector("input[name=patient][value=manual]");
    var fields = form.querySelectorAll(
      "[name=patient_id], [name$=_family], [name$=_given], [name=birth_date], [name=sex]"
    );
    var select = form.querySelector("select[name=roster_patient_id]");
    if (select) {
      select.disabled = !(roster && roster.checked && !roster.disabled);
    }
    for (var i = 0; i < fields.length; i++) {
      fields[i].disabled = !(manual && manual.checked);
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

  // 確認の窓（標準の dialog）。サーバーが開いた形で出した窓は、モーダルで開き直す（後ろを
  // 押せなくし、Esc で閉じられるようにする）。初めのフォーカスはキャンセル（autofocus）
  function showModal(dialog) {
    if (typeof dialog.showModal !== "function") {
      return false;
    }
    if (dialog.open) {
      dialog.close();
    }
    dialog.showModal();
    return true;
  }
  var opened = document.querySelectorAll("dialog[data-show-modal][open]");
  for (var d = 0; d < opened.length; d++) {
    showModal(opened[d]);
  }
  // 状態を終わりの状態（完了・取消・中止）へ変えるときは、送る前にその状態の確認の窓を開く。
  // htmx より先に受けて止める（捕捉の段で止めないと、htmx が先に送る）
  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      // 状態の変更のフォーム（POST で /orders/<受付番号>/status へ送るもの）だけを受ける。
      // 一覧の検索の帯（GET）にも状態の選択があるので、select の名前だけでは決めない
      var action = (form.getAttribute && form.getAttribute("action")) || "";
      if (
        !form.method ||
        form.method.toLowerCase() !== "post" ||
        !/^\/orders\/[^/]+\/status$/.test(action) ||
        form.closest("dialog")
      ) {
        return;
      }
      var select = form.querySelector("select[name=status]");
      if (!select) {
        return;
      }
      var dialog = document.getElementById("dlg-status-" + select.value);
      if (dialog && showModal(dialog)) {
        event.preventDefault();
        event.stopPropagation();
      }
    },
    true
  );
  // 窓の中の htmx の送信が終わったら窓を閉じる（失敗の知らせを、窓の後ろに隠さない）
  document.addEventListener("htmx:afterRequest", function (event) {
    var dialog = event.detail.elt && event.detail.elt.closest && event.detail.elt.closest("dialog");
    if (dialog && dialog.open) {
      dialog.close();
    }
  });

  // 登録・作成のボタンは、押したら送信が終わるまで押せなくする（二重送信を防ぐ）。
  // 窓の実行のボタンはフォームの外にある（form 属性で結ぶ）ので、押したボタンも押せなくする
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("hx-post") && form.method && form.method.toLowerCase() === "post") {
      var buttons = form.querySelectorAll("button[type=submit]");
      for (var i = 0; i < buttons.length; i++) {
        buttons[i].disabled = true;
      }
      if (event.submitter) {
        event.submitter.disabled = true;
      }
    }
  });
  // 戻るボタンで戻った画面では、押せる状態に戻す
  window.addEventListener("pageshow", function () {
    var buttons = document.querySelectorAll("button[type=submit][disabled]");
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
      // ひらがなは、フォーカスが外れるか送る時にカタカナへ直すので、入力の途中は誤りにしない
      return input.hasAttribute("data-test-mode") || isPhonetic(toKatakana(value));
    }
    if (kind === "birth-date") {
      // 生年月日はサーバーが読み取る（元号の表は app/core/wareki.py にだけ置く）。読めなかった
      // ことは、欄の下の読み取り結果を差し替えたときに data-unreadable で受け取る
      return !value.trim() || !input.hasAttribute("data-unreadable");
    }
    return true;
  }
  // 欄の aria-describedby が指す要素のうち、class を持つもの（.hint・.msg）
  function described(input, className) {
    var ids = (input.getAttribute("aria-describedby") || "").split(/\s+/);
    for (var i = 0; i < ids.length; i++) {
      var element = ids[i] ? document.getElementById(ids[i]) : null;
      if (element && element.classList.contains(className)) {
        return element;
      }
    }
    return null;
  }
  // かな：ひらがなをカタカナに直し、直したことを欄の下に知らせる（試験の形では直さない）
  var HIRAGANA = /[ぁ-ゖゝゞ]/g;
  var HIRAGANA_TO_KATAKANA = 0x60;
  function toKatakana(value) {
    return value.replace(HIRAGANA, function (char) {
      return String.fromCharCode(char.charCodeAt(0) + HIRAGANA_TO_KATAKANA);
    });
  }
  function convertPhonetic(input) {
    if (input.getAttribute("data-check") !== "phonetic" || input.hasAttribute("data-test-mode")) {
      return;
    }
    var note = document.getElementById("note-phonetic");
    var converted = toKatakana(input.value);
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
  // 欄にいるまま Enter で送ったとき（focusout が起きない）も、送る前に直して確かめ直す
  document.addEventListener(
    "submit",
    function (event) {
      var inputs = event.target.querySelectorAll ? event.target.querySelectorAll("input[data-check=phonetic]") : [];
      for (var i = 0; i < inputs.length; i++) {
        convertPhonetic(inputs[i]);
        checkField(inputs[i]);
      }
    },
    true
  );
  function checkField(input) {
    var kind = input.getAttribute("data-check");
    var note = described(input, "msg");
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
    var text = note.querySelector("span");
    (text || note).textContent = message;
    note.hidden = ok;
  }
  document.addEventListener("input", function (event) {
    if (event.target instanceof HTMLInputElement) {
      if (event.target.getAttribute("data-check") === "birth-date") {
        // 入力のたびに前の読み取りの誤りを外し、新しい読み取り結果（.hint）が返るまで古い誤りを残さない
        event.target.removeAttribute("data-unreadable");
        event.target.removeAttribute("data-message");
      }
      checkField(event.target);
    }
  });
  document.addEventListener("change", function (event) {
    if (event.target instanceof HTMLInputElement) {
      checkField(event.target);
    }
  });
  // 生年月日：サーバーが返した読み取り結果（.hint）を差し替えた後に、誤りの文（data-error）を欄の
  // 文にして確かめ直す。読めないときは .hint が空で、.msg に誤りの文が出る
  document.addEventListener("htmx:afterSettle", function (event) {
    var config = event.detail && event.detail.requestConfig;
    var input = config && config.elt;
    if (!(input instanceof HTMLInputElement) || input.getAttribute("data-check") !== "birth-date") {
      return;
    }
    var hint = described(input, "hint");
    var problem = hint ? hint.getAttribute("data-error") : null;
    if (problem) {
      input.setAttribute("data-unreadable", "");
      input.setAttribute("data-message", problem);
    } else {
      input.removeAttribute("data-unreadable");
    }
    checkField(input);
  });
})();
