// Runs before the module bundle and reports locally even when the Python bridge fails.
(function () {
  var meta = document.querySelector('meta[name="jot-startup"]');
  if (!meta) return;
  var config = JSON.parse(meta.content);
  var version = '', finished = false;
  function send(kind, message) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 3000);
    return fetch(config.event_url, {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: kind, message: String(message || '').slice(0, 1500),
        build_id: config.build_id, version: version, attempt: config.attempt })
    }).then(function (response) { return response.ok; }).catch(function () { return false; })
      .finally(function () { clearTimeout(timer); });
  }
  window.elDesktopStartup = {
    validate: function (compiledVersion) {
      version = String(compiledVersion).replace(/^v/, '');
      window.__elDesktopVersion = version;
      if (version !== config.version || location.pathname !== '/ui/' + config.build_id + '/index.html') {
        void send('mismatch', 'Frontend build does not match the desktop process');
        return false;
      }
      return true;
    },
    settingsStarted: function () {
      var api = window.pywebview && window.pywebview.api;
      if (!version || !api || !api.load_settings) return Promise.resolve(false);
      return send('settings-started', 'Loading settings through Python bridge');
    },
    ready: function () {
      var api = window.pywebview && window.pywebview.api;
      if (!version || !api || !api.load_settings || !api.save_settings) return Promise.resolve(false);
      return send('ready', 'Settings loaded through Python bridge').then(function (ok) {
        if (ok) finished = true;
        return ok;
      });
    }
  };
  window.addEventListener('error', function (event) {
    if (finished) return;
    var target = event.target;
    if (!event.message && (!target || (target.tagName !== 'SCRIPT' && target.tagName !== 'LINK'))) return;
    var message = event.message || (target && (target.src || target.href)) || 'Unknown bootstrap error';
    void send('error', message);
  }, true);
  window.addEventListener('unhandledrejection', function (event) {
    if (!finished) void send('error', String(event.reason));
  });
  void send('page', 'Versioned desktop document loaded');
}());
