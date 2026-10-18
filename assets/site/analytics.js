/* Inlined before Google's unmodified tag; never include legal search terms. */
(function () {
  'use strict';
  const measurementId = '__GA4_MEASUREMENT_ID__';
  window['ga-disable-' + measurementId] =
    navigator.globalPrivacyControl === true || navigator.doNotTrack === '1';
  const cleanURL = value => {
    try { const url = new URL(value); return url.origin + url.pathname; }
    catch (_) { return ''; }
  };
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag('set', {
    page_location: cleanURL(window.location.href),
    page_referrer: cleanURL(document.referrer),
    allow_google_signals: false,
    allow_ad_personalization_signals: false
  });
})();
