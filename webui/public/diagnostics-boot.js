// Loaded independently before the bundle, respecting script-src 'self'.
(function () {
  var pending = [], count = 0, busy = false;
  var retries = 0, retryTimer = null;
  function retry() {
    if (!pending.length || retryTimer !== null || retries >= 3) return;
    retries += 1;
    retryTimer = setTimeout(function () {
      retryTimer = null;
      flush();
    }, 1000);
  }
  function flush() {
    var api = window.pywebview && window.pywebview.api;
    if (!api || !api.record_frontend_event || busy || retryTimer !== null || !pending.length) return;
    busy = true;
    var event = pending[0];
    Promise.resolve().then(function () {
      return api.record_frontend_event('error', event.message, event.stack);
    }).then(function (result) {
      busy = false;
      if (result.ok) { pending.shift(); retries = 0; flush(); }
      else { retry(); }
    }).catch(function () { busy = false; retry(); });
  }
  window.addEventListener('error', function (event) {
    if (count >= 10) return;
    if (event.message) {
      if (document.documentElement.dataset.diagnosticsReady === 'true') return;
      pending.push({message: 'Bootstrap error: ' + event.message.slice(0, 3000), stack: String(event.error && event.error.stack || '').slice(0, 6000)});
    } else {
      var target = event.target;
      if (!target || (target.tagName !== 'SCRIPT' && target.tagName !== 'LINK')) return;
      var url = (target.src || target.href || '').split('?')[0].split('#')[0];
      pending.push({message: 'Bootstrap resource failed: ' + url.slice(-300), stack: ''});
    }
    count += 1;
    flush();
  }, true);
  window.addEventListener('pywebviewready', flush);
}());
