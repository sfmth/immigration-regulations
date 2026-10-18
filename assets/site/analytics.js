/* Page views only: never send legal search terms, URL queries, or fragments. */
(function () {
  'use strict';
  const config = window.IMMIGRATION_SITE || {};
  if (!/^G-[A-Z0-9]+$/.test(config.google_analytics_id || '')) return;
  if (navigator.globalPrivacyControl === true || navigator.doNotTrack === '1') return;
  const cleanURL = value => {
    try { const url = new URL(value); return url.origin + url.pathname; }
    catch (_) { return ''; }
  };
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag('js', new Date());
  window.gtag('config', config.google_analytics_id, {
    send_page_view: false,
    page_location: cleanURL(window.location.href),
    page_referrer: cleanURL(document.referrer),
    allow_google_signals: false,
    allow_ad_personalization_signals: false
  });
  window.gtag('event', 'page_view', {
    page_location: cleanURL(window.location.href),
    page_referrer: cleanURL(document.referrer),
    page_title: document.title
  });
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://www.googletagmanager.com/gtag/js?id=' + config.google_analytics_id;
  document.head.append(script);
})();
