"""出图任务面板：单页 UI + JSON API，全部由场景固定内核驱动。

图形界面是场景固定与一致性核验的主入口：
  - 选择场景来源 → 固定并提交
  - 修订列表显示场景指纹与跨节点一致性
  - 查看版本摘要、动画时刻、插件参数与真实像素
  - 任选两台节点比较渲染差值
命令行仅作辅助（见 README）。
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .compare import render_delta
from .errors import PinError
from .kernel import Kernel

INDEX_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>场景固定 · 出图任务面板</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
         background:#0d1117; color:#dbe2ec; }
  header { padding:12px 18px; background:#161c26; border-bottom:1px solid #2a3342;
           display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
  h1 { font-size:16px; margin:0; color:#ffd166; }
  h2 { font-size:13px; color:#8b98ab; text-transform:uppercase; letter-spacing:.08em; }
  button { background:#2d6cdf; color:#fff; border:0; border-radius:6px;
           padding:7px 14px; font:inherit; cursor:pointer; }
  button:hover { background:#3b7bef; }
  select { background:#0d1117; color:#dbe2ec; border:1px solid #2a3342; border-radius:6px;
           padding:6px 8px; font:inherit; }
  main { display:grid; grid-template-columns: 340px 1fr; gap:14px; padding:14px 18px; }
  .card { background:#161c26; border:1px solid #2a3342; border-radius:10px; padding:12px 14px; }
  .rev { cursor:pointer; margin-bottom:10px; }
  .rev:hover { border-color:#3b7bef; }
  .rev.sel { border-color:#ffd166; }
  .rev .hash { color:#7ee0a3; }
  .muted { color:#8b98ab; }
  .badge { display:inline-block; min-width:64px; text-align:center; border-radius:5px;
           padding:1px 8px; font-size:12px; margin-right:6px; }
  .ok { background:#12351f; color:#7ee0a3; border:1px solid #1f5c33; }
  .err { background:#3d1418; color:#ff9aa2; border:1px solid #6e2028; }
  .none { background:#222a36; color:#8b98ab; border:1px solid #2a3342; }
  table { border-collapse:collapse; width:100%; font-size:12.5px; }
  th, td { text-align:left; padding:4px 8px; border-bottom:1px solid #232c3a;
           vertical-align:top; word-break:break-all; }
  th { color:#8b98ab; font-weight:normal; }
  .banner { margin:14px 18px 0; padding:10px 14px; border-radius:8px;
            background:#3d1418; border:1px solid #6e2028; color:#ffb3ba; white-space:pre-wrap; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(430px,1fr)); gap:14px; }
  img.shot { width:100%; max-width:400px; image-rendering:pixelated; border:1px solid #2a3342;
             border-radius:6px; background:#000; display:block; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:8px 0; }
  footer { padding:10px 18px 26px; color:#8b98ab; font-size:12px; }
  code { color:#7ee0a3; }
</style>
</head>
<body>
<header>
  <h1>场景固定 · 出图任务面板</h1>
  <div class="row" style="margin:0">
    <span class="muted">场景来源</span>
    <select id="sceneSel"></select>
    <button id="pinBtn">固定并提交</button>
    <span id="pinMsg" class="muted"></span>
  </div>
</header>
<div id="banner" class="banner" hidden></div>
<main>
  <aside>
    <h2>场景修订</h2>
    <div id="revList"></div>
    <h2 style="margin-top:18px">回归样例</h2>
    <div id="samples" class="muted"></div>
  </aside>
  <section id="detail"><p class="muted">选择左侧修订，查看版本摘要并在两台工作站出图。</p></section>
</main>
<footer id="policy"></footer>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let STATE = null, SELECTED = null;

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json();
  if (!r.ok) throw j;
  return j;
}
function showBanner(html) { const b = $('#banner'); b.innerHTML = html; b.hidden = !html; }
function chainHtml(chain) {
  return (chain || []).map(c => `  ↳ 引用来源 <code>${esc(c.file)}</code> @ ${esc(c.where)}`).join('\\n');
}
function paramsHtml(rev) {
  const a = rev.animation || {}, p = rev.plugins || {};
  const plug = Object.entries(p).map(([k, v]) =>
    `${k}(${Object.entries(v).map(([kk, vv]) => kk + '=' + vv).join(', ')})`).join(' ');
  return `动画时刻 ${a.time_ms} ms @ ${a.fps} fps ｜ 插件 ${esc(plug || '默认')}`;
}
function consistencyBadge(rev) {
  const rendered = STATE.nodes.filter(n => rev.results[n]);
  if (rendered.length < 2) return '<span class="badge none">待渲染</span>';
  return rev.consistent
    ? '<span class="badge ok">跨节点一致</span>'
    : '<span class="badge err">跨节点不一致</span>';
}

async function refresh() {
  STATE = await api('/api/state');
  $('#sceneSel').innerHTML = STATE.scenes.map(s => `<option>${esc(s)}</option>`).join('');
  $('#policy').innerHTML = '<b>受支持格式</b>：' +
    Object.entries(STATE.policy.formats).map(([k, v]) => `${k}: ${v.join(', ')}`).join(' ｜ ') +
    '<br><b>拒绝策略</b>：' + STATE.policy.reject.join('；') +
    '<br><b>动画</b>：' + esc(STATE.policy.animation) +
    '<br><b>插件</b>：' + esc(STATE.policy.plugins.join(', '));
  const errors = [];
  STATE.revisions.forEach(r => {
    if (Object.keys(r.results).length > 1 && !r.consistent) {
      errors.push(`修订 #${r.short}：` + r.problems.join('；'));
    }
    STATE.nodes.forEach(n => {
      const res = r.results[n];
      if (res && res.status !== 'ok') errors.push(`修订 #${r.short} @ ${n}：${res.error || '失败'}`);
    });
  });
  showBanner(errors.length
    ? '场景固定核验异常（来自实际出图结果）：\\n' + errors.map(esc).join('\\n')
    : '');
  renderRevList();
  $('#samples').innerHTML = STATE.revisions.length
    ? STATE.revisions.map(r =>
        `<div class="card rev ${r.revision === SELECTED ? 'sel' : ''}" data-rev="${esc(r.revision)}"
              style="margin-bottom:8px">
           <div><b>${esc(r.name)}</b> <span class="hash">#${esc(r.short)}</span></div>
           <div class="muted">指纹 <code>${esc(r.fingerprint.slice(0, 12))}</code></div>
           <div class="muted">${r.assets} 项资源 ｜ ${esc(r.created)}</div>
         </div>`).join('')
    : '<p>请先固定 scenes/demo 生成回归样例。</p>';
  document.querySelectorAll('#samples .rev').forEach(el =>
    el.onclick = () => { SELECTED = el.dataset.rev; renderRevList(); showRev(SELECTED); });
  if (SELECTED) showRev(SELECTED);
}

function renderRevList() {
  $('#revList').innerHTML = STATE.revisions.map(r => {
    const badges = STATE.nodes.map(n => {
      const res = r.results[n];
      const cls = res ? (res.status === 'ok' ? 'ok' : 'err') : 'none';
      const txt = res ? (res.status === 'ok' ? '✓ ' + res.pixel : '✗ 失败') : '未渲染';
      return `<span class="badge ${cls}">${n} ${esc(txt)}</span>`;
    }).join('');
    return `<div class="card rev ${r.revision === SELECTED ? 'sel' : ''}" data-rev="${r.revision}">
      <div><b>${esc(r.name)}</b> <span class="hash">#${r.short}</span></div>
      <div class="muted">指纹 <code>${esc(r.fingerprint.slice(0, 16))}</code></div>
      <div class="muted">${esc(r.created)} ｜ ${r.assets} 项资源 ｜ ${r.bytes} B</div>
      <div class="muted">${esc(paramsHtml(r))}</div>
      <div class="row">${badges}${consistencyBadge(r)}</div></div>`;
  }).join('') || '<p class="muted">尚无修订，请先固定场景。</p>';
  document.querySelectorAll('.rev').forEach(el =>
    el.onclick = () => { SELECTED = el.dataset.rev; renderRevList(); showRev(SELECTED); });
}

async function showRev(rev) {
  const m = await api('/api/manifest?rev=' + rev);
  const r = STATE.revisions.find(x => x.revision === rev);
  const assets = m.assets.map(a =>
    `<tr><td>${esc(a.path)}</td><td>${esc(a.role)}</td><td>${a.size}</td><td><code>${a.sha256.slice(0,12)}</code></td></tr>`).join('');
  const a = m.settings.animation || {}, p = m.settings.plugins || {};
  const plugRows = Object.entries(p).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td><code>${esc(JSON.stringify(v))}</code></td></tr>`).join('');
  const revOpts = STATE.revisions.map(x =>
    `<option value="${esc(x.revision)}"${x.revision === rev ? ' selected' : ''}>` +
    `#${esc(x.short)} ${esc(x.name)}</option>`).join('');
  let html = `<div class="card">
    <h2>版本摘要</h2>
    <div class="row" style="margin:0 0 8px">
      <span class="muted">切换回归样例</span>
      <select id="revSel">${revOpts}</select>
      <button id="renderSelBtn">出图并核对画面</button>
    </div>
    <div>清单哈希 <code>${rev}</code> ｜ 名称 ${esc(m.name)} ｜ 入口 <code>${esc(m.entry)}</code></div>
    <div>场景指纹 <code>${esc(r ? r.fingerprint : '')}</code></div>
    <div class="muted">固定于 ${esc(m.created)} ｜ 分辨率 ${m.settings.render.width}×${m.settings.render.height} ｜ 背景 ${m.settings.render.background}</div>
    <div class="muted">动画时刻 ${a.time_ms} ms @ ${a.fps} fps</div>
    <details open><summary class="muted">插件参数</summary><table>
      <tr><th>插件</th><th>参数</th></tr>${plugRows}</table></details>
    <div class="row"><button id="renderBtn">在全部节点渲染此修订</button><span id="renderMsg" class="muted"></span></div>
    <details><summary class="muted">任务清单（${m.assets.length} 项资源，按内容寻址）</summary>
      <table><tr><th>逻辑路径</th><th>角色</th><th>字节</th><th>sha256</th></tr>${assets}</table>
    </details></div>
    <div class="card" id="compare" style="margin-top:14px"></div>
    <div class="grid" id="nodes" style="margin-top:14px"></div>`;
  $('#detail').innerHTML = html;
  $('#renderBtn').onclick = () => doRender(rev);
  $('#revSel').onchange = () => { SELECTED = $('#revSel').value; renderRevList(); showRev(SELECTED); };
  $('#renderSelBtn').onclick = async () => {
    SELECTED = $('#revSel').value;
    await doRender(SELECTED);
  };
  await showCompare(rev);
  for (const n of STATE.nodes) $('#nodes').appendChild(await nodeCard(rev, n));
}

async function showCompare(rev) {
  const el = $('#compare');
  const c = await api('/api/compare?rev=' + rev);
  if (Object.keys(c.pixel_sha256).length < 2) {
    el.innerHTML = `<h2>跨节点一致性</h2><p class="muted">至少两台节点出图后才能比较。</p>`;
    return;
  }
  const nodes = Object.keys(c.pixel_sha256).sort();
  const short = v => v ? esc(v.slice(0, 16)) : '<span class="badge err">缺失</span>';
  const rows = nodes.map(n =>
    `<tr><td>${esc(n)}</td><td><code>${short(c.fingerprints[n])}</code></td><td><code>${short(c.pixel_sha256[n])}</code></td></tr>`).join('');
  let deltaHtml = '';
  if (nodes.length >= 2) {
    const d = await api(`/api/delta?rev=${rev}&a=${nodes[0]}&b=${nodes[1]}`);
    deltaHtml = d.error ? `<p class="muted">${esc(d.error.message)}</p>`
      : `<div class="muted">渲染差值 ${esc(nodes[0])} ↔ ${esc(nodes[1])}：` +
        `${d.pixels_differ}/${d.pixels_total} 像素不同（${(d.differ_ratio * 100).toFixed(3)}%），` +
        `最大通道差 ${d.max_channel_delta}，${d.identical ? '像素完全一致' : '像素存在差异'}</div>`;
  }
  el.innerHTML = `<h2>跨节点一致性 ${c.consistent ? '<span class="badge ok">通过</span>' : '<span class="badge err">失败</span>'}</h2>
    <table><tr><th>节点</th><th>场景指纹</th><th>像素 sha256</th></tr>${rows}</table>
    ${c.problems.length ? `<div class="banner" style="margin:10px 0 0">${esc(c.problems.join('\\n'))}</div>` : ''}
    ${deltaHtml}`;
}

async function nodeCard(rev, node) {
  const div = document.createElement('div');
  div.className = 'card';
  let res;
  try { res = await api(`/api/result?rev=${rev}&node=${node}`); }
  catch (e) { div.innerHTML = `<h2>${node}</h2><p class="muted">尚未渲染</p>`; return div; }
  if (res.status === 'ok') {
    const rows = res.assets.map(a =>
      `<tr><td>${esc(a.path)}</td><td>${esc(a.source)}</td><td><code>${a.actual.slice(0,12)}</code></td><td>${a.ok ? '✓' : '✗'}</td></tr>`).join('');
    const env = res.env;
    div.innerHTML = `<h2>${node} <span class="badge ok">成功</span></h2>
      <img class="shot" src="/api/image?rev=${rev}&node=${node}&t=${Date.now()}">
      <div class="row">场景指纹 <code>${esc(res.fingerprint.slice(0, 16))}</code></div>
      <div class="row">像素 sha256 <code>${esc(res.output.pixel_sha256.slice(0, 16))}</code></div>
      <details open><summary class="muted">环境记录</summary><table>
        <tr><th>主机</th><td>${esc(env.host)}</td></tr>
        <tr><th>平台</th><td>${esc(env.platform)}</td></tr>
        <tr><th>Python</th><td>${esc(env.python)} ｜ pid ${env.pid}</td></tr>
        <tr><th>工作目录</th><td><code>${esc(env.workdir)}</code></td></tr>
        <tr><th>起止</th><td>${esc(env.started)} → ${esc(env.finished)}（${env.duration_ms} ms）</td></tr>
      </table></details>
      <details><summary class="muted">资源校验（${res.assets.length} 项，缓存命中/回源取数）</summary>
        <table><tr><th>逻辑路径</th><th>来源</th><th>实际 sha256</th><th>校验</th></tr>${rows}</table>
      </details>`;
  } else {
    const e = res.error || {};
    const chain = e.kind === 'pin' ? '\\n' + chainHtml(e.chain)
      : (e.detail ? '\\n' + Object.entries(e.detail).map(([k, v]) => `  ↳ ${k}: ${v}`).join('\\n') : '');
    div.innerHTML = `<h2>${node} <span class="badge err">失败</span></h2>
      <div class="banner" style="margin:0">${esc(e.message || '未知错误')}${esc(chain)}</div>
      <p class="muted">失败已反馈回场景固定（保留于该修订的结果记录中）。环境：${esc(res.env.host)} ｜ ${esc(res.env.finished)}</p>`;
  }
  return div;
}

async function doRender(rev) {
  $('#renderMsg').textContent = '渲染中…';
  try {
    await api('/api/render', {method: 'POST', body: JSON.stringify({revision: rev})});
    $('#renderMsg').textContent = '完成';
  } catch (e) { $('#renderMsg').textContent = '失败：' + (e.error ? e.error.message : e); }
  await refresh();
}

$('#pinBtn').onclick = async () => {
  showBanner(''); $('#pinMsg').textContent = '固定中…';
  try {
    const j = await api('/api/pin', {method: 'POST', body: JSON.stringify({scene: $('#sceneSel').value})});
    SELECTED = j.revision;
    $('#pinMsg').textContent = (j.created_new ? '新修订 ' : '内容未变，复用修订 ') +
      j.revision.slice(0, 12) + ' ｜ 指纹 ' + j.fingerprint.slice(0, 12);
    await refresh();
  } catch (e) {
    $('#pinMsg').textContent = '';
    const err = e.error || {};
    showBanner('固定被拒绝：' + esc(err.message || JSON.stringify(e)) + '\\n' + chainHtml(err.chain));
  }
};

refresh();
</script>
</body>
</html>
"""


