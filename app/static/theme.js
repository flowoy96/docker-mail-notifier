// Wird vor dem ersten Rendern geladen, damit die Seite nicht kurz im falschen Farbschema aufblitzt.
(function () {
  var KEY = 'dmn-theme';
  var media = window.matchMedia('(prefers-color-scheme: dark)');

  function get() {
    try {
      var value = localStorage.getItem(KEY);
      return value === 'light' || value === 'dark' ? value : 'auto';
    } catch (e) {
      return 'auto';
    }
  }

  function apply() {
    var mode = get();
    var dark = mode === 'dark' || (mode === 'auto' && media.matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = dark ? '#000000' : '#f5f5f7';
  }

  function set(mode) {
    try {
      if (mode === 'auto') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch (e) { /* privater Modus: gilt dann nur bis zum Neuladen */ }
    apply();
  }

  if (media.addEventListener) media.addEventListener('change', apply);
  window.dmnTheme = { get: get, set: set, apply: apply };
  apply();
})();
