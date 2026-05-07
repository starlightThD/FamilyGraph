const forms = document.querySelectorAll('form[data-todo]');

forms.forEach((form) => {
  form.addEventListener('submit', (event) => {
    event.preventDefault();

    const todoMessage = form.dataset.todo || 'TODO: 后端接口尚未实现。';
    const resultBox = form.parentElement.querySelector('.result-box');

    if (resultBox) {
      resultBox.textContent = todoMessage;
      return;
    }

    alert(todoMessage);
  });
});

// TODO: 后端就绪后，替换为真实 API 调用（fetch/axios）与错误处理逻辑。