def make_handler(kernel):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, exc):
            if isinstance(exc, PinError):
                self._json({"error": exc.to_dict()}, 400)
            else:
                self._json({"error": {"kind": "internal", "message": str(exc)}}, 500)

        def do_GET(self):
            try:
                url = urlparse(self.path)
                q = parse_qs(url.query)
                if url.path == "/":
                    body = INDEX_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif url.path == "/api/state":
                    self._json(kernel.state())
                elif url.path == "/api/manifest":
                    self._json(kernel.manifest(q["rev"][0]))
                elif url.path == "/api/result":
                    res = kernel.result(q["rev"][0], q["node"][0])
                    if res is None:
                        self._json({"error": {"message": "尚无结果"}}, 404)
                    else:
                        self._json(res)
                elif url.path == "/api/compare":
                    self._json(kernel.compare(q["rev"][0]))
                elif url.path == "/api/delta":
                    rev, a, b = q["rev"][0], q["a"][0], q["b"][0]
                    pa = kernel.image_file(rev, a)
                    pb = kernel.image_file(rev, b)
                    if pa is None or pb is None:
                        self._json({"error": {"message": "比较双方须均已成功出图"}}, 404)
                    else:
                        self._json(render_delta(pa.read_bytes(), pb.read_bytes()))
                elif url.path == "/api/image":
                    p = kernel.image_file(q["rev"][0], q["node"][0])
                    if p is None:
                        self._json({"error": {"message": "无图像"}}, 404)
                    else:
                        body = p.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                else:
                    self._json({"error": {"message": "not found"}}, 404)
            except Exception as exc:  # noqa: BLE001 - 边界处统一转 JSON
                self._error(exc)

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/pin":
                    self._json(kernel.pin(body["scene"]))
                elif self.path == "/api/render":
                    self._json(kernel.render(body["revision"]))
                else:
                    self._json({"error": {"message": "not found"}}, 404)
            except Exception as exc:  # noqa: BLE001
                self._error(exc)

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(kernel, host="127.0.0.1", port=8471):
    httpd = ThreadingHTTPServer((host, port), make_handler(kernel))
    print(f"出图任务面板已启动: http://{host}:{port}")
    print(f"节点: {', '.join(n.id for n in kernel.nodes)} ｜ 工作区: {kernel.root}")
    httpd.serve_forever()
