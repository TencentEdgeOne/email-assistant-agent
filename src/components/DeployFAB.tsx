/**
 * DeployButton + GitHubButton — inline header buttons.
 *
 * DeployButton: follows the page's locale (zh/en) via useI18n().
 * Determines deploy URL based on the current hostname:
 *   - *.edgeone.dev → international (edgeone.ai)
 *   - otherwise     → Tencent Cloud console
 *
 * GitHubButton: static link to the source repo.
 */
import { useCallback } from 'react';
import { tokens } from '../design-tokens';
import { useI18n } from '../i18n';

const TEMPLATE_NAME = 'email-assistant-agent';
const GITHUB_URL = 'https://github.com/TencentEdgeOne/email-assistant-agent';

const EDGEONE_AI_DEPLOY_URL = `https://edgeone.ai/makers/new?template=${TEMPLATE_NAME}&from=within&fromAgent=1&agentLang=python`;
const TENCENT_CLOUD_DEPLOY_URL = `https://console.cloud.tencent.com/edgeone/makers/new?template=${TEMPLATE_NAME}&from=within&fromAgent=1&agentLang=python`;

function getDeployUrl(): string {
  if (typeof window === 'undefined') return TENCENT_CLOUD_DEPLOY_URL;
  const hostname = window.location.hostname;
  const parts = hostname.split('.');
  const domain = parts.slice(1).join('.');
  return domain === 'edgeone.dev' ? EDGEONE_AI_DEPLOY_URL : TENCENT_CLOUD_DEPLOY_URL;
}

export default function DeployButton() {
  const { locale } = useI18n();

  const handleDeploy = useCallback(() => {
    window.open(getDeployUrl(), '_blank');
  }, []);

  const label = locale === 'zh' ? '一键部署' : 'Deploy';

  return (
    <button
      type="button"
      onClick={handleDeploy}
      style={deployBtnStyle}
      title={locale === 'zh' ? '部署到 EdgeOne Makers' : 'Deploy to EdgeOne Makers'}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z" />
      </svg>
      <span>{label}</span>
    </button>
  );
}

export function GitHubButton() {
  return (
    <a
      href={GITHUB_URL}
      target="_blank"
      rel="noopener noreferrer"
      style={githubBtnStyle}
      title="View source on GitHub"
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
      </svg>
    </a>
  );
}

const deployBtnStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  padding: '6px 14px',
  borderRadius: tokens.radius.md,
  fontSize: tokens.fontSize.sm,
  fontWeight: tokens.fontWeight.semibold,
  color: '#ffffff',
  background: tokens.color.brand,
  border: 'none',
  cursor: 'pointer',
  lineHeight: 1.2,
  whiteSpace: 'nowrap',
  flexShrink: 0,
};

const githubBtnStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 30,
  height: 30,
  borderRadius: tokens.radius.md,
  color: tokens.color.textMuted,
  background: 'transparent',
  border: `1px solid ${tokens.color.border}`,
  cursor: 'pointer',
  flexShrink: 0,
  textDecoration: 'none',
};
