/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        verdict: {
          passed: "#16a34a",
          failed: "#dc2626",
          unresolved: "#d97706",
          skipped: "#6b7280",
        },
      },
    },
  },
  plugins: [],
};
