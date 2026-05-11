const forms = document.querySelectorAll('form[data-todo]');

forms.forEach((form) => {
  form.addEventListener('submit', (event) => {
    event.preventDefault();

    const todoMessage = form.dataset.todo || 'TODO: Backend API is not implemented yet.';
    const resultBox = form.parentElement.querySelector('.result-box');

    if (resultBox) {
      resultBox.textContent = todoMessage;
      return;
    }

    alert(todoMessage);
  });
});

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

// TODO: Replace with real API calls (fetch/axios) and error handling.
