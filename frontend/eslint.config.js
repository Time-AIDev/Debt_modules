import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import hooks from 'eslint-plugin-react-hooks'

// Run from the repository root with --config frontend/eslint.config.js.
// Correctness checks deliberately do not introduce a formatting or prop-types migration.
export default [
  { ignores: ['**/node_modules/**', '**/dist/**', '**/.test-artifacts/**', 'reports/**', 'docs/**'] },
  {
    files: ['frontend/**/*.{js,jsx,mjs}', 'scripts/**/*.{js,mjs}'],
    languageOptions: { ecmaVersion: 'latest', sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } }, globals: { ...globals.browser, ...globals.node } },
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    plugins: { react, 'react-hooks': hooks },
    rules: { ...js.configs.recommended.rules,
      'no-unused-vars': 'off',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'react/jsx-uses-vars': 'error', 'react/jsx-no-undef': 'error', 'react/jsx-no-duplicate-props': 'error',
      'react-hooks/rules-of-hooks': 'error',
    },
  },
  { files: ['frontend/**/*.test.{js,jsx}', 'frontend/src/test-*.{js,jsx}'],
    languageOptions: { globals: { ...globals.vitest } } },
]
