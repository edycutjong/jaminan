import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import react from "eslint-plugin-react";

// eslint-config-next is not used: its @next/eslint-plugin-next -> fast-glob -> micromatch -> braces chain carries an
// unpatched ReDoS advisory (GHSA-vfj7-8cjw-p6xm). `next build` still type-checks, and these rules cover React and TS.
const config = [
  { ignores: [".next/**", "node_modules/**", ".venv/**", "next-env.d.ts", "tools/**"] },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks, react },
    settings: { react: { version: "19" } },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react/jsx-key": "error",
      "react/no-unescaped-entities": "error",
      // The API payloads are untyped JSON documents; `any` at that boundary is deliberate.
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
];

export default config;
