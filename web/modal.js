/**
 * modal.js - 自定义弹窗组件
 * 替代 alert() 和 confirm()
 */

/**
 * 显示确认弹窗
 * @param {Object} opts
 * @param {string} opts.title - 标题
 * @param {string} opts.desc - 描述
 * @param {string} opts.type - 'danger' | 'warning' | 'info'
 * @param {string} opts.confirmText - 确认按钮文字
 * @param {string} opts.cancelText - 取消按钮文字
 * @returns {Promise<boolean>} 用户是否确认
 */
function showConfirm(opts = {}) {
  return new Promise(resolve => {
    const {
      title = '确认操作',
      desc = '确定要执行此操作吗？',
      type = 'danger',
      confirmText = '确定',
      cancelText = '取消',
    } = opts;

    const icons = {
      danger: '🗑',
      warning: '⚠️',
      info: 'ℹ️',
    };

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-box">
        <div class="modal-icon ${type}">${icons[type] || icons.info}</div>
        <div class="modal-title">${title}</div>
        <div class="modal-desc">${desc}</div>
        <div class="modal-actions">
          <button class="modal-btn modal-btn-cancel">${cancelText}</button>
          <button class="modal-btn modal-btn-${type === 'danger' ? 'danger' : 'primary'}">${confirmText}</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('show'));

    const cleanup = (result) => {
      overlay.classList.remove('show');
      setTimeout(() => overlay.remove(), 200);
      resolve(result);
    };

    overlay.querySelector('.modal-btn-cancel').onclick = () => cleanup(false);
    overlay.querySelector('.modal-btn-danger, .modal-btn-primary').onclick = () => cleanup(true);
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(false); };
  });
}

/**
 * 显示提示弹窗
 * @param {Object} opts
 * @param {string} opts.title - 标题
 * @param {string} opts.desc - 描述
 * @param {string} opts.type - 'info' | 'warning'
 * @returns {Promise<void>}
 */
function showAlert(opts = {}) {
  return new Promise(resolve => {
    const {
      title = '提示',
      desc = '',
      type = 'info',
    } = opts;

    const icons = {
      warning: '⚠️',
      info: 'ℹ️',
      success: '✅',
    };

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-box">
        <div class="modal-icon ${type}">${icons[type] || icons.info}</div>
        <div class="modal-title">${title}</div>
        <div class="modal-desc">${desc}</div>
        <div class="modal-actions">
          <button class="modal-btn modal-btn-primary">知道了</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('show'));

    const cleanup = () => {
      overlay.classList.remove('show');
      setTimeout(() => overlay.remove(), 200);
      resolve();
    };

    overlay.querySelector('.modal-btn-primary').onclick = cleanup;
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };
  });
}
