import arcgisDarkTheme from '@arcgis/core/assets/esri/themes/dark/main.css?url';
import arcgisLightTheme from '@arcgis/core/assets/esri/themes/light/main.css?url';

export type Theme = 'light' | 'dark';

export function getThemePreference(): Theme {
  try {
    return window.localStorage.getItem('oseas-theme') === 'dark' ? 'dark' : 'light';
  } catch (error) {
    console.warn('Could not read the saved theme preference; using light mode.', error);
    return 'light';
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  document.body.classList.toggle('calcite-mode-light', theme === 'light');
  document.body.classList.toggle('calcite-mode-dark', theme === 'dark');

  let stylesheet = document.querySelector<HTMLLinkElement>('#arcgis-theme');
  if (!stylesheet) {
    stylesheet = document.createElement('link');
    stylesheet.id = 'arcgis-theme';
    stylesheet.rel = 'stylesheet';
    document.head.append(stylesheet);
  }
  stylesheet.href = theme === 'dark' ? arcgisDarkTheme : arcgisLightTheme;

  try {
    window.localStorage.setItem('oseas-theme', theme);
  } catch (error) {
    console.warn('Could not save the theme preference for the next visit.', error);
  }
}
