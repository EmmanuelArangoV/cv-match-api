# Portal de documentación del Backend

Este proyecto Docusaurus publica el contenido de `../docs`. Se mantiene separado del runtime
Python para que el pipeline de Azure DevOps pueda construir API y documentación de forma
independiente.

```bash
npm install
npm run start
npm run build
```

`npm run build` genera el sitio estático en `build/`. En CI se puede publicar esa carpeta y
configurar `DOCS_URL` y, si aplica, `DOCS_BASE_URL`.
