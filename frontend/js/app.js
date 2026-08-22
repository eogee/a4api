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
    if (document.querySelector('form[lay-filter="config-form"] [name="target_dsh"]').checked) {
      targets.push('dsh');
    }
    var mtEl = document.querySelector('form[lay-filter="config-form"] [name="max_tokens"]');
    var mtVal = mtEl && mtEl.value !== undefined ? String(mtEl.value).trim() : '';
    return {
      name: val('name'),
      provider_id: val('provider_id'),
      api_key: val('api_key'),
      model: val('model'),
      targets: targets.join(','),
      max_tokens: mtVal === '' ? null : Number(mtVal)
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
        if ((c.targets || '').indexOf('dsh') !== -1) {
          text += s.current_dsh_model
            ? ' · dsh: ' + s.current_dsh_model
            : ' · dsh 待配置';
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
    else if (data.index === 2 && !skillData) loadSkills();
  });

  /* ---------- 卡片 ---------- */
  function targetBadges(targets) {
    var list = (targets || 'claude').split(',');
    var html = '';
    list.forEach(function (t) {
      if (t === 'codex') html += '<span class="target-badge target-codex">Codex</span>';
      else if (t === 'dsh') html += '<span class="target-badge target-dsh">dsh</span>';
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
    var hasDsh = (targets || '').indexOf('dsh') !== -1;
    var restartHtml = hasClaude
      ? '<div class="layui-form" style="margin-top:16px;">' +
          '<input type="checkbox" id="chk-restart" lay-skin="primary" title="切换后重启 Claude Code（若正在运行）">' +
        '</div>'
      : '';
    var codexNote = hasCodex
      ? '<p style="font-size:12px;color:#8a8e94;margin-top:10px;">Codex 配置写入后需重启 Codex 才生效</p>'
      : '';
    var dshNote = hasDsh
      ? '<p style="font-size:12px;color:#8a8e94;margin-top:10px;">dsh 配置热加载，新会话即生效</p>'
      : '';
    layer.open({
      type: 1,
      title: '确认切换',
      area: ['420px', 'auto'],
      content: '<div style="padding:20px 24px;">' +
        '<p style="font-size:15px;">确定切换到「' + escapeHtml(name) + '」？</p>' +
        restartHtml + codexNote + dshNote + '</div>',
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
            '<label class="layui-form-label">输出上限</label>' +
            '<div class="layui-input-block"><input type="number" name="max_tokens" class="layui-input" min="1" step="1" placeholder="留空自动兜底（131072）；dsh 目标生效"></div>' +
          '</div>' +
          '<div class="layui-form-item">' +
            '<label class="layui-form-label">应用目标</label>' +
            '<div class="layui-input-block target-checkboxes">' +
              '<input type="checkbox" name="target_claude" title="Claude Code" lay-skin="primary" checked>' +
              '<input type="checkbox" name="target_codex" title="Codex" lay-skin="primary">' +
              '<input type="checkbox" name="target_dsh" title="dsh" lay-skin="primary">' +
            '</div>' +
            '<div class="layui-form-mid layui-word-aux" style="margin-left:110px;">Codex / dsh 需使用 OpenAI 兼容接口</div>' +
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
          if (c.max_tokens) {
            document.querySelector('input[name="max_tokens"]').value = c.max_tokens;
          }
          var targets = (c.targets || 'claude').split(',');
          document.querySelector('input[name="target_claude"]').checked = targets.indexOf('claude') !== -1;
          document.querySelector('input[name="target_codex"]').checked = targets.indexOf('codex') !== -1;
          document.querySelector('input[name="target_dsh"]').checked = targets.indexOf('dsh') !== -1;
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
          layer.msg('请至少选择一个应用目标（Claude Code / Codex / dsh）', { icon: 2 });
          return;
        }
        if (data.max_tokens != null && (!Number.isInteger(data.max_tokens) || data.max_tokens < 1)) {
          layer.msg('最大输出上限需为正整数', { icon: 2 });
          return;
        }
        // Codex / dsh 需使用 OpenAI 兼容接口：保存前拦截 Anthropic 服务商 + 勾选相应目标
        var selProvider = providers.find(function (p) { return p.id === Number(data.provider_id); });
        var needOpenai = data.targets.indexOf('codex') !== -1 || data.targets.indexOf('dsh') !== -1;
        if (needOpenai && selProvider && selProvider.api_type !== 'openai') {
          layer.msg('Codex / dsh 需使用 OpenAI 兼容接口，请更换服务商或去掉对应目标', { icon: 2 });
          return;
        }
        var body = {
          name: data.name,
          provider_id: Number(data.provider_id),
          model: data.model,
          targets: data.targets
        };
        if (data.api_key) body.api_key = data.api_key;
        body.max_tokens = data.max_tokens;  // 显式置空=清除，回到自动兜底

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
    var notesHtml = '<div class="update-notes">' + (notes ? renderMarkdown(notes) : '暂无更新说明') + '</div>';
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

  /* ---------- 技能管理 ---------- */
  var TOOL_LABEL = { claude: 'Claude', codex: 'Codex', dsh: 'dsh' };
  var skillView = 'global'; // global | project
  var skillData = null;
  var migrationBusy = false; // 迁移/适配执行中：阻塞其他技能操作

  /* 迁移执行期间拦截一切点击（捕获阶段），进度层之外无任何可操作目标 */
  document.addEventListener('click', function (e) {
    if (!migrationBusy) return;
    e.preventDefault();
    e.stopPropagation();
  }, true);

  function endBadge(t) {
    if (t === 'codex') return '<span class="target-badge target-codex">Codex</span>';
    if (t === 'dsh') return '<span class="target-badge target-dsh">dsh</span>';
    return '<span class="target-badge target-claude">Claude</span>';
  }

  function scopeLabel(scope, project) {
    return scope === 'global' ? '全局' : '项目「' + project + '」';
  }

  function findGroup(scope, project, name) {
    if (!skillData) return null;
    var pool = [];
    if (scope === 'global') pool = skillData.global || [];
    else {
      (skillData.projects || []).forEach(function (p) {
        if (p.project === project) pool = p.skills || [];
      });
    }
    var lowered = String(name || '').toLowerCase();
    return pool.find(function (g) { return g.name.toLowerCase() === lowered; }) || null;
  }

  function skillGroupCard(g, scope, project) {
    var dup = g.end_count > 1
      ? '<span class="target-badge dup-badge">' + g.end_count + ' 端存在</span>'
      : '';
    var badges = g.ends.map(endBadge).join('');
    var copies = g.copies.map(function (c) {
      var p = c.path || '';
      return '<div class="skill-copy" data-copy>' +
        '<span class="target-badge target-' + c.tool + '">' + TOOL_LABEL[c.tool] + '</span>' +
        '<span class="skill-copy-path" title="' + escapeHtml(p) + '">' + escapeHtml(p) + '</span>' +
        '<span class="skill-copy-actions">' +
          '<a href="javascript:;" data-sk="open" data-path="' + escapeHtml(p) + '">打开</a>' +
          '<a href="javascript:;" data-sk="delcopy" data-path="' + escapeHtml(p) + '">删除</a>' +
        '</span>' +
      '</div>';
    }).join('');
    var desc = g.description
      ? '<div class="card-meta skill-desc" title="' + escapeHtml(g.description) + '">' + escapeHtml(g.description) + '</div>'
      : '<div class="card-meta skill-desc skill-desc-none">无描述</div>';
    return '' +
      '<div class="config-card skill-card" data-group="' + escapeHtml(g.name) + '" data-scope="' + scope + '" data-project="' + escapeHtml(project || '') + '">' +
        '<div class="skill-badges">' + badges + dup + '</div>' +
        '<div class="card-name">' + escapeHtml(g.name) + '</div>' +
        desc +
        '<div class="skill-copies">' + copies + '</div>' +
        '<div class="card-actions">' +
          '<button class="layui-btn layui-btn-sm layui-btn-normal" data-sk="migrate">迁移…</button>' +
          '<button class="layui-btn layui-btn-sm" data-sk="preview" data-path="' + escapeHtml((g.copies[0] || {}).path || '') + '">预览</button>' +
        '</div>' +
      '</div>';
  }

  function renderSkills() {
    var box = document.getElementById('skills-content');
    if (!skillData) { box.innerHTML = '<div class="empty-tip">加载中…</div>'; return; }
    if (skillView === 'global') {
      box.classList.add('card-grid');
      var gs = skillData.global || [];
      if (!gs.length) {
        box.innerHTML = '<div class="empty-tip">三个工具的全局目录还没有任何 skill<br>' +
          '<span style="font-size:12px;">~/.claude/skills · ~/.codex/skills · ~/.dsh/skills</span></div>';
        return;
      }
      box.innerHTML = gs.map(function (g) { return skillGroupCard(g, 'global', ''); }).join('');
      return;
    }
    var projects = skillData.projects || [];
    box.classList.remove('card-grid');
    if (!projects.length) {
      box.innerHTML = '<div class="empty-tip">未发现任何含 skill 的项目，可点击右上角「项目根目录」调整扫描范围</div>';
      return;
    }
    var html = '';
    projects.forEach(function (p) {
      html += '<div class="proj-block">' +
        '<div class="proj-head">' +
          '<span class="proj-name">' + escapeHtml(p.project) + '</span>' +
          '<span class="proj-root" title="' + escapeHtml(p.root) + '">' + escapeHtml(p.root) + '</span>' +
          '<button class="layui-btn layui-btn-xs" data-sk="adapt" data-project="' + escapeHtml(p.project) + '">一键适配三端</button>' +
        '</div>';
      if (!p.skills.length) {
        html += '<div class="empty-tip proj-empty">该项目下没有 skill</div>';
      } else {
        html += '<div class="proj-grid">' + p.skills.map(function (g) {
          return skillGroupCard(g, 'project', p.project);
        }).join('') + '</div>';
      }
      html += '</div>';
    });
    box.innerHTML = html;
  }

  function loadSkills() {
    document.getElementById('skills-content').innerHTML = '<div class="empty-tip">加载中…</div>';
    apiGet('/skills/discover').then(function (d) {
      skillData = d;
      renderSkills();
    }).catch(function (e) {
      document.getElementById('skills-content').innerHTML =
        '<div class="empty-tip">加载失败：' + escapeHtml(e.message) + '</div>';
    });
  }

  function setSkillView(view) {
    skillView = view;
    document.querySelectorAll('#skills-scope-seg .seg-btn').forEach(function (b) {
      b.classList.toggle('seg-active', b.getAttribute('data-view') === view);
    });
    if (skillData) renderSkills();
  }

  /* ---- 迁移结果汇总提示 ---- */
  function migrationSummaryToast(res) {
    var tip = '已迁移 ' + res.migrated + ' 处';
    if (res.skipped) tip += '，跳过 ' + res.skipped;
    if (res.conflicts_trashed) tip += '，旧版入回收站 ' + res.conflicts_trashed;
    if (res.failed) tip += '，失败 ' + res.failed;
    layer.msg(tip, { icon: res.failed ? 2 : 1, time: 3200 });
  }

  /* ---- 迁移进度层：串行执行迁移任务并展示进度条 ----
   * 执行期间全屏遮罩且弹窗不可关闭，禁止用户进行其他点击与操作。
   * tasks: [{ label, source, targets }]，每个任务对应一次 /skills/migrate 调用；
   * 单个任务失败不中断后续任务，最终由 done(agg) 汇总提示。 */
  function runMigrateTasks(tasks, title, done) {
    var total = tasks.length;
    var agg = { migrated: 0, skipped: 0, conflicts_trashed: 0, failed: 0 };
    migrationBusy = true;

    function setProgress(finished, label, taskFailed) {
      var bar = document.getElementById('mig-progress-bar');
      var txt = document.getElementById('mig-progress-text');
      var pct = total ? Math.round((finished / total) * 100) : 100;
      if (bar) bar.style.width = pct + '%';
      if (txt) {
        txt.innerHTML = '<span class="mig-progress-count">（' + finished + '/' + total + '）</span>' +
          escapeHtml(label || '') + (taskFailed ? '<span class="mig-fail"> 失败</span>' : '');
      }
    }

    function run(i) {
      if (i >= total) {
        layer.close(layerIndex);
        done(agg);
        return;
      }
      var t = tasks[i];
      setProgress(i, t.label, false);
      apiSend('/skills/migrate', 'POST', { sources: [t.source], targets: t.targets })
        .then(function (res) {
          agg.migrated += res.migrated || 0;
          agg.skipped += res.skipped || 0;
          agg.conflicts_trashed += res.conflicts_trashed || 0;
          agg.failed += res.failed || 0;
          setProgress(i + 1, t.label, false);
          run(i + 1);
        })
        .catch(function () {
          agg.failed += 1;
          setProgress(i + 1, t.label, true);
          run(i + 1);
        });
    }

    var layerIndex = layer.open({
      type: 1,
      title: false,
      closeBtn: 0,
      btn: false,
      shade: [0.45, '#000'],
      shadeClose: false,
      skin: 'mig-progress-skin',
      area: ['460px', 'auto'],
      content:
        '<div class="mig-progress">' +
          '<div class="mig-progress-title">' + escapeHtml(title) + '</div>' +
          '<div class="layui-progress layui-progress-big">' +
            '<div class="layui-progress-bar mig-progress-bar" id="mig-progress-bar" style="width:0%;"></div>' +
          '</div>' +
          '<div class="mig-progress-text" id="mig-progress-text">准备中…（0/' + total + '）</div>' +
          '<div class="mig-progress-hint">迁移进行中，请勿进行其他操作</div>' +
        '</div>',
      success: function () { run(0); },
      end: function () { migrationBusy = false; }
    });
  }

  /* ---- 迁移弹窗：指定源副本与任意（工具×项目/全局）目标 ---- */
  function openMigrateDialog(scope, project, name) {
    if (migrationBusy) return;
    var g = findGroup(scope, project, name);
    if (!g) { layer.msg('数据已过期，请刷新后重试', { icon: 2 }); return; }

    function destRow(destScope, tool, destProject, srcCopy) {
      var isSrc = !!srcCopy
        && destScope === srcCopy.scope
        && tool === srcCopy.tool
        && (destProject || '') === (srcCopy.project || '');
      return '<label class="mig-item' + (isSrc ? ' mig-disabled' : '') + '">' +
        '<input type="checkbox" data-mig="' + destScope + '|' + tool + '|' + (destProject || '') + '"' + (isSrc ? ' disabled' : '') + '>' +
        '<span class="target-badge target-' + tool + '">' + TOOL_LABEL[tool] + '</span>' +
        '<span class="mig-place">' + (destScope === 'global' ? '全局' : escapeHtml(destProject)) + '</span>' +
      '</label>';
    }

    function buildPanel(srcIdx) {
      var src = g.copies[srcIdx] || {};
      var html = '<div class="mig-panel">' +
        '<div class="mig-section"><div class="mig-title">迁移哪一份？</div>' +
        g.copies.map(function (c, i) {
          return '<label class="mig-item">' +
            '<input type="radio" name="mig-src" value="' + i + '"' + (i === srcIdx ? ' checked' : '') + '>' +
            '<span class="target-badge target-' + c.tool + '">' + TOOL_LABEL[c.tool] + '</span>' +
            '<span class="mig-place" title="' + escapeHtml(c.path || '') + '">' + scopeLabel(c.scope, c.project) + '</span>' +
          '</label>';
        }).join('') + '</div>';
      html += '<div class="mig-section"><div class="mig-title">复制到哪些位置？（目标端同名旧版将移入回收站）</div>';
      html += '<div class="mig-group"><span class="mig-group-name">全局</span>';
      ['claude', 'codex', 'dsh'].forEach(function (t) { html += destRow('global', t, '', src); });
      html += '</div>';
      (skillData.projects || []).forEach(function (p) {
        html += '<div class="mig-group"><span class="mig-group-name">' + escapeHtml(p.project) + '</span>';
        ['claude', 'codex', 'dsh'].forEach(function (t) { html += destRow('project', t, p.project, src); });
        html += '</div>';
      });
      html += '</div></div>';
      return html;
    }

    function bindPanel(panel) {
      panel.addEventListener('change', function (e) {
        if (e.target.name !== 'mig-src') return;
        var idx = Number(e.target.value);
        // 换源后整体重建面板，让禁用态与新源保持一致
        var scroll = panel.scrollTop;
        var holder = document.createElement('div');
        holder.innerHTML = buildPanel(idx);
        var newPanel = holder.firstChild;
        panel.parentNode.replaceChild(newPanel, panel);
        bindPanel(newPanel);
        newPanel.scrollTop = scroll;
      });
    }

    layer.open({
      type: 1,
      title: '迁移「' + escapeHtml(name) + '」（复制，保留原件）',
      area: ['520px', 'auto'],
      content: buildPanel(0),
      btn: ['开始迁移', '取消'],
      success: function () {
        bindPanel(document.querySelector('.mig-panel'));
      },
      yes: function (index) {
        var srcIdx = 0;
        var radios = document.querySelectorAll('input[name="mig-src"]');
        radios.forEach(function (r, i) { if (r.checked) srcIdx = i; });
        var src = g.copies[srcIdx];
        var targets = [];
        document.querySelectorAll('[data-mig]:checked').forEach(function (cb) {
          var parts = cb.getAttribute('data-mig').split('|');
          targets.push({
            scope: parts[0], tool: parts[1],
            project: parts[2] === '' ? null : parts[2]
          });
        });
        if (!targets.length) { layer.msg('请至少勾选一个迁移目标', { icon: 2 }); return; }
        layer.close(index);
        var sourceDesc = { scope: src.scope, tool: src.tool, project: src.project, name: g.name };
        // 每个目标一个任务，进度条按目标粒度推进
        var tasks = targets.map(function (t) {
          return {
            source: sourceDesc,
            targets: [t],
            label: '「' + g.name + '」→ ' + TOOL_LABEL[t.tool] + ' · ' + scopeLabel(t.scope, t.project)
          };
        });
        runMigrateTasks(tasks, '迁移「' + g.name + '」（源端保留）', function (res) {
          migrationSummaryToast(res);
          loadSkills();
        });
      }
    });
  }

  /* ---- 项目一键适配三端：把项目内所有 skill 补齐到缺失的端 ---- */
  function adaptProject(project) {
    if (migrationBusy) return;
    var p = (skillData.projects || []).find(function (x) { return x.project === project; });
    if (!p || !p.skills.length) { layer.msg('该项目没有可迁移的 skill', { icon: 0 }); return; }
    var plan = []; // [{source, targets[], name, missing[]}]
    p.skills.forEach(function (g) {
      var missing = ['claude', 'codex', 'dsh'].filter(function (t) { return g.ends.indexOf(t) === -1; });
      if (!missing.length || !g.copies.length) return;
      plan.push({
        source: { scope: 'project', tool: g.copies[0].tool, project: project, name: g.name },
        targets: missing.map(function (t) { return { scope: 'project', tool: t, project: project }; }),
        name: g.name,
        missing: missing
      });
    });
    if (!plan.length) { layer.msg('该项目的 skill 已在 Claude / Codex / dsh 三端齐全', { icon: 1 }); return; }
    var lines = plan.map(function (x) {
      return '<li>「' + escapeHtml(x.name) + '」→ ' + x.missing.map(function (t) { return TOOL_LABEL[t]; }).join('、') + '</li>';
    }).join('');
    layer.open({
      type: 1,
      title: '一键适配三端 · ' + escapeHtml(project),
      area: ['440px', 'auto'],
      content: '<div style="padding:18px 24px;"><p style="margin-bottom:10px;">将按以下计划复制补齐（源端保留）：</p><ul class="adapt-list">' + lines + '</ul></div>',
      btn: ['执行迁移', '取消'],
      yes: function (index) {
        layer.close(index);
        // 逐个 skill 分别带各自缺失的目标，串行提交避免同名冲突交叉
        var tasks = plan.map(function (x) {
          return {
            source: x.source,
            targets: x.targets,
            label: '「' + x.name + '」→ ' + x.missing.map(function (t) { return TOOL_LABEL[t]; }).join('、')
          };
        });
        runMigrateTasks(tasks, '一键适配三端 · ' + project + '（源端保留）', function (res) {
          if (!res.failed) {
            layer.msg('适配完成：已迁移 ' + res.migrated + ' 处', { icon: 1, time: 2600 });
          } else {
            migrationSummaryToast(res);
          }
          loadSkills();
        });
      }
    });
  }

  /* ---- 预览 SKILL.md ---- */
  function previewSkill(path) {
    apiGet('/skills/content?path=' + encodeURIComponent(path)).then(function (c) {
      var fm = '';
      if (c.description) fm += '<p class="skill-fm-line"><b>描述</b>：' + escapeHtml(c.description) + '</p>';
      fm += '<p class="skill-fm-line"><b>路径</b>：<code>' + escapeHtml(c.path) + '</code></p>';
      var bodyHtml = c.body ? renderMarkdown(c.body) : '<p style="color:#8a8e94;">SKILL.md 没有正文内容</p>';
      layer.open({
        type: 1,
        title: '预览 · ' + escapeHtml(c.name),
        area: ['680px', 'auto'],
        content: '<div class="skill-preview"><div class="skill-fm">' + fm + '</div>' +
          '<div class="update-notes skill-md">' + bodyHtml + '</div></div>',
        btn: ['关闭']
      });
    }).catch(function (e) { layer.msg(e.message, { icon: 2 }); });
  }

  function openExplorer(path) {
    apiSend('/skills/open', 'POST', { path: path })
      .then(function () { layer.msg('已在资源管理器打开', { icon: 1, time: 1500 }); })
      .catch(function (e) { layer.msg(e.message, { icon: 2 }); });
  }

  function confirmDeleteCopy(path) {
    layer.confirm('确定删除这个 skill？<br><span style="font-size:12px;color:#8a8e94;">将移入回收站，30 天内可恢复</span>',
      { title: '删除确认' }, function (index) {
        apiSend('/skills/delete', 'POST', { path: path }).then(function (res) {
          layer.close(index);
          layer.msg(res.message || '已移入回收站', { icon: 1 });
          loadSkills();
        }).catch(function (e) { layer.msg(e.message, { icon: 2 }); });
      });
  }

  /* ---- 回收站 ---- */
  function openTrash() {
    layer.open({
      type: 1,
      title: '回收站（30 天内可恢复）',
      area: ['700px', 'auto'],
      content: '<div id="trash-box" style="padding:14px 18px;max-height:480px;overflow-y:auto;">加载中…</div>',
      btn: ['刷新状态', '关闭'],
      success: function () { loadTrashBox(); },
      yes: function () { loadTrashBox(); } // GET 即执行惰性过期清理，重取即得最新状态
    });
  }

  function loadTrashBox() {
    apiGet('/skills/trash').then(function (r) {
      var box = document.getElementById('trash-box');
      if (!box) return;
      var html = '';
      if (r.purged_expired) {
        html += '<p class="trash-notice">已自动清理 ' + r.purged_expired + ' 条超过 30 天的过期条目</p>';
      }
      if (!r.items.length) {
        html += '<div class="empty-tip" style="padding:40px 0;">回收站是空的</div>';
      } else {
        html += '<table class="layui-table trash-table"><thead><tr>' +
          '<th>名称</th><th>原位置</th><th>剩余天数</th><th class="trash-col-actions">操作</th>' +
        '</tr></thead><tbody>' + r.items.map(function (it) {
          var place = (it.scope === 'global' ? '全局' : ('项目「' + escapeHtml(it.project || '') + '」'))
            + ' · ' + (TOOL_LABEL[it.tool] || it.tool || '?');
          return '<tr>' +
            '<td>' + escapeHtml(it.name) + '</td>' +
            '<td class="trash-origin" title="' + escapeHtml(it.original_path) + '">' + place + '</td>' +
            '<td>' + it.days_left + ' 天</td>' +
            '<td class="trash-col-actions"><button class="layui-btn layui-btn-xs" data-trash="restore" data-id="' + it.id + '">恢复</button>' +
            '<button class="layui-btn layui-btn-xs layui-btn-danger layui-btn-primary" data-trash="purge" data-id="' + it.id + '">彻底删除</button></td>' +
          '</tr>';
        }).join('') + '</tbody></table>';
      }
      box.innerHTML = html;
    }).catch(function (e) {
      var box = document.getElementById('trash-box');
      if (box) box.innerHTML = '<div class="empty-tip">加载失败：' + escapeHtml(e.message) + '</div>';
    });
  }

  function trashAction(action, id) {
    var req;
    if (action === 'restore') {
      req = apiSend('/skills/trash/' + id + '/restore', 'POST', {});
    } else {
      req = fetch(API + '/skills/trash/' + id, { method: 'DELETE' }).then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || '请求失败'); });
        return r.json();
      });
    }
    req.then(function () {
      layer.msg(action === 'restore' ? '已恢复到原位置' : '已彻底删除', { icon: 1 });
      loadTrashBox();
      loadSkills();
    }).catch(function (e) { layer.msg(e.message, { icon: 2 }); });
  }

  /* ---- 项目根目录配置 ---- */
  function openRootsDialog() {
    apiGet('/skills/project-roots').then(function (r) {
      layer.open({
        type: 1,
        title: '项目根目录（每行一个，一级子目录视为项目）',
        area: ['520px', 'auto'],
        content: '<div style="padding:16px 20px;">' +
          '<textarea id="roots-input" class="layui-textarea" rows="5" placeholder="如 C:\\ProgramMine">' +
          escapeHtml((r.roots || []).join('\n')) + '</textarea>' +
          '<p style="font-size:12px;color:#8a8e94;margin-top:8px;">只收录其中含有至少一个 skill 的项目。</p></div>',
        btn: ['保存', '取消'],
        yes: function (index) {
          var roots = document.getElementById('roots-input').value.split('\n')
            .map(function (s) { return s.trim(); }).filter(Boolean);
          apiSend('/skills/project-roots', 'PUT', { roots: roots }).then(function () {
            layer.close(index);
            layer.msg('已保存', { icon: 1 });
            loadSkills();
          }).catch(function (e) { layer.msg(e.message, { icon: 2 }); });
        }
      });
    }).catch(function (e) { layer.msg(e.message, { icon: 2 }); });
  }

  /* ---- 迁移日志 ---- */
  function openMigrationLogs() {
    layer.open({
      type: 1,
      title: '迁移日志',
      area: ['720px', 'auto'],
      content: '<div id="miglog-box" style="padding:14px 18px;max-height:480px;overflow-y:auto;">加载中…</div>',
      btn: ['关闭'],
      success: function () {
        apiGet('/skills/migrations').then(function (list) {
          var box = document.getElementById('miglog-box');
          if (!box) return;
          if (!list.length) {
            box.innerHTML = '<div class="empty-tip" style="padding:40px 0;">暂无迁移记录</div>';
            return;
          }
          box.innerHTML = '<table class="layui-table trash-table"><thead><tr>' +
            '<th>时间</th><th>Skill</th><th>源</th><th>目标</th><th>结果</th>' +
          '</tr></thead><tbody>' + list.map(function (m) {
            return '<tr>' +
              '<td>' + escapeHtml(m.migrate_time) + '</td>' +
              '<td>' + escapeHtml(m.skill_name) + '</td>' +
              '<td>' + escapeHtml(m.source) + '</td>' +
              '<td>' + escapeHtml(m.target) + '</td>' +
              '<td class="' + (m.status === 'success' ? 'mig-ok' : 'mig-fail') + '">' +
                (m.status === 'success' ? '成功' : '失败：' + escapeHtml(m.detail)) + '</td>' +
            '</tr>';
          }).join('') + '</tbody></table>';
        }).catch(function (e) {
          var box = document.getElementById('miglog-box');
          if (box) box.innerHTML = '<div class="empty-tip">加载失败：' + escapeHtml(e.message) + '</div>';
        });
      }
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

  /* ---------- 技能管理事件 ---------- */
  document.querySelectorAll('#skills-scope-seg .seg-btn').forEach(function (btn) {
    btn.addEventListener('click', function () { setSkillView(btn.getAttribute('data-view')); });
  });

  document.getElementById('btn-skills-refresh').addEventListener('click', function () { loadSkills(); });
  document.getElementById('btn-skills-trash').addEventListener('click', openTrash);
  document.getElementById('btn-skills-roots').addEventListener('click', openRootsDialog);
  document.getElementById('btn-skills-migrations').addEventListener('click', openMigrationLogs);

  document.getElementById('skills-content').addEventListener('click', function (e) {
    var btn = e.target.closest('[data-sk]');
    if (!btn) return;
    var sk = btn.getAttribute('data-sk');
    if (sk === 'open') openExplorer(btn.getAttribute('data-path'));
    else if (sk === 'delcopy') confirmDeleteCopy(btn.getAttribute('data-path'));
    else if (sk === 'preview') previewSkill(btn.getAttribute('data-path'));
    else if (sk === 'adapt') adaptProject(btn.getAttribute('data-project'));
    else if (sk === 'migrate') {
      var card = btn.closest('.skill-card');
      openMigrateDialog(
        card.getAttribute('data-scope'),
        card.getAttribute('data-project') || '',
        card.getAttribute('data-group')
      );
    }
  });

  // 回收站 / 迁移日志等弹窗内的动态按钮：document 级委托
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-trash]');
    if (!btn) return;
    trashAction(btn.getAttribute('data-trash'), Number(btn.getAttribute('data-id')));
  });

  /* ---------- 初始化 ---------- */
  loadConfigs();
  loadStatus();
  loadProxyStatus();
  loadProviders();
  // 启动时静默检查一次更新；失败不打扰（silent=true 只弹更新，不弹错误）
  checkUpdate(true);
});
