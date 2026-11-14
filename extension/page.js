// The two functions the extension runs inside a web page. Each must be
// self-contained: Chrome copies the function's text into the page, so it
// cannot use anything defined outside itself.

// Read the page as text: its visible words in reading order, with every
// link, button and field numbered like [12] so JARVIS can refer to it.
// With wait set, it first gives a page that is still drawing itself (chat
// apps, mail, anything built by scripts) a few seconds to settle.
async function jarvisReadPage(wait) {
  const snapshot = () => {
  const INTERACTIVE = "a[href], button, input, select, textarea, summary, [role=button], [role=link], [role=tab], " +
    "[role=menuitem], [role=checkbox], [role=radio], [role=option], [role=switch], [role=textbox], [role=searchbox], " +
    "[role=combobox], [contenteditable=''], [contenteditable=true], [onclick], [tabindex]:not([tabindex='-1']), " +
    "[role=row][tabindex], [role=listitem][tabindex], [role=gridcell][tabindex], [role=treeitem]";
  // Many sites make plain boxes clickable (a chat in a list, a card). The
  // hand cursor gives them away; only the outermost such box is numbered.
  const clickable = (el) => {
    if (el === document.body || !el.parentElement) return false;
    if (getComputedStyle(el).cursor !== "pointer" || getComputedStyle(el.parentElement).cursor === "pointer") return false;
    return !!clean(el.getAttribute("aria-label") || el.innerText);
  };
  const BLOCK = new Set(["P", "DIV", "LI", "TR", "SECTION", "ARTICLE", "HEADER", "FOOTER", "MAIN", "NAV", "ASIDE", "UL", "OL",
    "TABLE", "H1", "H2", "H3", "H4", "H5", "H6", "BR", "FORM", "FIELDSET", "DETAILS", "BLOCKQUOTE", "PRE", "DD", "DT"]);
  const MAX_ELEMENTS = 500, MAX_TEXT = 60000;

  document.querySelectorAll("[data-jarvis-ref]").forEach((e) => e.removeAttribute("data-jarvis-ref"));
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  };

  const elements = [];
  let out = "";
  const describe = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    let kind = el.getAttribute("role") || (tag === "div" || tag === "span" || tag === "li" ? "clickable" : tag);
    if (tag === "a") kind = "link";
    if (tag === "input") kind = ["checkbox", "radio", "submit", "button", "file", "range"].includes(type) ? type : "field";
    if (tag === "textarea" || el.isContentEditable) kind = "field";
    if (tag === "select") kind = "dropdown";
    // The words of a <label>, without the text of the control inside it.
    const labelText = () => {
      if (!el.labels || !el.labels[0]) return "";
      const copy = el.labels[0].cloneNode(true);
      copy.querySelectorAll("input, select, textarea, button").forEach((c) => c.remove());
      return copy.textContent;
    };
    const label = clean(
      el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title") ||
      labelText() || el.getAttribute("alt") ||
      (tag === "input" || tag === "select" || tag === "textarea" ? el.getAttribute("name") : el.innerText) || el.value || ""
    ).slice(0, 120);
    const item = { ref: elements.length + 1, kind, label };
    const isPassword = type === "password";
    const auto = (el.getAttribute("autocomplete") || "").toLowerCase();
    if (isPassword) item.secret = "password";
    else if (/cc-|card/.test(auto) || /card.?number|cvv|cvc/i.test((el.name || "") + " " + (el.id || ""))) item.secret = "card";
    if (type === "search" || kind === "searchbox" || /search|query|^q$/i.test((el.name || "") + " " + (el.getAttribute("aria-label") || "") + " " + (el.getAttribute("placeholder") || ""))) item.search = true;
    if (kind === "field" && !isPassword) item.value = clean(el.isContentEditable ? el.innerText : el.value).slice(0, 200);
    if (kind === "checkbox" || kind === "radio") item.checked = !!el.checked;
    if (kind === "dropdown") {
      item.value = clean(el.options[el.selectedIndex] && el.options[el.selectedIndex].text);
      item.options = Array.from(el.options).slice(0, 30).map((o) => clean(o.text));
    }
    if (tag === "a") item.href = el.href;
    if (el.disabled || el.getAttribute("aria-disabled") === "true") item.disabled = true;
    if (tag === "button" || type === "submit" || kind === "button") item.button = true;
    return item;
  };

  const walk = (node) => {
    if (out.length > MAX_TEXT) return;
    if (node.nodeType === Node.TEXT_NODE) {
      const text = clean(node.nodeValue);
      if (text) out += text + " ";
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tag = node.tagName;
    if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "IFRAME", "CANVAS", "HEAD"].includes(tag)) return;
    if (node.getAttribute("aria-hidden") === "true" || !visible(node)) return;
    const block = BLOCK.has(tag);
    if (block && !out.endsWith("\n")) out += "\n";
    if (/^H[1-6]$/.test(tag)) out += "#".repeat(Number(tag[1])) + " ";
    if ((node.matches(INTERACTIVE) || clickable(node)) && elements.length < MAX_ELEMENTS) {
      const item = describe(node);
      node.setAttribute("data-jarvis-ref", String(item.ref));
      elements.push(item);
      let line = `[${item.ref}] ${item.kind}`;
      if (item.label) line += ` "${item.label}"`;
      if (item.value !== undefined && item.value !== item.label) line += ` = "${item.value}"`;
      if (item.checked !== undefined) line += item.checked ? " (ticked)" : " (not ticked)";
      if (item.options) line += ` options: ${item.options.join(" | ")}`;
      if (item.secret) line += ` (${item.secret}: JARVIS never fills this in)`;
      if (item.disabled) line += " (disabled)";
      out += line + " ";
      // The text inside a link or button is already its label; fields have none.
      if (item.kind !== "field" && item.kind !== "dropdown" && !node.querySelector(INTERACTIVE)) { if (block) out += "\n"; return; }
      if (item.kind === "field" || item.kind === "dropdown") { if (block) out += "\n"; return; }
    }
    for (const child of node.childNodes) walk(child);
    if (block && !out.endsWith("\n")) out += "\n";
  };
  walk(document.body);

  return {
    title: document.title,
    url: location.href,
    text: out.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim().slice(0, MAX_TEXT),
    elements,
    scroll: { y: Math.round(scrollY), height: Math.round(document.documentElement.scrollHeight), view: Math.round(innerHeight) },
  };
  };

  let page = snapshot();
  if (!wait) return page;
  // Settled = two looks, a moment apart, that see the same thing, with
  // something on the page to work with. Give up waiting after six seconds.
  const started = Date.now();
  while (Date.now() - started < 6000) {
    await new Promise((resolve) => setTimeout(resolve, 350));
    const next = snapshot();
    const same = next.elements.length === page.elements.length && next.text.length === page.text.length;
    page = next;
    if (same && (page.elements.length > 2 || Date.now() - started > 2500)) break;
  }
  return page;
}

