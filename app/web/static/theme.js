// 地（明るい地・暗い地）とナビの開閉を、描く前に決める。覚えが無ければ地は端末の設定に従い
// （html に data-theme を付けない）、ナビは開く。上の帯の「表示」とナビの開閉の押しボタンは app.js
(function () {
  var root = document.documentElement;
  try {
    var theme = window.localStorage.getItem("ris-theme");
    if (theme === "dark" || theme === "light") {
      root.setAttribute("data-theme", theme);
    }
    if (window.localStorage.getItem("ris-nav") === "closed") {
      root.setAttribute("data-nav", "closed");
    }
  } catch (error) {
    // 覚えを読めなくても、端末の設定の地・開いたナビで出す
  }
})();
