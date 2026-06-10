/**
 * DeployFAB — floating "Deploy Now" popup.
 *
 * Slides up from the bottom-right after 2.5s. Dismissible via close button.
 * Follows the page's locale (zh/en) via useI18n().
 *
 * Deploy URL logic:
 *   - *.edgeone.app → international (edgeone.ai)
 *   - otherwise     → Tencent Cloud console
 */
import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';

const TEXTS = {
  zh: {
    button: '🚀 一键部署 - 免费!',
    desc: '使用 <a href="https://edgeone.ai/products/pages" target="_blank">EdgeOne Makers</a> 部署你自己的 AI 邮件助手 — 全球 CDN，Serverless Agents，完全免费。',
  },
  en: {
    button: '🚀 Deploy Now - Free!',
    desc: 'Deploy your own AI Email Assistant with <a href="https://edgeone.ai/products/pages" target="_blank">EdgeOne Makers</a> — global CDN, serverless agents, completely free.',
  },
};

export default function DeployFAB() {
  const { locale } = useI18n();
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    // Don't show in headless/test
    if (navigator.userAgent.includes('HeadlessChrome')) return;
    const showFab = (typeof (window as any).__SHOW_FAB__ !== 'undefined')
      ? (window as any).__SHOW_FAB__
      : true;
    if (!showFab) return;

    const timer = setTimeout(() => setVisible(true), 2500);
    return () => clearTimeout(timer);
  }, []);

  const handleDeploy = useCallback(() => {
    const hostname = window.location.hostname;
    const parts = hostname.split('.');
    const projectName = 'email-assistant-agent';
    const domain = parts.slice(1).join('.');

    if (domain === 'edgeone.app') {
      window.open(
        `https://edgeone.ai/pages/new?template=${projectName}&from=github`,
        '_blank',
      );
    } else {
      window.open(
        `https://console.cloud.tencent.com/edgeone/pages/new?from=github&template=${projectName}`,
        '_blank',
      );
    }
  }, []);

  const handleClose = useCallback(() => {
    setVisible(false);
    setTimeout(() => setDismissed(true), 500);
  }, []);

  if (dismissed) return null;

  const t = TEXTS[locale];

  return (
    <div style={{ ...popup, bottom: visible ? 20 : -300 }}>
      <style>{`
        #deploy-fab-popup a {
          color: #67e8f9 !important;
          text-decoration: underline;
          text-underline-offset: 2px;
          font-weight: 600;
        }
        #deploy-fab-popup a:hover {
          color: #ffffff !important;
        }
      `}</style>
      <svg
        onClick={handleClose}
        style={closeBtn}
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
      >
        <path d="M16 8L8 16" stroke="#E0E0E0" strokeWidth="2" strokeLinecap="round" />
        <path d="M8 8L16 16" stroke="#E0E0E0" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <div style={deployBtn} onClick={handleDeploy}>
        {t.button}
      </div>
      <p id="deploy-fab-popup" style={descStyle} dangerouslySetInnerHTML={{ __html: t.desc }} />
    </div>
  );
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const popup: React.CSSProperties = {
  boxSizing: 'content-box',
  display: 'block',
  position: 'fixed',
  zIndex: 9999,
  right: 20,
  background: 'rgba(0, 0, 0, 0.85)',
  color: 'white',
  padding: 16,
  borderRadius: 12,
  width: 260,
  boxShadow: '0 4px 24px rgba(0,0,0,0.25)',
  fontSize: 13,
  transition: 'bottom 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)',
  fontFamily: 'system-ui, -apple-system, sans-serif',
  textAlign: 'center',
  backdropFilter: 'blur(8px)',
};

const closeBtn: React.CSSProperties = {
  position: 'absolute',
  top: 10,
  right: 10,
  cursor: 'pointer',
  opacity: 0.6,
};

const deployBtn: React.CSSProperties = {
  fontSize: 14,
  backgroundColor: '#0d9488',
  color: 'white',
  border: 'none',
  padding: '10px 24px',
  borderRadius: 20,
  cursor: 'pointer',
  marginBottom: 10,
  marginTop: 8,
  display: 'inline-block',
  fontWeight: 600,
  lineHeight: '20px',
};

const descStyle: React.CSSProperties = {
  margin: 0,
  lineHeight: 1.5,
  textAlign: 'left',
  fontFamily: 'system-ui, sans-serif',
  color: 'rgba(255,255,255,0.85)',
  fontSize: 12,
};
