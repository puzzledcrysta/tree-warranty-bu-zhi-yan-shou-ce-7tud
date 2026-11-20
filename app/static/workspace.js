import {query, readInput, encodeInput} from './api.js';
import {el, evidence, table} from './table.js';

const byId = id => document.getElementById(id);
const settings = JSON.parse(byId('settings').textContent);
const links = [...document.querySelectorAll('[data-module]')];
const body = byId('grid-data');
const alert = byId('notice');
const live = byId('state');
const action = document.querySelector('#source button[type=submit]');
const topExport = byId('export');
let selected = Object.hasOwn(settings.tabs, location.hash.slice(1)) ? location.hash.slice(1) : 'domain';
let result = null;
let inputs = {};
let reviewVersion = 0;
let renderEpoch = 0;
let activeView = null;
let woView = 'batches';
const filter = byId('filter');
const differences = byId('differences');

function filterTable() {
  if (!activeView) return;
  const {columns, rows, stage} = activeView;
  if (!columns.length) {
    byId('shown').textContent = '';
    return;
  }
  const query = filter.value.trim().toLocaleLowerCase();
  const selected = rows.filter(row => {
    if (stage === 'reconcile' && differences.checked && row.code === 'MATCH') return false;
    return !query || [row.key,row.id,row.line,row.code,settings.reasons[row.code],row.detail,row.note,row.kind,
      row.order,row.tree,row.species,row.lot,row.status,row.arrived]
      .some(value => String(value ?? '').toLocaleLowerCase().includes(query));
  });
  byId('shown').textContent = `${selected.length} / ${rows.length}`;
  table(body, columns, selected);
}
filter.addEventListener('input', filterTable);
differences.addEventListener('change', filterTable);
for (const button of document.querySelectorAll('[data-wo-view]')) {
  button.addEventListener('click', async () => {
    woView = button.dataset.woView;
    for (const item of document.querySelectorAll('[data-wo-view]')) {
      item.classList.toggle('is-on', item === button);
    }
    await render();
  });
}
const uploaded = new Map();

function notice(message, error = false) {
  alert.value = message;
  alert.classList.toggle('problem', error);
}

function tag(code) {
  return el('span', settings.reasons[code] || code, code === 'MATCH' ? 'state' : 'state problem');
}


function showEvidence(row) {
  const panel = byId('evidence-panel');
  const record = byId('evidence-key');
  const details = byId('signal');
  if (!row) {
    record.textContent = '';
    details.replaceChildren(el('p', '本批没有可采信记录', 'empty'));
    return;
  }
  record.textContent = row.key;
  const content = el('ol', undefined, panel.dataset.instrument);
  for (const item of row.proof) {
    const line = el('li');
    line.append(el('span', item.metric));
    line.append(el('strong', item.unit ? `${item.value} ${item.unit}` : item.value, 'measure'));
    content.append(line);
  }
  details.replaceChildren(content);
}

function inspect(row) {
  const button = el('button', '查看依据', 'btn');
  button.type = 'button';
  button.addEventListener('click', () => showEvidence(row));
  const raw = evidence('原始字段', row.raw);
  const cell = el('div');
  cell.append(button, raw);
  return cell;
}

function setRun(report) {
  result = report;
  byId('created').textContent = `${report.manifest.created.slice(0, 19).replace('T', ' ')} UTC`;
  showEvidence(report.accepted[0]);
  const id = result.manifest.run_id;
  byId('run-id').textContent = id.slice(0, 9);
  byId('run-id').title = id;
  topExport.hidden = false;
  topExport.href = `/api/export/${id}`;
  const values = {...result.counts, delta: result.book.delta, mismatched: result.book.mismatched};
  for (const cell of document.querySelectorAll('[data-count]')) {
    if (cell.dataset.count === 'settled') {
      cell.textContent = result.writeoff ? result.writeoff.summary.settled_qty : '—';
    } else if (cell.dataset.count === 'held') {
      cell.textContent = result.writeoff ? result.writeoff.summary.held_qty : '—';
    } else {
      cell.textContent = values[cell.dataset.count];
    }
  }
  live.textContent = `批次 ${id.slice(0, 9)} · ${result.balanced ? '记录已对齐' : '记录数不符'}${
    result.writeoff ? ` · ${result.writeoff.summary.mode_label}` : ''}`;
}

