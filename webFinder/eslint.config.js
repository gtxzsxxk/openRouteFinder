import vue from 'eslint-plugin-vue'
import prettier from 'eslint-config-prettier'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // Base TypeScript config
  ...tseslint.configs.recommended,

  // Vue recommended rules
  ...vue.configs['flat/recommended'],

  // Prettier must come last to disable conflicting style rules
  prettier,

  {
    files: ['**/*.{vue,ts,tsx,js,mjs,cjs}'],
    languageOptions: {
      parser: vue.parser,
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
        sourceType: 'module',
      },
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/require-default-prop': 'off',
      'vue/one-component-per-file': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },

  // Ignore generated/built files
  {
    ignores: ['dist/', 'node_modules/', 'public/'],
  },
)
