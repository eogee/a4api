/* markdown.js — 轻量安全的 Markdown → HTML 渲染器。
 * 仅用于更新说明等展示文本。所有原文先转义再按标记生成 HTML，
 * 只输出白名单标签；链接 href 仅允许 http(s)，杜绝属性逃逸与脚本注入。
 * ES5 风格，与 app.js 保持一致；独立实现 esc（app.js 的 escapeHtml 在 layui.use 闭包内，非全局）。
 */
(function (window) {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // 行内：转义 → 提取 code span（占位符保护，避免其中 **、* 被误判）→ 粗体 → 斜体 → 链接 → 还原
  function inline(text) {
    var s = esc(text);
    var codeSpans = [];
    s = s.replace(/`([^`]+)`/g, function (m, c) {
      codeSpans.push('<code>' + esc(c) + '</code>');
      return '\u0000' + (codeSpans.length - 1) + '\u0000';
    });
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\s][^*]*?)\*(?=[^*]|$)/g, function (m, p, t) {
      return p + '<em>' + t + '</em>';
    });
    s = s.replace(/\[([^\]]+)\]\(([^)]*)\)/g, function (m, linkText, href) {
      href = href.trim();
      if (/^https?:\/\/[^\s]+$/i.test(href)) {
        return '<a href="' + esc(href) + '" target="_blank" rel="noopener">' + linkText + '</a>';
      }
      return linkText; // 非 http(s) 链接只保留文字
    });
    s = s.replace(/\u0000(\d+)\u0000/g, function (m, idx) {
      return codeSpans[Number(idx)];
    });
    return s;
  }

  function renderMarkdown(md) {
    var lines = String(md == null ? '' : md).replace(/\r\n?/g, '\n').split('\n');
    var out = [];
    var listType = null;
    var i = 0, n = lines.length;

    function closeList() {
      if (listType === 'ul') out.push('</ul>');
      else if (listType === 'ol') out.push('</ol>');
      listType = null;
    }

    while (i < n) {
      var line = lines[i];
      var t = line.trim();
      if (t === '') { closeList(); i++; continue; }

      // 围栏代码块
      if (/^```/.test(t)) {
        closeList();
        var code = [];
        i++;
        while (i < n && !/^```/.test(lines[i].trim())) { code.push(lines[i]); i++; }
        i++;
        out.push('<pre><code>' + esc(code.join('\n')) + '</code></pre>');
        continue;
      }

      // 标题
      var h = /^(#{1,6})\s+(.*)$/.exec(t);
      if (h) {
        closeList();
        var lv = h[1].length;
        out.push('<h' + lv + '>' + inline(h[2]) + '</h' + lv + '>');
        i++; continue;
      }

      // 引用
      if (/^>\s?/.test(t)) {
        closeList();
        var quote = [];
        while (i < n && /^>\s?/.test(lines[i])) { quote.push(lines[i].replace(/^>\s?/, '')); i++; }
        out.push('<blockquote>' + inline(quote.join('\n')) + '</blockquote>');
        continue;
      }

      // 无序列表
      var ul = /^[-*+]\s+(.*)$/.exec(t);
      if (ul) {
        if (listType !== 'ul') { closeList(); out.push('<ul>'); listType = 'ul'; }
        out.push('<li>' + inline(ul[1]) + '</li>');
        i++; continue;
      }

      // 有序列表
      var ol = /^\d+\.\s+(.*)$/.exec(t);
      if (ol) {
        if (listType !== 'ol') { closeList(); out.push('<ol>'); listType = 'ol'; }
        out.push('<li>' + inline(ol[1]) + '</li>');
        i++; continue;
      }

      // 段落：收集到空行或下一个块标记
      closeList();
      var para = [line];
      i++;
      while (i < n && lines[i].trim() !== '' &&
             !/^(#{1,6}\s|```|>\s?|[-*+]\s|\d+\.\s)/.test(lines[i].trim())) {
        para.push(lines[i]);
        i++;
      }
      out.push('<p>' + inline(para.join('<br>')) + '</p>');
    }
    closeList();
    return out.join('\n');
  }

  window.renderMarkdown = renderMarkdown;
})(window);
