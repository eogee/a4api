layui.use(['layer', 'form'], function () {
  var layer = layui.layer;
  var form = layui.form;
  var API = '/api/v1';

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
    return {
      name: val('name'),
      provider_id: val('provider_id'),
      api_key: val('api_key'),
      model: val('model'),
      temperature: val('temperature')
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

  /* ---------- 卡片 ---------- */
  function buildCard(c) {
    var activeCls = c.is_active ? ' card-active' : '';
    var badge = c.is_active ? '<div class="active-badge">使用中</div>' : '';
    var pname = c.provider ? c.provider.name : ('#' + c.provider_id);
    var temp = c.temperature != null ? c.temperature : 0.7;
    return '' +
      '<div class="config-card' + activeCls + '" data-id="' + c.id + '">' +
        badge +
        '<div class="card-name">' + escapeHtml(c.name) + '</div>' +
        '<div class="card-meta">' + escapeHtml(pname) + ' · ' + escapeHtml(c.model) + '</div>' +
        '<div class="card-meta">温度：' + escapeHtml(temp) + '</div>' +
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
  function confirmSwitch(id, name) {
    layer.open({
      type: 1,
      title: '确认切换',
      area: ['420px', 'auto'],
      content: '<div style="padding:20px 24px;">' +
        '<p style="font-size:15px;">确定切换到「' + escapeHtml(name) + '」？</p>' +
        '<label style="display:block;margin-top:16px;font-size:13px;color:#666;">' +
          '<input type="checkbox" id="chk-restart" style="margin-right:6px;">切换后重启 Claude Code（若正在运行）' +
        '</label></div>',
      btn: ['确认切换', '取消'],
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
      layer.msg('切换成功' + (info ? '，' + info : ''), { icon: 1, time: 2600 });
      loadConfigs();
      loadStatus();
    }).catch(function (e) {
      layer.close(layerIndex);
      layer.msg(e.message, { icon: 2, time: 3000 });
    });
  }

  /* ---------- 新增 / 编辑 ---------- */
  function providerOptions(providers, selected) {
    return providers.map(function (p) {
      var sel = (selected && p.id === selected) ? ' selected' : '';
      return '<option value="' + p.id + '"' + sel + '>' + escapeHtml(p.name) + '</option>';
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
            '<div class="layui-input-block"><select name="provider_id">' + providerOptions(providers) + '</select></div>' +
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
            '<label class="layui-form-label">温度</label>' +
            '<div class="layui-input-block"><input type="number" name="temperature" class="layui-input" value="0.7" step="0.1" min="0" max="2"></div>' +
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
      area: ['480px', 'auto'],
      content: html,
      success: function () {
        if (c) {
          document.querySelector('input[name="name"]').value = c.name;
          document.querySelector('select[name="provider_id"]').value = String(c.provider_id);
          document.querySelector('input[name="model"]').value = c.model;
          if (c.temperature != null) {
            document.querySelector('input[name="temperature"]').value = c.temperature;
          }
        }
        form.render(null, 'config-form');
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
        var temp = parseFloat(data.temperature);
        var body = {
          name: data.name,
          provider_id: Number(data.provider_id),
          model: data.model,
          temperature: isNaN(temp) ? 0.7 : temp
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

  /* ---------- 事件绑定 ---------- */
  document.getElementById('btn-add').addEventListener('click', function () {
    openForm(null);
  });

  document.getElementById('card-grid').addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var card = btn.closest('.config-card');
    var id = Number(card.getAttribute('data-id'));
    var action = btn.getAttribute('data-action');
    if (action === 'switch') confirmSwitch(id, btn.getAttribute('data-name'));
    else if (action === 'edit') openForm(id);
    else if (action === 'del') confirmDelete(id, btn.getAttribute('data-name'));
  });

  /* ---------- 初始化 ---------- */
  loadConfigs();
  loadStatus();
});
