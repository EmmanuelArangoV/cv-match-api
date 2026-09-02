import type { Config } from '@docusaurus/types'
import type * as Preset from '@docusaurus/preset-classic'

const config: Config = {
  title: 'RIWI MATCH Backend',
  tagline: 'Referencia técnica de la API, workers y operaciones',
  url: process.env.DOCS_URL ?? 'http://localhost',
  baseUrl: process.env.DOCS_BASE_URL ?? '/',
  organizationName: 'Riwi',
  projectName: 'cv-match-api',
  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },
  i18n: {
    defaultLocale: 'es',
    locales: ['es'],
  },
  presets: [
    [
      'classic',
      {
        docs: {
          path: '../docs',
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/EmmanuelArangoV/cv-match-api/edit/main/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
    navbar: {
      title: 'RIWI MATCH · Backend',
      items: [
        { to: '/', label: 'Documentación', position: 'left' },
        {
          href: 'https://github.com/EmmanuelArangoV/cv-match-api',
          label: 'Código',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Fuente de verdad',
          items: [
            { label: 'OpenAPI', to: '/api' },
            { label: 'Estado operativo', to: '/operations' },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} RIWI MATCH.`,
    },
  } satisfies Preset.ThemeConfig,
}

export default config