async function render() {
  const ticket = ++renderEpoch;
  const stage = selected;
  byId('phase').textContent = settings.tabs[stage];
  byId('review').hidden = true;
  byId('writeoff-views').hidden = stage !== 'writeoff' || !result?.writeoff;
  for (const link of links) {
    if (link.dataset.module === stage) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  if (!result) return;
  const id = result.manifest.run_id;
  const raw = row => evidence('来源字段', row.raw);
  const key = [settings.key, 'key'];
  const line = ['行号', 'line', 'num'];
  try {
    let view, rows;
    if (stage === 'domain') {
      view = [key, [`应付养护款 · ${settings.unit}`, 'amount', 'num'], line, ['明细依据', inspect]];
      rows = result.accepted;
    } else if (stage === 'quality') {
      view = [key, line, ['判定', row => tag(row.code)], ['说明', 'detail'], ['字段', raw]];
      rows = [...result.quarantine, ...result.suppressed].sort((a,b) => a.line-b.line);
    } else if (stage === 'reconcile') {
      view = [key, ['实际', 'amount', 'num'], ['外部账', 'reference', 'num'], ['差值', 'delta', 'num'], ['外部行', 'book_line', 'num'], ['结论', row => tag(row.code)]];
      rows = [...result.book.rows].sort((a,b) => Number(a.code === 'MATCH') - Number(b.code === 'MATCH'));
    } else if (stage === 'intake') {
      const intake = await query('/api/intake', inputs);
      view = [line, ['分类', 'kind'], ['字段', raw]];
      rows = [...intake.rows.map(row => ({...row,kind:'完整记录'})), ...intake.rejected.map(row => ({...row,kind:'坏行'})),
              ...intake.blank_lines.map(line => ({line,kind:'空白行',raw:[]})),
              ...intake.header_lines.map(line => ({line,kind:'重复表头',raw:[]}))].sort((a,b) => a.line-b.line);
    } else if (stage === 'contract') {
      const contract = await query('/api/contract', inputs);
      view = [key, line, ['修订', 'revision', 'num'], ['来源时刻 UTC', 'time'], ['字段', row => evidence('归一值', Object.entries(row.fields).map(([k,v]) => `${k} · ${v}`))]];
      rows = contract.accepted;
    } else if (stage === 'writeoff') {
      const writeoff = result.writeoff;
      if (!writeoff) {
        if (ticket === renderEpoch) {
          activeView = {stage, columns: [], rows: []};
          body.replaceChildren(el('p', '本批未提供苗批账与领用册，导入后重新运行', 'empty'));
        }
        view = [];
        rows = [];
      } else {
        const stateTag = value => el('span', value,
          value === '可签收' || value === '已核销' ? 'state' : 'state problem');
        if (woView === 'batches') {
          view = [
            ['街段验收单', 'key'], ['补植株数', 'replants', 'num'],
            ['已核销', 'allocated', 'num'], ['挂起', 'held', 'num'],
            ['涉及领用单', 'orders', 'num'], ['签收', row => stateTag(row.status)]];
          rows = writeoff.batches.filter(row => row.allocated || row.held || row.replants);
        } else if (woView === 'orders') {
          view = [['领用单号', 'order'], ['行数', 'lines', 'num'],
                  ['已核销株', 'allocated', 'num'], ['挂起株', 'held', 'num'],
                  ['单据状态', row => stateTag(row.status)]];
          rows = writeoff.orders;
        } else if (woView === 'lines') {
          view = [['领用单', 'order'], ['街段验收单', 'key'], ['树位', 'tree'], ['树种', 'species'],
                  ['申领', 'qty', 'num'], ['已核销', 'allocated', 'num'],
                  ['苗批号', row => row.lot ?? '—'], ['状态', row => stateTag(row.status)],
                  ['来源行', 'line_no', 'num']];
          rows = writeoff.lines;
        } else if (woView === 'lots') {
          view = [['苗批号', 'lot'], ['树种', 'species'], ['进场日', 'arrived'],
                  ['进场数量', 'quantity', 'num'], ['已核销', 'used', 'num'],
                  ['剩余余量', 'remaining', 'num']];
          rows = writeoff.lots;
        } else {
          view = [['行号', 'line', 'num'], ['原因', row => tag(row.code)], ['说明', 'detail'],
                  ['字段', raw]];
          rows = [...writeoff.quarantine, ...writeoff.suppressed].sort((a, b) => a.line - b.line);
        }
      }
    } else if (stage === 'runs') {
      const runs = await query('/api/runs');
      view = [['指纹','id'], ['创建 UTC','created'], ['操作', row => {
        const current = row.id === id;
        const button = el('button',current ? '复算当前批' : '打开此批','btn');
        button.addEventListener('click', async () => {
          button.disabled = true;
          try {
            if (current) {
              setRun(await query(`/api/runs/${id}/replay`, {}));
              notice('复算已核对');
            } else {
              const [past, original] = await Promise.all([
                query(`/api/runs/${row.id}`), query(`/api/runs/${row.id}/source`),
              ]);
              inputs = original;
              setRun(past);
              if (original.stock_base64) {
                const decode = base64 => new TextDecoder('utf-8').decode(
                  Uint8Array.from(atob(base64), char => char.charCodeAt(0)));
                byId('stock-csv').value = decode(original.stock_base64);
                byId('requisitions-csv').value = decode(original.requisitions_base64);
                byId('writeoff-mode').value = original.mode;
              }
              notice('已打开历史批次');
              await render();
            }
          }
          catch (error) { notice(error.message, true); }
          finally { button.disabled = false; }
        });
        return button;
      }]];
      rows = runs;
    } else {
      const timeline = await query(`/api/review/${id}`);
      view = [['版本','version','num'], ['结论','decision'], ['复核意见','note'], ['登记 UTC','changed']];
      rows = timeline;
      if (ticket === renderEpoch) {
        reviewVersion = timeline[0]?.version || 0;
        byId('review').hidden = false;
      }
    }
    if (ticket === renderEpoch) {
      if (activeView?.stage !== stage) filter.value = '';
      activeView = {stage, columns: view, rows};
      byId('tools').hidden = false;
      byId('only-differences').hidden = stage !== 'reconcile';
      filterTable();
    }
  } catch (error) {
    if (ticket === renderEpoch) notice(error.message, true);
  }
}

window.addEventListener('hashchange', () => {
  const next = Object.hasOwn(settings.tabs, location.hash.slice(1)) ? location.hash.slice(1) : 'domain';
  if (next !== 'writeoff') woView = 'batches';
  selected = next;
  render();
});
byId('sample').addEventListener('click', async () => {
  const paths = ['shift', 'external', 'stock', 'requisitions'];
  try {
    const responses = await Promise.all(paths.map(name => fetch(`/api/samples/${name}`)));
    if (responses.some(item => !item.ok)) throw Error('样例暂时不可用');
    const files = await Promise.all(responses.map(item => item.arrayBuffer()));
    const names = ['source', 'book', 'stock', 'requisitions'];
    for (const [index, name] of names.entries()) {
      const decoded = new TextDecoder('utf-8').decode(files[index]);
      byId(`${name}-csv`).value = decoded;
      uploaded.set(name, {text: byId(`${name}-csv`).value, bytes: files[index]});
      if (name === 'source' || name === 'book') byId(`${name}-file`).value = '';
      else byId(`${name}-file`).value = '';
    }
    document.querySelector('#source details').open = true;
    notice('样例已载入');
  } catch (error) { notice(error.message, true); }
});
for (const name of ['source', 'book', 'stock', 'requisitions']) {
  byId(`${name}-file`).addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    action.disabled = true;
    try {
      const [text, bytes] = await readInput(file);
      byId(`${name}-csv`).value = text;
      uploaded.set(name, {text: byId(`${name}-csv`).value, bytes});
      notice(`已读取 ${file.name}`);
    } catch (error) {
      event.target.value = '';
      notice(error.message, true);
    } finally { action.disabled = false; }
  });
}
byId('source').addEventListener('submit', async event => {
  event.preventDefault();
  const candidate = {};
  for (const [control, name] of [['source', 'data'], ['book', 'book'],
                                 ['stock', 'stock'], ['requisitions', 'requisitions']]) {
    const text = byId(`${control}-csv`).value;
    const original = uploaded.get(control);
    if (original && text === original.text && (control === 'source' || control === 'book')) {
      candidate[`${name}_base64`] = encodeInput(original.bytes);
    } else if (text.length || original) {
      candidate[name] = text;
    }
  }
  candidate.mode = byId('writeoff-mode').value;
  action.disabled = true;
  ++renderEpoch;
  notice('计算中');
  try {
    const report = await query('/api/runs', candidate);
    inputs = candidate;
    setRun(report);
    notice('批次已计算');
    await render();
  } catch (error) { notice(error.message, true); }
  finally { action.disabled = false; }
});
byId('review').addEventListener('submit', async event => {
  event.preventDefault();
  const id = result.manifest.run_id;
  const note = byId('review-note');
  try {
    await query(`/api/review/${id}`, {version: reviewVersion, decision: byId('decision').value, note: note.value});
    notice('复核已登记');
    note.value = '';
    await render();
  } catch (error) {
    notice(error.message, true);
    if (error.status === 409) await render();
  }
});
render();
