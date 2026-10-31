// app.js の「確認中」の動きを、最小の偽の DOM の上で動かす（tests/web/test_connections.py から node で起こす）。
// 引数: app.js のパス。結果は JSON を 1 行で標準出力に出す。
"use strict";
const fs = require("fs");

class Node_ {
  constructor(tag) {
    this.tag = tag;
    this.attrs = {};
    this.className = "";
    this.childNodes = [];
    this.parentNode = null;
    this.text = "";
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  getAttribute(name) {
    return name in this.attrs ? this.attrs[name] : null;
  }
  hasAttribute(name) {
    return name in this.attrs;
  }
  appendChild(child) {
    if (child.parentNode) {
      child.parentNode.childNodes = child.parentNode.childNodes.filter((c) => c !== child);
    }
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  set textContent(value) {
    for (const child of this.childNodes) {
      child.parentNode = null;
    }
    this.childNodes = [];
    this.text = value;
  }
  get textContent() {
    return this.text + this.childNodes.map((c) => c.textContent).join("");
  }
  // 使うのは「.st[data-k=check]」だけ
  querySelector(selector) {
    if (selector !== ".st[data-k=check]") {
      throw new Error("unsupported selector: " + selector);
    }
    for (const child of this.childNodes) {
      if (child.className === "st" && child.getAttribute("data-k") === "check") {
        return child;
      }
    }
    return null;
  }
  closest(tag) {
    for (let node = this; node; node = node.parentNode) {
      if (node.tag === tag) {
        return node;
      }
    }
    return null;
  }
}

function cell(label) {
  const td = new Node_("td");
  td.className = "res";
  const mark = new Node_("span");
  mark.className = "st";
  mark.setAttribute("data-k", "plan");
  mark.text = label;
  td.appendChild(mark);
  return td;
}

const listeners = {};
const rows = [new Node_("tr"), new Node_("tr")];
const cells = rows.map((row, i) => row.appendChild(cell("未確認" + i)));
const buttons = rows.map((row) => {
  const button = new Node_("button");
  button.setAttribute("data-conn-check", "row");
  return row.appendChild(button);
});

const documentStub = {
  documentElement: new Node_("html"),
  addEventListener(name, handler) {
    (listeners[name] = listeners[name] || []).push(handler);
  },
  querySelector: () => null,
  querySelectorAll(selector) {
    return selector === "#conn-sections td.res" ? cells : [];
  },
  getElementById: () => null,
  createElement: (tag) => new Node_(tag),
};
global.document = documentStub;
global.window = {
  addEventListener() {},
  localStorage: { setItem() {}, getItem: () => null },
  setTimeout: () => 0,
};

// eslint-disable-next-line no-eval
(0, eval)(fs.readFileSync(process.argv[2], "utf8"));

function fire(name, detail) {
  for (const handler of listeners[name] || []) {
    handler({ detail, target: null });
  }
}

const shown = () => cells.map((td) => td.textContent);
const config = { path: "/connections/check?target=hl7" };
const out = { initial: shown() };

fire("htmx:beforeRequest", { elt: buttons[0] });
out.checking = shown();
fire("htmx:afterRequest", { elt: buttons[0], requestConfig: config, xhr: { status: 204 } });
out.after204 = shown();

// 200 では戻さない（結果は応答が差し替える）
fire("htmx:beforeRequest", { elt: buttons[0] });
fire("htmx:afterRequest", { elt: buttons[0], requestConfig: config, xhr: { status: 200 } });
out.after200 = shown();

process.stdout.write(JSON.stringify(out) + "\n");
