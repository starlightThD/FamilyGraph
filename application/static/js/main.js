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
