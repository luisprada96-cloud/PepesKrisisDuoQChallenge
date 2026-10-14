/* The links remain usable without JavaScript; mobile gets a compact menu. */
document.addEventListener('DOMContentLoaded', () => {
  const header = document.querySelector('.site-header');
  const toggle = document.getElementById('nav-menu-toggle');
  const links = document.getElementById('primary-navigation');
  if (!header || !toggle || !links) return;
  header.classList.add('navigation-enhanced');
  toggle.hidden = false;
  function setOpen(open) {
    header.classList.toggle('navigation-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Cerrar menú de navegación' : 'Abrir menú de navegación');
    toggle.querySelector('i').className = open ? 'fa-solid fa-xmark' : 'fa-solid fa-bars';
  }
  toggle.addEventListener('click', () => setOpen(toggle.getAttribute('aria-expanded') !== 'true'));
  links.addEventListener('click', event => { if (event.target.closest('a')) setOpen(false); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && header.classList.contains('navigation-open')) {
      setOpen(false);
      toggle.focus();
    }
  });
  document.addEventListener('click', event => { if (!header.contains(event.target)) setOpen(false); });
  const desktop = window.matchMedia('(min-width: 901px)');
  desktop.addEventListener('change', () => { if (desktop.matches) setOpen(false); });
});
