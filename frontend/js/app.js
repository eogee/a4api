layui.use(['layer', 'form', 'element'], function () {
  var layer = layui.layer;
  var form = layui.form;
  var element = layui.element;
  var API = '/api/v1';

  var providerReturnToConfig = false;

  /* ---------- 工具 ---------- */
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function apiGet(path) {
    return fetch(API + path).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || '请求失败'); });
      return r.json();
    });
  }

  function apiSend(path, method, body) {
    return fetch(API + path, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || '请求失败'); });
      return r.json();
    });
  }

  /* 从当前打开的配置表单读取值（不依赖 form.getData，兼容性更好） */
  function readFormValues() {
    function val(name) {
      var el = document.querySelector('form[lay-filter="config-form"] [name="' + name + '"]');
      return el ? el.value : '';
    }
    var targets = [];
    if (document.querySelector('form[lay-filter="config-form"] [name="target_claude"]').checked) {
      targets.push('claude');
    }
    if (document.querySelector('form[lay-filter="config-form"] [name="target_codex"]').checked) {
      targets.push('codex');
    }
    return {
      name: val('name'),
      provider_id: val('provider_id'),
      api_key: val('api_key'),
      model: val('model'),
      targets: targets.join(',')
    };
  }

  /* ---------- 状态栏 ---------- */
  function loadStatus() {
    apiGet('/status').then(function (s) {
      var el = document.getElementById('status-text');
      if (s.active_config) {
        var c = s.active_config;
        var pname = c.provider ? c.provider.name : ('#' + c.provider_id);
        var text = c.name + '（' + pname + ' · ' + c.model + '）';
        if (s.current_model && s.current_model !== c.model) {
          text += '  ⚠ 配置文件内为 ' + s.current_model;
        }
        if ((c.targets || '').indexOf('codex') !== -1) {
          text += s.current_codex_model
            ? ' · Codex: ' + s.current_codex_model
            : ' · Codex 待配置';
        }
        el.textContent = text;
        el.classList.add('status-active');
      } else {
        el.textContent = '未设置（使用默认配置）';
        el.classList.remove('status-active');
      }
    }).catch(function (e) {
      document.getElementById('status-text').textContent = '状态获取失败';
    });
  }

  /* ---------- 代理服务开关 ---------- */
  function loadProxyStatus() {
    apiGet('/proxy/status').then(function (s) {
      var sw = document.getElementById('proxy-switch');
      sw.checked = !!s.running;
      sw.disabled = !s.running;
      document.getElementById('proxy-label').textContent =
        s.running ? '代理服务（运行中）' : '代理服务';
      form.render('switch');
    }).catch(function () {});
  }

  form.on('switch(proxy-switch)', function (data) {
    if (data.elem.checked) return; // 只允许关闭，不允许手动开启
    layer.confirm(
      '关闭后当前 OpenAI 服务商将无法使用，需要重新切换配置才能恢复。确定关闭代理服务吗？',
      { title: '关闭代理服务' },
      function (index) {
        apiSend('/proxy/stop', 'POST', {}).then(function () {
          layer.close(index);
          layer.msg('代理服务已关闭', { icon: 1 });
          loadProxyStatus();
        }).catch(function (e) {
          layer.close(index);
          layer.msg(e.message, { icon: 2 });
          loadProxyStatus();
        });
      },
      function () {
        // 取消：恢复为开启状态
        document.getElementById('proxy-switch').checked = true;
        form.render('switch');
      }
    );
  });

  /* ---------- 供应商管理 ---------- */
  function protocolLabel(p) {
    if (p.api_type !== 'openai') return 'Anthropic';
    return p.native_responses ? 'OpenAI 兼容（原生 Responses）' : 'OpenAI 兼容（本地代理）';
  }

  function loadProviders() {
    apiGet('/providers').then(function (list) {
      var box = document.getElementById('provider-list');
      if (!list.length) {
        box.innerHTML = '<div class="empty-tip">还没有供应商，点击右上角「新增供应商」创建</div>';
        return;
      }
      var rows = list.map(function (p) {
        return '<tr>' +
          '<td>' + escapeHtml(p.name) + '</td>' +
          '<td class="provider-base">' + escapeHtml(p.api_base) + '</td>' +
          '<td>' + escapeHtml(protocolLabel(p)) + '</td>' +
          '<td>' + (p.is_custom ? '自定义' : '预置') + '</td>' +
          '<td class="provider-actions">' +
            '<button class="layui-btn layui-btn-xs" data-provider-action="edit" data-id="' + p.id + '">编辑</button>' +
            '<button class="layui-btn layui-btn-xs layui-btn-danger layui-btn-primary" data-provider-action="del" data-id="' + p.id + '" data-name="' + escapeHtml(p.name) + '">删除</button>' +
          '</td>' +
        '</tr>';
      }).join('');
      box.innerHTML =
        '<table class="layui-table"><thead><tr>' +
          '<th>名称</th><th>Base URL</th><th>协议</th><th>来源</th><th style="width:150px">操作</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table>';
    }).catch(function (e) {
      document.getElementById('provider-list').innerHTML =
        '<div class="empty-tip">加载失败：' + escapeHtml(e.message) + '</div>';
    });
  }

  function openProviderForm(editId) {
    var isEdit = editId != null;
    var html = '' +
      '<form class="layui-form provider-form" lay-filter="provider-form">' +
        '<div class="layui-form-item">' +
          '<label class="layui-form-label">名称</label>' +
          '<div class="layui-input-block"><input type="text" name="name" class="layui-input" placeholder="如：硅基流动"></div>' +
        '</div>' +
        '<div class="layui-form-item">' +
          '<label class="layui-form-label">Base URL</label>' +
          '<div class="layui-input-block"><input type="text" name="api_base" class="layui-input" placeholder="如：https://api.siliconflow.cn/v1"></div>' +
        '</div>' +
        '<div class="layui-form-item">' +
          '<label class="layui-form-label">协议类型</label>' +
          '<div class="layui-input-block"><select name="api_type" lay-filter="provider-form">' +
            '<option value="anthropic">Anthropic（Claude Code 原生）</option>' +
            '<option value="openai">OpenAI 兼容（走本地翻译代理）</option>' +
          '</select>' +
          '<div class="provider-hint" style="color:#8a8e94;">Codex 需使用 OpenAI 兼容（Responses）接口；上游原生支持 Responses 时可勾选下方开关直连，否则经本地代理。</div>' +
          '</div>' +
        '</div>' +
        '<div class="layui-form-item native-responses-item" style="display:none;">' +
          '<label class="layui-form-label">原生 Responses</label>' +
          '<div class="layui-input-block">' +
            '<input type="checkbox" name="native_responses" lay-skin="switch" lay-text="直连|代理">' +
            '<div class="provider-hint" style="color:#8a8e94;">上游原生支持 OpenAI Responses（如 DeepSeek）时开启：Codex 将直连上游，无需本地代理。</div>' +
          '</div>' +
        '</div>' +
        '<div class="layui-form-item">' +
          '<label class="layui-form-label">自定义</label>' +
          '<div class="layui-input-block"><input type="checkbox" name="is_custom" lay-skin="switch" checked></div>' +
        '</div>' +
      '</form>';

    layer.open({
      type: 1,
      title: isEdit ? '编辑供应商' : '新增供应商',
      area: ['500px', 'auto'],
      content: html,
      success: function () {
        if (isEdit) {
          apiGet('/providers/' + editId).then(function (p) {
            document.querySelector('input[name="name"]').value = p.name;
            document.querySelector('input[name="api_base"]').value = p.api_base;
            document.querySelector('select[name="api_type"]').value = p.api_type;
            document.querySelector('input[name="is_custom"]').checked = !!p.is_custom;
            document.querySelector('input[name="native_responses"]').checked = !!p.native_responses;
            toggleNativeResponses();
            form.render(null, 'provider-form');
          });
        } else {
          toggleNativeResponses();
          form.render(null, 'provider-form');
        }
      },
      btn: ['保存', '取消'],
      yes: function (index) {
        var name = document.querySelector('input[name="name"]').value.trim();
        var apiBase = document.querySelector('input[name="api_base"]').value.trim();
        var apiType = document.querySelector('select[name="api_type"]').value;
        var isCustom = document.querySelector('input[name="is_custom"]').checked;
        var nativeResponses = !!document.querySelector('input[name="native_responses"]').checked;
        if (!name || !apiBase) {
          layer.msg('请填写名称和 Base URL', { icon: 2 });
          return;
        }
        var body = { name: name, api_base: apiBase, api_type: apiType, native_responses: nativeResponses, is_custom: isCustom };
        var req = isEdit
          ? apiSend('/providers/' + editId, 'PUT', body)
          : apiSend('/providers', 'POST', body);
        req.then(function () {
          layer.close(index);
          layer.msg('保存成功', { icon: 1 });
          loadProviders();
          if (!isEdit && providerReturnToConfig) {
            providerReturnToConfig = false;
            element.tabChange('main-tab', 'configs');
            openForm(null);
          }
        }).catch(function (e) {
          layer.msg(e.message, { icon: 2 });
        });
      }
    });
  }

  function toggleNativeResponses() {
    var sel = document.querySelector('select[name="api_type"]');
    var item = document.querySelector('.native-responses-item');
    if (sel && item) {
      item.style.display = sel.value === 'openai' ? '' : 'none';
    }
  }

  form.on('select(provider-form)', function (data) {
    if (data.elem.name === 'api_type') {
      toggleNativeResponses();
    }
  });

  function confirmDeleteProvider(id, name) {
    layer.confirm('确定删除供应商「' + escapeHtml(name) + '」？' +
      '<br><span style="font-size:12px;color:#8a8e94;">该供应商下有配置方案时无法删除</span>',
      { title: '删除确认' }, function (index) {
        apiSend('/providers/' + id, 'DELETE', {}).then(function () {
          layer.close(index);
          layer.msg('已删除', { icon: 1 });
          loadProviders();
        }).catch(function (e) {
          layer.msg(e.message, { icon: 2 });
        });
      });
  }

  element.on('tab(main-tab)', function (data) {
    if (data.index === 1) loadProviders();
  });

  /* ---------- 卡片 ---------- */
  function targetBadges(targets) {
    var list = (targets || 'claude').split(',');
    var html = '';
    list.forEach(function (t) {
      if (t === 'codex') html += '<span class="target-badge target-codex">Codex</span>';
      else if (t === 'claude') html += '<span class="target-badge target-claude">Claude</span>';
    });
    return html;
  }

  function buildCard(c) {
    var activeCls = c.is_active ? ' card-active' : '';
    var badge = c.is_active ? '<div class="active-badge">使用中</div>' : '';
    var pname = c.provider ? c.provider.name : ('#' + c.provider_id);
    return '' +
      '<div class="config-card' + activeCls + '" data-id="' + c.id + '" data-targets="' + escapeHtml(c.targets) + '">' +
        badge +
        '<div class="card-name">' + escapeHtml(c.name) + '</div>' +
        '<div class="card-meta">' + escapeHtml(pname) + ' · ' + escapeHtml(c.model) + '</div>' +
        '<div class="card-targets">' + targetBadges(c.targets) + '</div>' +
        '<div class="card-actions">' +
          '<button class="layui-btn layui-btn-sm layui-btn-normal" data-action="switch" data-name="' + escapeHtml(c.name) + '">切换</button>' +
          '<button class="layui-btn layui-btn-sm" data-action="edit">编辑</button>' +
          '<button class="layui-btn layui-btn-sm layui-btn-danger layui-btn-primary" data-action="del" data-name="' + escapeHtml(c.name) + '">删除</button>' +
        '</div>' +
      '</div>';
  }

  function loadConfigs() {
    apiGet('/configs').then(function (list) {
      var grid = document.getElementById('card-grid');
      if (!list.length) {
        grid.innerHTML = '<div class="empty-tip">还没有配置方案，点击右上角「新增配置」创建</div>';
        return;
      }
      grid.innerHTML = list.map(buildCard).join('');
    }).catch(function (e) {
      document.getElementById('card-grid').innerHTML = '<div class="empty-tip">加载失败：' + escapeHtml(e.message) + '</div>';
    });
  }

  /* ---------- 切换 ---------- */
  function confirmSwitch(id, name, targets) {
    var hasClaude = (targets || '').indexOf('claude') !== -1;
    var hasCodex = (targets || '').indexOf('codex') !== -1;
    var restartHtml = hasClaude
      ? '<div class="layui-form" style="margin-top:16px;">' +
          '<input type="checkbox" id="chk-restart" lay-skin="primary" title="切换后重启 Claude Code（若正在运行）">' +
        '</div>'
      : '';
    var codexNote = hasCodex
      ? '<p style="font-size:12px;color:#8a8e94;margin-top:10px;">Codex 配置写入后需重启 Codex 才生效</p>'
      : '';
    layer.open({
      type: 1,
      title: '确认切换',
      area: ['420px', 'auto'],
      content: '<div style="padding:20px 24px;">' +
        '<p style="font-size:15px;">确定切换到「' + escapeHtml(name) + '」？</p>' +
        restartHtml + codexNote + '</div>',
      btn: ['确认切换', '取消'],
      success: function () {
        if (hasClaude) form.render('checkbox');
      },
      yes: function (index) {
        var chk = document.getElementById('chk-restart');
        var restart = !!(chk && chk.checked);
        doSwitch(id, restart, index);
      }
    });
  }

  function doSwitch(id, restart, layerIndex) {
    apiSend('/switch/' + id, 'POST', { restart: restart }).then(function (res) {
      layer.close(layerIndex);
      var info = res.process_info ? (res.process_info.detail || '') : '';
      layer.msg((res.message || '切换成功') + (info ? '，' + info : ''), { icon: 1, time: 3200 });
      loadConfigs();
      loadStatus();
      loadProxyStatus();
    }).catch(function (e) {
      layer.close(layerIndex);
      layer.msg(e.message, { icon: 2, time: 3000 });
    });
  }

  /* ---------- 新增 / 编辑 ---------- */
  function providerOptions(providers, selected) {
    return providers.map(function (p) {
      var sel = (selected && p.id === selected) ? ' selected' : '';
      var tag = p.api_type === 'openai' ? (p.native_responses ? '（原生Responses）' : '（OpenAI）') : '';
      return '<option value="' + p.id + '"' + sel + '>' + escapeHtml(p.name) + tag + '</option>';
    }).join('');
  }

  function openForm(editId) {
    apiGet('/providers').then(function (providers) {
      var isEdit = editId != null;
      var html = '' +
        '<form class="layui-form config-form" lay-filter="config-form">' +
          '<div class="layui-form-item">' +
            '<label class="layui-form-label">方案名称</label>' +
            '<div class="layui-input-block"><input type="text" name="name" class="layui-input" placeholder="如：日常开发 / 写作" value=""></div>' +
          '</div>' +
          '<div class="layui-form-item">' +
            '<label class="layui-form-label">服务商</label>' +
            '<div class="layui-input-block">' +
              '<select name="provider_id" lay-search>' +
                '<option value="">选择或搜索服务商</option>' + providerOptions(providers) +
              '</select>' +
              '<div class="provider-hint"><a href="javascript:;" id="link-add-provider">没有你的供应商？点此添加</a></div>' +
            '</div>' +
          '</div>' +
          '<div class="layui-form-item">' +
            '<label class="layui-form-label">API Key</label>' +
            '<div class="layui-input-block"><input type="password" name="api_key" class="layui-input" placeholder="' + (isEdit ? '留空则不修改' : '粘贴 API Key') + '"></div>' +
          '</div>' +
          '<div class="layui-form-item">' +
            '<label class="layui-form-label">模型</label>' +
            '<div class="layui-input-block"><input type="text" name="model" class="layui-input" placeholder="如：glm-4.7-flash"></div>' +
          '</div>' +
          '<div class="layui-form-item">' +
            '<label class="layui-form-label">应用目标</label>' +
            '<div class="layui-input-block target-checkboxes">' +
              '<input type="checkbox" name="target_claude" title="Claude Code" lay-skin="primary" checked>' +
              '<input type="checkbox" name="target_codex" title="Codex" lay-skin="primary">' +
            '</div>' +
            '<div class="layui-form-mid layui-word-aux" style="margin-left:110px;">Codex 需使用 OpenAI 兼容（Responses）接口</div>' +
          '</div>' +
        '</form>';

      if (isEdit) {
        apiGet('/configs/' + editId).then(function (c) {
          openFormLayer(isEdit, html, c, providers);
        });
      } else {
        openFormLayer(isEdit, html, null, providers);
      }
    });
  }

  function openFormLayer(isEdit, html, c, providers) {
    layer.open({
      type: 1,
      title: isEdit ? '编辑配置方案' : '新增配置方案',
      area: ['500px', 'auto'],
      content: html,
      success: function () {
        if (c) {
          document.querySelector('input[name="name"]').value = c.name;
          document.querySelector('select[name="provider_id"]').value = String(c.provider_id);
          document.querySelector('input[name="model"]').value = c.model;
          var targets = (c.targets || 'claude').split(',');
          document.querySelector('input[name="target_claude"]').checked = targets.indexOf('claude') !== -1;
          document.querySelector('input[name="target_codex"]').checked = targets.indexOf('codex') !== -1;
        }
        form.render(null, 'config-form');
        var link = document.getElementById('link-add-provider');
        if (link) {
          link.addEventListener('click', function () {
            providerReturnToConfig = true;
            layer.closeAll();
            element.tabChange('main-tab', 'providers');
            openProviderForm(null);
          });
        }
      },
      btn: ['保存', '取消'],
      yes: function (index) {
        var data = readFormValues();
        if (!data.name || !data.provider_id || !data.model) {
          layer.msg('请填写方案名称、服务商和模型', { icon: 2 });
          return;
        }
        if (!isEdit && !data.api_key) {
          layer.msg('请填写 API Key', { icon: 2 });
          return;
        }
        if (!data.targets) {
          layer.msg('请至少选择一个应用目标（Claude Code / Codex）', { icon: 2 });
          return;
        }
        // Codex 需使用 OpenAI 兼容（Responses）接口：保存前拦截 Anthropic 服务商 + 勾选 Codex
        var selProvider = providers.find(function (p) { return p.id === Number(data.provider_id); });
        if (data.targets.indexOf('codex') !== -1 && selProvider && selProvider.api_type !== 'openai') {
          layer.msg('Codex 需使用 OpenAI 兼容（Responses）接口，请更换服务商或去掉 Codex 目标', { icon: 2 });
          return;
        }
        var body = {
          name: data.name,
          provider_id: Number(data.provider_id),
          model: data.model,
          targets: data.targets
        };
        if (data.api_key) body.api_key = data.api_key;

        var req = isEdit
          ? apiSend('/configs/' + c.id, 'PUT', body)
          : apiSend('/configs', 'POST', body);

        req.then(function () {
          layer.close(index);
          layer.msg('保存成功', { icon: 1 });
          loadConfigs();
        }).catch(function (e) {
          layer.msg(e.message, { icon: 2 });
        });
      }
    });
  }

  /* ---------- 删除 ---------- */
  function confirmDelete(id, name) {
    layer.confirm('确定删除「' + escapeHtml(name) + '」？', { title: '删除确认' }, function (index) {
      apiSend('/configs/' + id, 'DELETE', {}).then(function () {
        layer.close(index);
        layer.msg('已删除', { icon: 1 });
        loadConfigs();
        loadStatus();
      }).catch(function (e) {
        layer.msg(e.message, { icon: 2 });
      });
    });
  }

  /* ---------- 自动更新 ---------- */
  var updateDlTimer = null;

  function fmtBytes(n) {
    if (!n) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (n >= 10 ? n.toFixed(0) : n.toFixed(1)) + ' ' + units[i];
  }

  function checkUpdate(silent) {
    apiGet('/update/check').then(function (r) {
      if (r.status === 'update_available') {
        // 之前已下载校验通过 → 直接提示应用，避免重复下载
        if (r.downloaded) {
          showApplyConfirm(r.downloaded_version || r.latest_version);
        } else {
          showUpdatePrompt(r);
        }
      } else if (!silent) {
        if (r.status === 'up_to_date') {
          layer.msg('已是最新版本 v' + escapeHtml(r.current_version), { icon: 1 });
        } else if (r.status === 'ignored') {
          layer.msg('已忽略该版本（v' + escapeHtml(r.latest_version) + '）', { icon: 0 });
        } else if (r.status === 'too_old') {
          layer.msg(r.error || '当前版本过旧，请下载完整安装包更新', { icon: 2 });
        } else {
          layer.msg('检查更新失败：' + (r.error || '网络或服务器不可达'), { icon: 2 });
        }
      }
    }).catch(function (e) {
      if (!silent) layer.msg('检查更新失败：' + e.message, { icon: 2 });
    });
  }

  function showUpdatePrompt(r) {
    var notes = (r.notes || '').trim();
    var notesHtml = '<div class="update-notes">' + (notes ? escapeHtml(notes) : '暂无更新说明') + '</div>';
    if (r.notes_url && /^https:\/\//.test(r.notes_url)) {
      notesHtml += '<div class="update-notes-url"><a href="' + escapeHtml(r.notes_url) + '" target="_blank" rel="noopener">查看完整发布说明</a></div>';
    }
    layer.open({
      type: 1,
      title: '发现新版本 v' + escapeHtml(r.latest_version),
      area: ['460px', 'auto'],
      content: '<div class="update-panel">' +
        '<p class="update-versions">当前 <b>v' + escapeHtml(r.current_version) + '</b> → 最新 <b>v' + escapeHtml(r.latest_version) + '</b></p>' +
        notesHtml + '</div>',
      btn: ['立即下载更新', '忽略此版本', '暂不'],
      yes: function (index) {
        layer.close(index);
        startDownload(r.latest_version);
      },
      btn2: function (index) {
        layer.close(index);
        apiSend('/update/ignore', 'POST', { version: r.latest_version }).catch(function () {});
      },
      btn3: function (index) { layer.close(index); }
    });
  }

  function startDownload(version) {
    var index = layer.open({
      type: 1,
      title: '正在下载更新 v' + escapeHtml(version),
      area: ['440px', 'auto'],
      content: '<div class="update-download">' +
        '<div class="layui-progress layui-progress-big" lay-showpercent="true">' +
          '<div class="layui-progress-bar layui-bg-green" style="width:0%"></div>' +
        '</div>' +
        '<p class="update-download-status" id="update-dl-status">准备中…</p></div>',
      btn: ['取消下载'],
      yes: function (idx) {
        apiSend('/update/cancel', 'POST', {}).then(function () { layer.close(idx); }).catch(function () {});
      }
    });
    apiSend('/update/download', 'POST', { version: version }).then(function () {
      pollDownloadProgress(index, version);
    }).catch(function (e) {
      layer.close(index);
      layer.msg('开始下载失败：' + e.message, { icon: 2 });
    });
  }

  function pollDownloadProgress(layerIndex, version) {
    clearInterval(updateDlTimer);
    updateDlTimer = setInterval(function () {
      apiGet('/update/progress').then(function (p) {
        if (p.status === 'queued' || p.status === 'downloading') {
          var pct = p.total ? Math.min(100, Math.round(p.downloaded / p.total * 100)) : 0;
          var bar = document.querySelector('.update-download .layui-progress-bar');
          if (bar) bar.style.width = pct + '%';
          var st = document.getElementById('update-dl-status');
          if (st) st.textContent = '已下载 ' + fmtBytes(p.downloaded) + (p.total ? ' / ' + fmtBytes(p.total) : '');
        } else if (p.status === 'done') {
          clearInterval(updateDlTimer);
          layer.close(layerIndex);
          showApplyConfirm(version);
        } else if (p.status === 'cancelled') {
          clearInterval(updateDlTimer);
          layer.close(layerIndex);
          layer.msg('已取消下载', { icon: 0 });
        } else if (p.status === 'failed') {
          clearInterval(updateDlTimer);
          layer.close(layerIndex);
          layer.msg('下载失败：' + (p.error || '未知错误'), { icon: 2 });
        }
      }).catch(function () { /* 瞬时错误继续轮询 */ });
    }, 500);
  }

  function showApplyConfirm(version) {
    layer.open({
      type: 1,
      title: '更新包下载完成',
      area: ['420px', 'auto'],
      content: '<div class="update-panel">' +
        '<p>v' + escapeHtml(version) + ' 安装包已下载并通过 SHA256 校验。</p>' +
        '<p class="update-warn">是否现在运行安装程序完成更新？更新过程中 a4api 将自动关闭。</p></div>',
      btn: ['立即更新', '稍后'],
      yes: function (index) {
        layer.close(index);
        doApply();
      },
      btn2: function (index) { layer.close(index); }
    });
  }

  function doApply() {
    var tip = layer.msg('正在启动更新安装程序，a4api 即将关闭…', { icon: 1, time: 0 });
    apiSend('/update/apply', 'POST', {}).then(function () {
      // 应用随即退出，这里无需清理
    }).catch(function (e) {
      layer.close(tip);
      layer.msg('启动更新失败：' + e.message, { icon: 2 });
    });
  }

  /* ---------- 事件绑定 ---------- */
  document.getElementById('btn-add').addEventListener('click', function () {
    openForm(null);
  });

  document.getElementById('btn-add-provider').addEventListener('click', function () {
    providerReturnToConfig = false;
    openProviderForm(null);
  });

  document.getElementById('btn-check-update').addEventListener('click', function () {
    checkUpdate(false);
  });

  document.getElementById('card-grid').addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var card = btn.closest('.config-card');
    var id = Number(card.getAttribute('data-id'));
    var action = btn.getAttribute('data-action');
    if (action === 'switch') confirmSwitch(id, btn.getAttribute('data-name'), card.getAttribute('data-targets'));
    else if (action === 'edit') openForm(id);
    else if (action === 'del') confirmDelete(id, btn.getAttribute('data-name'));
  });

  document.getElementById('provider-list').addEventListener('click', function (e) {
    var btn = e.target.closest('[data-provider-action]');
    if (!btn) return;
    var id = Number(btn.getAttribute('data-id'));
    var action = btn.getAttribute('data-provider-action');
    if (action === 'edit') openProviderForm(id);
    else if (action === 'del') confirmDeleteProvider(id, btn.getAttribute('data-name'));
  });

  /* ---------- 初始化 ---------- */
  loadConfigs();
  loadStatus();
  loadProxyStatus();
  loadProviders();
  // 启动时静默检查一次更新；失败不打扰（silent=true 只弹更新，不弹错误）
  checkUpdate(true);
});
