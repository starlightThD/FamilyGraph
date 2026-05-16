(() => {
  const navLinks = document.querySelectorAll('.nav-link');
  const normalizePath = (path) => path.replace(/\/$/, '');
  const currentPath = normalizePath(window.location.pathname);

  navLinks.forEach((link) => {
    try {
      const linkPath = normalizePath(new URL(link.href, window.location.origin).pathname);
      if (linkPath === currentPath) {
        link.classList.add('active');
      }
    } catch (error) {
      // Ignore invalid URLs so the rest of the script can continue.
    }
  });

  let bubbleEl = null;
  let hideTimer = null;

  const ensureBubble = () => {
    if (bubbleEl) return bubbleEl;
    bubbleEl = document.createElement('div');
    bubbleEl.id = 'request-time-bubble';
    bubbleEl.className = 'request-time-bubble';
    document.body.appendChild(bubbleEl);
    return bubbleEl;
  };

  const showTimingBubble = (text, isError = false) => {
    const el = ensureBubble();
    el.textContent = text;
    el.classList.toggle('error', Boolean(isError));
    el.classList.add('visible');

    if (hideTimer) {
      window.clearTimeout(hideTimer);
    }
    hideTimer = window.setTimeout(() => {
      el.classList.remove('visible');
    }, 2600);
  };

  const getNavigationBackendDuration = () => {
    const navEntries = performance.getEntriesByType ? performance.getEntriesByType('navigation') : [];
    const navEntry = navEntries && navEntries.length ? navEntries[0] : null;
    if (!navEntry || !Array.isArray(navEntry.serverTiming)) return null;

    const backendMetric = navEntry.serverTiming.find((metric) => metric && metric.name === 'app');
    if (!backendMetric || !Number.isFinite(backendMetric.duration)) return null;
    return backendMetric.duration;
  };

  const showNavigationTimingBubble = () => {
    const backendDuration = getNavigationBackendDuration();
    if (!Number.isFinite(backendDuration)) return;
    showTimingBubble(`Backend ${backendDuration.toFixed(2)} ms`);
  };

  const resolveRequestUrl = (input) => {
    try {
      if (typeof input === 'string') {
        return new URL(input, window.location.href);
      }
      if (input instanceof URL) {
        return input;
      }
      if (typeof Request !== 'undefined' && input instanceof Request) {
        return new URL(input.url, window.location.href);
      }
    } catch (error) {
      return null;
    }
    return null;
  };

  const isBackendRequest = (requestUrl) => {
    return Boolean(requestUrl && requestUrl.origin === window.location.origin);
  };

  const wrapFetchWithTimingBubble = () => {
    if (typeof window.fetch !== 'function') return;

    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const requestUrl = resolveRequestUrl(args[0]);
      const shouldReport = isBackendRequest(requestUrl);
      const startAt = performance.now();

      try {
        const response = await originalFetch(...args);
        if (shouldReport) {
          const headerValue = Number.parseFloat(response.headers.get('X-Server-Time-Ms') || '');
          const duration = Number.isFinite(headerValue) ? headerValue : (performance.now() - startAt);
          const label = response.ok ? 'Backend' : `Backend ${response.status}`;
          showTimingBubble(`${label} ${duration.toFixed(2)} ms`, !response.ok);
        }
        return response;
      } catch (error) {
        if (shouldReport) {
          const duration = performance.now() - startAt;
          showTimingBubble(`Backend request failed ${duration.toFixed(2)} ms`, true);
        }
        throw error;
      }
    };
  };

  wrapFetchWithTimingBubble();
  if (document.readyState === 'complete') {
    showNavigationTimingBubble();
  } else {
    window.addEventListener('load', showNavigationTimingBubble, { once: true });
  }
})();
