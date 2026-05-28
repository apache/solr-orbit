(function () {
  'use strict';

  // ── Sidebar toggle buttons (expand/collapse) ──────────
  document.querySelectorAll('.nav-toggle-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var isOpen = btn.classList.toggle('open');
      var list = btn.closest('.nav-row')
        ? btn.closest('.nav-row').nextElementSibling
        : btn.nextElementSibling;
      if (list) list.classList.toggle('open', isOpen);
    });
  });

  // ── Mobile sidebar ────────────────────────────────────
  var menuBtn  = document.getElementById('mobile-menu-btn');
  var sidebar  = document.getElementById('sidebar');
  var overlay  = document.getElementById('sidebar-overlay');

  function openSidebar() {
    sidebar.classList.add('open');
    overlay.classList.add('open');
    menuBtn.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
    menuBtn.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  if (menuBtn) {
    menuBtn.addEventListener('click', function () {
      sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
    });
  }
  if (overlay) {
    overlay.addEventListener('click', closeSidebar);
  }

  // ── Back to top ───────────────────────────────────────
  var backBtn = document.getElementById('back-to-top');
  if (backBtn) {
    window.addEventListener('scroll', function () {
      backBtn.classList.toggle('visible', window.scrollY > 400);
    }, { passive: true });
    backBtn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // ── Client-side search ────────────────────────────────
  var searchInput   = document.getElementById('search-input');
  var searchResults = document.getElementById('search-results');
  var searchData    = null;

  function loadSearchData(cb) {
    if (searchData) { cb(); return; }
    var base = document.querySelector('base') ? document.querySelector('base').href : '';
    // Derive the baseurl from a known asset link
    var cssLink = document.querySelector('link[rel=stylesheet][href*="/assets/css/"]');
    var baseurl = '';
    if (cssLink) {
      var m = cssLink.getAttribute('href').match(/^(.*?)\/assets\/css\//);
      if (m) baseurl = m[1];
    }
    fetch(baseurl + '/search.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { searchData = data; cb(); })
      .catch(function () { searchData = []; });
  }

  function renderResults(query) {
    if (!query || query.length < 2) {
      searchResults.classList.remove('open');
      return;
    }
    var q = query.toLowerCase();
    var matches = searchData.filter(function (p) {
      return p.title.toLowerCase().indexOf(q) !== -1 ||
             (p.content && p.content.toLowerCase().indexOf(q) !== -1);
    }).slice(0, 10);

    if (matches.length === 0) {
      searchResults.innerHTML = '<div class="search-no-results">No results for "' +
        query.replace(/</g, '&lt;') + '"</div>';
    } else {
      searchResults.innerHTML = matches.map(function (p) {
        return '<a class="search-result" href="' + p.url + '">' +
          '<div class="result-title">' + p.title + '</div>' +
          '<div class="result-path">' + p.url + '</div>' +
          '</a>';
      }).join('');
    }
    searchResults.classList.add('open');
  }

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      var query = searchInput.value.trim();
      if (!query) { searchResults.classList.remove('open'); return; }
      loadSearchData(function () { renderResults(query); });
    });

    searchInput.addEventListener('focus', function () {
      if (searchInput.value.trim().length >= 2 && searchData) {
        renderResults(searchInput.value.trim());
      }
    });

    document.addEventListener('click', function (e) {
      if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
        searchResults.classList.remove('open');
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') searchResults.classList.remove('open');
    });
  }

  // ── Heading anchor links ──────────────────────────────
  document.querySelectorAll('.page-content h2, .page-content h3, .page-content h4').forEach(function (h) {
    if (!h.id) return;
    var a = document.createElement('a');
    a.className = 'heading-anchor';
    a.href = '#' + h.id;
    a.setAttribute('aria-label', 'Link to ' + h.textContent);
    a.innerHTML = '#';
    h.appendChild(a);
  });

}());
