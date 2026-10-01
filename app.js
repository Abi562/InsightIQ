function plot(id, fig, opts) {
  const el = document.getElementById(id);
  if (!el || !window.Plotly) return;
  const layout = Object.assign({autosize: true}, fig.layout || {});
  Plotly.newPlot(el, fig.data, layout, Object.assign({responsive: true, displaylogo: false}, opts || {}));
}
document.addEventListener('DOMContentLoaded', () => {
  const t = document.getElementById('menuToggle'), s = document.getElementById('sidebar');
  if (t && s) t.addEventListener('click', () => s.classList.toggle('open'));
  // dataset switcher
  const sel = document.getElementById('dsSwitch');
  if (sel) sel.addEventListener('change', () => {
    window.location = '/dataset/' + sel.value + '/select?next=' + encodeURIComponent(location.pathname);
  });
  // show spinner on long-running forms
  document.querySelectorAll('form[data-busy]').forEach(f => f.addEventListener('submit', () => {
    const b = f.querySelector('button[type=submit]');
    if (b) { b.disabled = true; b.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>' + (f.dataset.busy || 'Working…'); }
  }));
  // dropzones
  document.querySelectorAll('.dropzone').forEach(z => {
    const input = z.querySelector('input[type=file]'), label = z.querySelector('.fname');
    z.addEventListener('click', e => { if (e.target !== input) input.click(); });
    input.addEventListener('change', () => { if (input.files[0]) label.textContent = input.files[0].name; });
    ['dragover', 'dragenter'].forEach(ev => z.addEventListener(ev, e => { e.preventDefault(); z.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(ev => z.addEventListener(ev, e => { e.preventDefault(); z.classList.remove('drag'); }));
    z.addEventListener('drop', e => { if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; label.textContent = input.files[0].name; } });
  });
  // question chips
  document.querySelectorAll('.chip[data-q]').forEach(c => c.addEventListener('click', () => {
    const i = document.getElementById('question'); i.value = c.dataset.q; i.form.submit();
  }));
});
