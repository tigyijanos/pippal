/* notices.js — the open-source NOTICES viewer (notices_card.py).
 *
 * Contains renderNotices + _mdToHtml helpers.
 * renderRelease (which relies on a separate release-history layer) is NOT included here.
 * Shared singletons come from app-core.js. */
"use strict";

import { U, API, t, view, footer } from "./app-core.js";

// ------------------------------------------------------------------
// Compact Markdown → HTML renderer — notices surface only.
//
// Handles the subset that appears in THIRD_PARTY.md / NOTICES.txt:
//   headings (#…######), GFM tables (|…|), **bold**, `inline code`,
//   [label](url) links, unordered lists (*/- lines), blank-line
//   paragraphs, and horizontal rules (---).
//
// Safety: all user-visible text is HTML-escaped before any inline
// pattern is applied, so raw < > & in the notices file cannot inject
// markup. The notices file is a trusted local asset, but correctness
// costs nothing here.
// ------------------------------------------------------------------
function _mdToHtml(md) {
  function esc(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Apply inline patterns to an already-escaped string fragment.
  // Order: code spans first (protect content), then links, bold, italic.
  function inline(s) {
    // `code`
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    // [label](url) — only http(s) links; esc was already applied so
    // the raw text of label/url is safe.
    s = s.replace(
      /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    );
    // **bold**
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // *italic* (single star, not adjacent to another star)
    s = s.replace(/(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)/g, "<em>$1</em>");
    return s;
  }

  var lines = md.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  var out = [];
  var i = 0;
  var inList = false;
  var inPara = false;

  function closeList() {
    if (inList) {
      out.push("</ul>");
      inList = false;
    }
  }
  function closePara() {
    if (inPara) {
      out.push("</p>");
      inPara = false;
    }
  }

  while (i < lines.length) {
    var raw = lines[i];
    i++;

    // --- Heading
    var hm = raw.match(/^(#{1,6})\s+(.*)/);
    if (hm) {
      closeList();
      closePara();
      var lvl = hm[1].length;
      out.push("<h" + lvl + ">" + inline(esc(hm[2])) + "</h" + lvl + ">");
      continue;
    }

    // --- Horizontal rule (--- / *** / ___)
    if (/^(\s*[-*_]){3,}\s*$/.test(raw)) {
      closeList();
      closePara();
      out.push("<hr>");
      continue;
    }

    // --- GFM table — a row starts and ends with |
    if (/^\|.+\|/.test(raw)) {
      closeList();
      closePara();
      // Collect all consecutive table lines.
      var tableLines = [raw];
      while (i < lines.length && /^\|.+\|/.test(lines[i])) {
        tableLines.push(lines[i]);
        i++;
      }
      // Second line is the separator row (---|---), skip it.
      var headerCells = tableLines[0]
        .replace(/^\||\|$/g, "")
        .split("|")
        .map(function (c) {
          return "<th>" + inline(esc(c.trim())) + "</th>";
        });
      out.push(
        "<table><thead><tr>" + headerCells.join("") + "</tr></thead><tbody>",
      );
      for (var ti = 2; ti < tableLines.length; ti++) {
        var rowCells = tableLines[ti]
          .replace(/^\||\|$/g, "")
          .split("|")
          .map(function (c) {
            return "<td>" + inline(esc(c.trim())) + "</td>";
          });
        out.push("<tr>" + rowCells.join("") + "</tr>");
      }
      out.push("</tbody></table>");
      continue;
    }

    // --- Unordered list item (* or -)
    var lim = raw.match(/^[\s]*[-*]\s+(.*)/);
    if (lim) {
      closePara();
      if (!inList) {
        out.push("<ul>");
        inList = true;
      }
      out.push("<li>" + inline(esc(lim[1])) + "</li>");
      continue;
    }

    // --- Blank line
    if (raw.trim() === "") {
      closeList();
      closePara();
      continue;
    }

    // --- Paragraph text
    closeList();
    if (!inPara) {
      out.push("<p>");
      inPara = true;
    } else {
      out.push(" ");
    }
    out.push(inline(esc(raw)));
  }
  closeList();
  closePara();
  return out.join("\n");
}

// ------------------------------------------------------------------
// NOTICES viewer (notices_card.py _NoticesViewer).
// ------------------------------------------------------------------
export function renderNotices() {
  return API.call("get_notices").then(function (text) {
    document.getElementById("brand-name").textContent = t(
      "notices.window_title",
    );
    footer.classList.add("hidden");
    view.innerHTML = "";
    var bodyEl = U.el("div", {
      class: "notices-rendered",
      testid: "notices-body",
      html: _mdToHtml(text),
    });
    view.appendChild(bodyEl);
  });
}
