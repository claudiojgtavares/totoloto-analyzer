// Presentation only. Forms, calculations and polling stay with the application.
(() => {
  const navigation = document.getElementById('navigation');
  if (!navigation) return;
  const compact = window.matchMedia('(max-width: 900px)');
  const adapt = () => { navigation.open = !compact.matches; };
  adapt();
  compact.addEventListener('change', adapt);
  navigation.addEventListener('keydown', event => {
    if (event.key === 'Escape' && compact.matches && navigation.open) {
      navigation.open = false;
      navigation.querySelector('summary').focus();
    }
  });
})();