// Do one thing on the page: click, type, choose from a dropdown, scroll,
// or press a key. Elements are found by the numbers jarvisReadPage gave them.
async function jarvisAct(action, args) {
  const flash = (el) => {  // show the user what JARVIS is touching
    const old = el.style.outline;
    el.style.outline = "3px solid #19e3f5";
    setTimeout(() => { el.style.outline = old; }, 900);
  };
  const find = () => {
    const el = document.querySelector(`[data-jarvis-ref="${args.ref}"]`);
    if (!el) return null;
    el.scrollIntoView({ block: "center", inline: "nearest" });
    flash(el);
    return el;
  };
  const key = (target, name) => {
    const init = { key: name, code: name, bubbles: true, cancelable: true, keyCode: name === "Enter" ? 13 : name === "Escape" ? 27 : name === "Tab" ? 9 : 0 };
    target.dispatchEvent(new KeyboardEvent("keydown", init));
    target.dispatchEvent(new KeyboardEvent("keypress", init));
    target.dispatchEvent(new KeyboardEvent("keyup", init));
  };
  const stale = { error: `Element ${args.ref} is no longer on the page. Read the page again; the numbers have changed.` };

  if (action === "scroll") {
    const amount = Math.round(innerHeight * 0.85);
    if (args.direction === "top") scrollTo(0, 0);
    else if (args.direction === "bottom") scrollTo(0, document.documentElement.scrollHeight);
    else scrollBy(0, args.direction === "up" ? -amount : amount);
    return { done: `scrolled ${args.direction || "down"}`, y: Math.round(scrollY), height: Math.round(document.documentElement.scrollHeight) };
  }

  if (action === "key") {
    const target = document.activeElement || document.body;
    key(target, args.key);
    if (args.key === "Enter" && target.form && typeof target.form.requestSubmit === "function") target.form.requestSubmit();
    return { done: `pressed ${args.key}` };
  }

  const el = find();
  if (!el) return stale;
  if (el.disabled) return { error: `Element ${args.ref} is disabled.` };

  if (action === "click") {
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
      el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
    el.click();
    return { done: "clicked" };
  }

  if (action === "select") {
    if (el.tagName !== "SELECT") return { error: `Element ${args.ref} is not a dropdown.` };
    const wanted = String(args.option).trim().toLowerCase();
    const option = Array.from(el.options).find((o) => o.text.trim().toLowerCase() === wanted) ||
      Array.from(el.options).find((o) => o.text.trim().toLowerCase().includes(wanted));
    if (!option) return { error: `No option like "${args.option}". Options: ${Array.from(el.options).map((o) => o.text.trim()).join(" | ")}` };
    el.value = option.value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return { done: `chose "${option.text.trim()}"` };
  }

  if (action === "type") {
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (type === "password") return { error: "JARVIS does not type into password fields." };
    el.focus();
    if (el.isContentEditable) {
      // Rich text boxes (chat apps, editors) listen for real typing events.
      if (args.clear !== false) { const range = document.createRange(); range.selectNodeContents(el); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range); }
      document.execCommand("insertText", false, args.text);
    } else if ("value" in el) {
      // Set the value the way the browser itself would, so sites built with
      // React and similar notice the change.
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, args.clear === false ? el.value + args.text : args.text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      return { error: `Element ${args.ref} is not something that can be typed into.` };
    }
    if (args.submit) {
      key(el, "Enter");
      if (el.form && typeof el.form.requestSubmit === "function") el.form.requestSubmit();
      if (el.isContentEditable) {
        // Some chat boxes ignore an Enter that did not come from a real
        // keyboard. If the words are still sitting there, press Send.
        await new Promise((resolve) => setTimeout(resolve, 400));
        if ((el.innerText || "").trim()) {
          let box = el.parentElement, send = null;
          for (let i = 0; i < 8 && box && !send; i++, box = box.parentElement) {
            send = Array.from(box.querySelectorAll("button, [role=button]")).find((b) =>
              /^send\b/i.test((b.getAttribute("aria-label") || b.getAttribute("title") || b.innerText || "").trim()) ||
              b.querySelector("[data-icon*=send]"));
          }
          if (send) { send.click(); return { done: "typed and pressed Send" }; }
          return { done: "typed and pressed Enter, but the text is still in the box: find and click the Send button" };
        }
      }
    }
    return { done: args.submit ? "typed and pressed Enter" : "typed" };
  }
  return { error: `Unknown action: ${action}` };
}
