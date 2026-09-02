import type { SidebarsConfig } from '@docusaurus/plugin-content-docs'

const sidebars: SidebarsConfig = {
  backend: [
    'index',
    {
      type: 'category',
      label: 'Código y arquitectura',
      items: ['architecture', 'code-map', 'lifecycle-and-projections', 'api_contract'],
    },
    {
      type: 'category',
      label: 'Flujos operativos',
      items: ['async-work', 'deployment', 'operations', 'integrations', 'costs', 'whatsapp_api_contract'],
    },
  ],
}

export default sidebars
