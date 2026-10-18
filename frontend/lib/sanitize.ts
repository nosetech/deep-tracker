// フィード本文（信頼できない HTML）を許可リスト方式でサニタイズする。ブラウザ上でのみ使う。

const ALLOWED_TAGS = new Set([
  "a",
  "abbr",
  "b",
  "blockquote",
  "br",
  "code",
  "dd",
  "del",
  "div",
  "dl",
  "dt",
  "em",
  "figcaption",
  "figure",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "img",
  "ins",
  "li",
  "mark",
  "ol",
  "p",
  "pre",
  "q",
  "s",
  "small",
  "span",
  "strong",
  "sub",
  "sup",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
]);

// 中身ごと捨てるタグ（テキストも表示しない）
const DROP_WITH_CONTENT = new Set([
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "noscript",
  "template",
  "svg",
  "math",
  "form",
  "input",
  "button",
  "select",
  "textarea",
  "link",
  "meta",
  "base",
  "title",
  "head",
]);

const ALLOWED_ATTRS: Record<string, string[]> = {
  a: ["href", "title"],
  img: ["src", "alt", "title", "width", "height"],
  td: ["colspan", "rowspan"],
  th: ["colspan", "rowspan"],
  abbr: ["title"],
};

function safeUrl(value: string, schemes: string[]): boolean {
  try {
    return schemes.includes(
      new URL(value, "https://invalid.example/").protocol,
    );
  } catch {
    return false;
  }
}

function clean(node: Node, out: Node, doc: Document) {
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) {
      out.appendChild(doc.createTextNode(child.textContent ?? ""));
      continue;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) continue;
    const el = child as Element;
    const tag = el.tagName.toLowerCase();
    if (DROP_WITH_CONTENT.has(tag)) continue;
    if (!ALLOWED_TAGS.has(tag)) {
      // 未許可タグは外して中身だけ残す
      clean(el, out, doc);
      continue;
    }
    const copy = doc.createElement(tag);
    for (const attr of ALLOWED_ATTRS[tag] ?? []) {
      const v = el.getAttribute(attr);
      if (v === null) continue;
      if (attr === "href" && !safeUrl(v, ["http:", "https:", "mailto:"]))
        continue;
      if (attr === "src" && !safeUrl(v, ["http:", "https:"])) continue;
      copy.setAttribute(attr, v);
    }
    if (tag === "a") {
      copy.setAttribute("target", "_blank");
      copy.setAttribute("rel", "noopener noreferrer nofollow");
    }
    if (tag === "img") {
      copy.setAttribute("loading", "lazy");
      copy.setAttribute("referrerpolicy", "no-referrer");
    }
    clean(el, copy, doc);
    out.appendChild(copy);
  }
}

export function sanitizeHtml(html: string): string {
  const src = new DOMParser().parseFromString(html, "text/html");
  const dst = document.implementation.createHTMLDocument("");
  clean(src.body, dst.body, dst);
  return dst.body.innerHTML;
}
