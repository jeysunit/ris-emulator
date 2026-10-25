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
})();
